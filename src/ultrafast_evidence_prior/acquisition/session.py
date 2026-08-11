"""Application-layer state machine for bounded adaptive evidence acquisition."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from ultrafast_evidence_prior.acquisition.coverage import (
    EvidenceCoverageAssessor,
    RequirementCoverageSpecCompiler,
)
from ultrafast_evidence_prior.acquisition.planner import (
    DeterministicGapQueryPlanner,
    validate_query_plan,
)
from ultrafast_evidence_prior.extraction import PROMPT_VERSION, TypedEvidenceExtractor
from ultrafast_evidence_prior.knowledge_store import StructuredKnowledgeStoreV2
from ultrafast_evidence_prior.requirements import as_retrieval_requirement, requirement_signature
from ultrafast_evidence_prior.schemas import (
    AcquisitionRoundTrace,
    AcquisitionTrace,
    EvidenceIRV2,
    EvidenceMiss,
    ExtractionStatus,
    KnowledgeRequirementV1,
    RequirementCoverageSpec,
    ResolvedTaskV1,
    SupplementalQuery,
    ValidationState,
)
from ultrafast_knowledge.evidence_pipeline import PersistentScientificPaperRepository
from ultrafast_knowledge.evidence_pipeline.schemas import EvidenceWindow, PaperCandidate

StopReason = Literal[
    "COVERAGE_SATISFIED",
    "MAX_ROUNDS",
    "QUERY_BUDGET_EXHAUSTED",
    "NO_NOVEL_HITS",
    "NO_COVERAGE_GAIN",
    "NO_ELIGIBLE_GAPS",
    "INVALID_QUERY_PLAN",
    "INDEX_NOT_READY",
]


@dataclass(frozen=True, slots=True)
class AcquisitionBudget:
    max_rounds: int = 2
    max_supplemental_queries: int = 3
    max_papers: int = 8
    max_windows: int = 32


@dataclass(slots=True)
class EvidenceAcquisitionResult:
    items: list[EvidenceIRV2]
    misses: list[EvidenceMiss]
    candidates: list[PaperCandidate]
    trace: AcquisitionTrace
    knowledge_reused_count: int
    llm_call_count: int


class EvidenceAcquisitionSession:
    """Code controls retrieval and stopping; no model may approve evidence or priors."""

    def __init__(
        self,
        *,
        repository: PersistentScientificPaperRepository,
        knowledge_store: StructuredKnowledgeStoreV2,
        extractor: TypedEvidenceExtractor,
        paper_top_k: int = 3,
        windows_per_paper: int = 8,
        budget: AcquisitionBudget | None = None,
        coverage_compiler: RequirementCoverageSpecCompiler | None = None,
        coverage_assessor: EvidenceCoverageAssessor | None = None,
        query_planner: DeterministicGapQueryPlanner | None = None,
    ) -> None:
        self.repository = repository
        self.knowledge_store = knowledge_store
        self.extractor = extractor
        self.paper_top_k = paper_top_k
        self.windows_per_paper = windows_per_paper
        self.budget = budget or AcquisitionBudget()
        self.coverage_compiler = coverage_compiler or RequirementCoverageSpecCompiler()
        self.coverage_assessor = coverage_assessor or EvidenceCoverageAssessor()
        self.query_planner = query_planner or DeterministicGapQueryPlanner()

    def run(
        self,
        task: ResolvedTaskV1,
        requirement: KnowledgeRequirementV1,
        *,
        force_reextract: bool = False,
    ) -> EvidenceAcquisitionResult:
        spec = self.coverage_compiler.compile(task, requirement)
        signature = requirement_signature(requirement)
        items: list[EvidenceIRV2] = []
        item_ids: set[str] = set()
        misses: list[EvidenceMiss] = []
        rounds: list[AcquisitionRoundTrace] = []
        candidate_state: dict[str, PaperCandidate] = {}
        candidate_votes: dict[str, float] = {}
        window_state: dict[str, list[EvidenceWindow]] = {}
        attempted: set[str] = set()
        llm_calls = 0
        knowledge_reused = 0

        cached = []
        if not force_reextract:
            cached = self.knowledge_store.for_requirement(
                requirement_signature=signature,
                extractor_model=self.extractor.model,
                prompt_version=PROMPT_VERSION,
            )
        self._add_items(items, item_ids, cached)
        knowledge_reused = len(cached)
        cached_keys = {self._evidence_key(item) for item in cached}
        for item in cached:
            key = self._evidence_key(item)
            candidate_state.setdefault(
                key,
                PaperCandidate(
                    paper_id=item.paper_id,
                    document_version_id=item.document_version_id,
                    score=0.0,
                    retrieval_routes=["structured_knowledge"],
                ),
            )
            candidate_votes.setdefault(key, 0.0)
        coverage = self.coverage_assessor.assess(requirement, spec, items)
        if cached:
            rounds.append(
                AcquisitionRoundTrace(
                    round=0,
                    planner_type="CACHE",
                    candidate_count=len(candidate_state),
                    validated_evidence_count=self._validated_count(items),
                    coverage=coverage,
                )
            )
        if coverage.operationally_sufficient:
            return self._result(
                requirement,
                spec,
                items,
                misses,
                candidate_state,
                rounds,
                "COVERAGE_SATISFIED",
                knowledge_reused,
                llm_calls,
                total_queries=0,
            )

        retrieval_requirement = as_retrieval_requirement(requirement)
        baseline_query = self.repository.retriever.query_compiler.compile(
            retrieval_requirement
        ).query_text
        baseline = SupplementalQuery(
            query_id=f"baseline-{requirement.requirement_id}",
            gap_ids=[item.facet_id for item in spec.facets],
            query_text=baseline_query[:256],
            top_k=self.paper_top_k,
        )
        candidates, windows = self.repository.retrieve(
            retrieval_requirement,
            paper_top_k=self.paper_top_k,
            windows_per_paper=self.windows_per_paper,
        )
        new_candidates, new_windows = self._merge_retrieval(
            baseline,
            candidates,
            windows,
            candidate_state,
            candidate_votes,
            window_state,
        )
        calls = self._extract_changed(
            requirement,
            signature,
            candidate_state,
            window_state,
            attempted,
            cached_keys,
            items,
            item_ids,
            misses,
        )
        llm_calls += calls
        coverage = self.coverage_assessor.assess(requirement, spec, items)
        rounds.append(
            AcquisitionRoundTrace(
                round=0,
                planner_type="BASELINE",
                queries=[baseline],
                candidate_count=len(candidate_state),
                new_candidate_count=new_candidates,
                window_count=self._window_count(window_state),
                new_window_count=new_windows,
                extraction_calls=calls,
                validated_evidence_count=self._validated_count(items),
                coverage=coverage,
            )
        )
        if coverage.operationally_sufficient:
            return self._result(
                requirement,
                spec,
                items,
                misses,
                candidate_state,
                rounds,
                "COVERAGE_SATISFIED",
                knowledge_reused,
                llm_calls,
                total_queries=1,
            )
        if self.budget.max_rounds <= 1:
            return self._result(
                requirement,
                spec,
                items,
                misses,
                candidate_state,
                rounds,
                "MAX_ROUNDS",
                knowledge_reused,
                llm_calls,
                total_queries=1,
            )

        plan = self.query_planner.plan(
            requirement,
            spec,
            coverage,
            round_number=1,
            top_k=self.paper_top_k,
            previous_queries=[baseline_query],
        )
        if not plan.queries:
            return self._result(
                requirement,
                spec,
                items,
                misses,
                candidate_state,
                rounds,
                "NO_ELIGIBLE_GAPS",
                knowledge_reused,
                llm_calls,
                total_queries=1,
            )
        if len(plan.queries) > self.budget.max_supplemental_queries:
            return self._result(
                requirement,
                spec,
                items,
                misses,
                candidate_state,
                rounds,
                "QUERY_BUDGET_EXHAUSTED",
                knowledge_reused,
                llm_calls,
                total_queries=1,
            )
        try:
            validate_query_plan(
                plan,
                requirement,
                coverage,
                known_paper_ids={item.paper_id for item in candidate_state.values()},
            )
        except ValueError:
            return self._result(
                requirement,
                spec,
                items,
                misses,
                candidate_state,
                rounds,
                "INVALID_QUERY_PLAN",
                knowledge_reused,
                llm_calls,
                total_queries=1,
            )

        previous_coverage = coverage.coverage_ratio
        round_new_candidates = 0
        round_new_windows = 0
        for query in plan.queries:
            candidates, windows = self.repository.retrieve_query(
                retrieval_requirement,
                query.query_text,
                paper_top_k=query.top_k,
                windows_per_paper=self.windows_per_paper,
            )
            self._prefer_sections(windows, query.preferred_sections)
            added_candidates, added_windows = self._merge_retrieval(
                query,
                candidates,
                windows,
                candidate_state,
                candidate_votes,
                window_state,
            )
            round_new_candidates += added_candidates
            round_new_windows += added_windows
        stop_reason: StopReason
        if round_new_candidates == 0 and round_new_windows == 0:
            stop_reason = "NO_NOVEL_HITS"
            calls = 0
        else:
            calls = self._extract_changed(
                requirement,
                signature,
                candidate_state,
                window_state,
                attempted,
                set(),
                items,
                item_ids,
                misses,
            )
            llm_calls += calls
            coverage = self.coverage_assessor.assess(requirement, spec, items)
            if coverage.operationally_sufficient:
                stop_reason = "COVERAGE_SATISFIED"
            elif coverage.coverage_ratio <= previous_coverage:
                stop_reason = "NO_COVERAGE_GAIN"
            else:
                stop_reason = "MAX_ROUNDS"
        rounds.append(
            AcquisitionRoundTrace(
                round=1,
                planner_type="DETERMINISTIC",
                queries=plan.queries,
                candidate_count=len(candidate_state),
                new_candidate_count=round_new_candidates,
                window_count=self._window_count(window_state),
                new_window_count=round_new_windows,
                extraction_calls=calls,
                validated_evidence_count=self._validated_count(items),
                coverage=coverage,
            )
        )
        return self._result(
            requirement,
            spec,
            items,
            misses,
            candidate_state,
            rounds,
            stop_reason,
            knowledge_reused,
            llm_calls,
            total_queries=1 + len(plan.queries),
        )

    def _extract_changed(
        self,
        requirement: KnowledgeRequirementV1,
        signature: str,
        candidate_state: dict[str, PaperCandidate],
        window_state: dict[str, list[EvidenceWindow]],
        attempted: set[str],
        skip_keys: set[str],
        items: list[EvidenceIRV2],
        item_ids: set[str],
        misses: list[EvidenceMiss],
    ) -> int:
        calls = 0
        for candidate in self._ordered_candidates(candidate_state):
            key = self._candidate_key(candidate)
            windows = window_state.get(key, [])[: self.windows_per_paper]
            fingerprint = self._window_fingerprint(key, windows)
            attempt_key = f"{key}:{fingerprint}"
            if attempt_key in attempted:
                continue
            attempted.add(attempt_key)
            if key in skip_keys:
                continue
            outcome = self.extractor.extract(requirement, candidate, windows)
            calls += outcome.llm_call_count
            self._add_items(items, item_ids, outcome.items)
            for item in outcome.items:
                if item.validation_state == ValidationState.VALIDATED:
                    self.knowledge_store.upsert(item, requirement_signature=signature)
            if outcome.status != ExtractionStatus.FOUND or not outcome.items:
                misses.append(
                    EvidenceMiss(
                        requirement_id=requirement.requirement_id,
                        paper_id=candidate.paper_id,
                        document_version_id=candidate.document_version_id,
                        status=outcome.status,
                        reason=outcome.reason,
                    )
                )
        return calls

    def _merge_retrieval(
        self,
        query: SupplementalQuery,
        candidates: list[PaperCandidate],
        windows: dict[str, list[EvidenceWindow]],
        candidate_state: dict[str, PaperCandidate],
        candidate_votes: dict[str, float],
        window_state: dict[str, list[EvidenceWindow]],
    ) -> tuple[int, int]:
        before_candidates = set(candidate_state)
        before_windows = self._window_ids(window_state)
        for rank, candidate in enumerate(candidates, 1):
            key = self._candidate_key(candidate)
            candidate_votes[key] = candidate_votes.get(key, 0.0) + 1.0 / (60 + rank)
            existing = candidate_state.get(key)
            routes = list(
                dict.fromkeys(
                    [
                        *(existing.retrieval_routes if existing else []),
                        *candidate.retrieval_routes,
                        f"query:{query.query_id}",
                    ]
                )
            )
            candidate_state[key] = candidate.model_copy(
                update={
                    "score": candidate_votes[key],
                    "paper_index_score": max(
                        candidate.paper_index_score,
                        existing.paper_index_score if existing else 0.0,
                    ),
                    "global_block_score": max(
                        candidate.global_block_score,
                        existing.global_block_score if existing else 0.0,
                    ),
                    "retrieval_routes": routes,
                }
            )
            by_center = {item.center_block_id: item for item in window_state.get(key, [])}
            for window in windows.get(key, []):
                current = by_center.get(window.center_block_id)
                if current is None or window.score > current.score:
                    by_center[window.center_block_id] = window
            window_state[key] = sorted(
                by_center.values(), key=lambda item: item.score, reverse=True
            )
        self._apply_budgets(candidate_state, candidate_votes, window_state)
        return (
            len(set(candidate_state) - before_candidates),
            len(self._window_ids(window_state) - before_windows),
        )

    def _apply_budgets(
        self,
        candidate_state: dict[str, PaperCandidate],
        candidate_votes: dict[str, float],
        window_state: dict[str, list[EvidenceWindow]],
    ) -> None:
        keep_candidates = {
            self._candidate_key(item)
            for item in self._ordered_candidates(candidate_state)[: self.budget.max_papers]
        }
        for key in list(candidate_state):
            if key not in keep_candidates:
                candidate_state.pop(key, None)
                candidate_votes.pop(key, None)
                window_state.pop(key, None)
        ranked_windows = sorted(
            ((key, window) for key, values in window_state.items() for window in values),
            key=lambda item: item[1].score,
            reverse=True,
        )[: self.budget.max_windows]
        keep_window_ids = {(key, window.center_block_id) for key, window in ranked_windows}
        for key, values in list(window_state.items()):
            window_state[key] = [
                item for item in values if (key, item.center_block_id) in keep_window_ids
            ]

    @staticmethod
    def _prefer_sections(
        windows: dict[str, list[EvidenceWindow]],
        preferred_sections: list[str],
    ) -> None:
        preferred = {item.casefold() for item in preferred_sections}
        if not preferred:
            return
        for key, values in windows.items():
            reranked = []
            for window in values:
                center = next(
                    (item for item in window.blocks if item.block_id == window.center_block_id),
                    None,
                )
                boost = (
                    0.05 if center and (center.section_type or "").casefold() in preferred else 0.0
                )
                reranked.append(window.model_copy(update={"score": window.score + boost}))
            windows[key] = sorted(reranked, key=lambda item: item.score, reverse=True)

    def _result(
        self,
        requirement: KnowledgeRequirementV1,
        spec: RequirementCoverageSpec,
        items: list[EvidenceIRV2],
        misses: list[EvidenceMiss],
        candidate_state: dict[str, PaperCandidate],
        rounds: list[AcquisitionRoundTrace],
        stop_reason: StopReason,
        knowledge_reused: int,
        llm_calls: int,
        *,
        total_queries: int,
    ) -> EvidenceAcquisitionResult:
        trace = AcquisitionTrace(
            requirement_id=requirement.requirement_id,
            coverage_spec=spec,
            rounds=rounds,
            stop_reason=stop_reason,
            index_revisions=self._index_revisions(),
            total_queries=total_queries,
            total_extraction_calls=llm_calls,
        )
        return EvidenceAcquisitionResult(
            items=items,
            misses=misses,
            candidates=self._ordered_candidates(candidate_state),
            trace=trace,
            knowledge_reused_count=knowledge_reused,
            llm_call_count=llm_calls,
        )

    def _index_revisions(self) -> dict[str, str]:
        output: dict[str, str] = {}
        for name in ("paper", "block"):
            state = self.repository.store.index_state(name)
            if state is not None:
                output[name] = str(state["revision"])
        return output

    @staticmethod
    def _add_items(
        target: list[EvidenceIRV2],
        known_ids: set[str],
        values: list[EvidenceIRV2],
    ) -> None:
        for item in values:
            if item.evidence_id not in known_ids:
                target.append(item)
                known_ids.add(item.evidence_id)

    @staticmethod
    def _validated_count(items: list[EvidenceIRV2]) -> int:
        return sum(item.validation_state == ValidationState.VALIDATED for item in items)

    @staticmethod
    def _candidate_key(candidate: PaperCandidate) -> str:
        return f"{candidate.paper_id}::{candidate.document_version_id}"

    @staticmethod
    def _evidence_key(evidence: EvidenceIRV2) -> str:
        return f"{evidence.paper_id}::{evidence.document_version_id}"

    @staticmethod
    def _window_fingerprint(key: str, windows: list[EvidenceWindow]) -> str:
        payload = "\n".join([key, *(item.center_block_id for item in windows)])
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @staticmethod
    def _window_ids(windows: dict[str, list[EvidenceWindow]]) -> set[tuple[str, str]]:
        return {(key, item.center_block_id) for key, values in windows.items() for item in values}

    @staticmethod
    def _window_count(windows: dict[str, list[EvidenceWindow]]) -> int:
        return sum(len(values) for values in windows.values())

    @staticmethod
    def _ordered_candidates(
        candidates: dict[str, PaperCandidate],
    ) -> list[PaperCandidate]:
        return sorted(
            candidates.values(),
            key=lambda item: (-item.score, item.paper_id, item.document_version_id),
        )
