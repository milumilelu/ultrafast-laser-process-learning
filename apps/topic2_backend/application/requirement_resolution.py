"""RequirementResolutionService (M3) - the only orchestrator that turns
KnowledgeRequirements into validated EvidenceIR through the scientific chain.

    KnowledgeRequirement
      -> RetrievalQueryPlan
      -> ScientificCorpusBuilder      (EvidenceCorpusPack, in-process RAG)
      -> ScientificKnowledgeService   (per-source LLM reading, cache-first)
      -> Deterministic validation
      -> validated candidates -> EvidenceIR items (provenance-preserving)
      -> per-dimension applicability -> typed PriorObjectSet (downstream)

Two source qualities over the same implementation:
- RESEARCH     : real LLM required; cache misses invoke the real reading.
- DEMO_FIXTURE : pre-recorded analysis cache (CURATED_LITERATURE_FIXTURE);
                 a cache miss fails closed (no silent fake reading).
- SANDBOX      : stub LLM; cache misses fail closed.

The agent's own HTTP workflow universe is NOT part of this chain: topic2 is
the composition root and consumes the knowledge modules in-process against
the shared memory DB (same tables, same cache).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from packages.scientific_retrieval.planner import plan_retrieval

VALIDATED_REVIEW_STATUS = "accepted_as_literature_evidence"

# CandidateType -> EvidenceIR claim_type (Topic2 evidence vocabulary)
CLAIM_TYPE_MAP: dict[str, str] = {
    "threshold": "threshold",
    "material_property": "material_property",
    "optical_property": "material_property",
    "parameter_range": "range_preference",
    "reported_optimum": "range_preference",
    "parameter_effect": "parameter_direction",
    "relative_importance": "relative_importance",
    "functional_shape": "functional_shape",
    "formula": "formula",
    "mechanism": "mechanism_model",
    "parameter_value": "material_property",
}

# KnowledgeRequirement type -> corpus retrieval intents (canonical lowercase values)
REQUIREMENT_TYPE_INTENTS: dict[str, list[str]] = {
    "PARAMETER_PRIOR": ["threshold", "material_property", "optical_property"],
    "threshold": ["threshold", "material_property"],
    "MECHANISM_MODEL": ["mechanism", "formula"],
    "process_mechanism": ["mechanism", "interaction"],
    "PATH_STRATEGY": ["reported_optimum", "parameter_condition"],
    "reported_optimum": ["reported_optimum"],
    "parameter_effect": ["parameter_effect"],
    "PARAMETER_EFFECT": ["parameter_effect"],
    "formula": ["formula"],
    "material_property": ["material_property"],
    "experimental_condition": ["parameter_condition", "historical_analog"],
}

ProgressCallback = Callable[[str, dict[str, Any]], None]


class RequirementResolutionError(Exception):
    """Scientific chain could not produce evidence (fail closed)."""


class _CacheMissStubLLM:
    """Fail-closed stub: never silently fakes a reading."""

    def __init__(self, mode: str):
        self.mode = mode

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict:
        raise RequirementResolutionError(
            f"{self.mode} 模式缺少预录分析缓存且无真实 LLM：科学精读无法执行"
        )


def build_real_llm_client() -> Any:
    """Real LLM client from the agent config store; mock is refused."""
    from ultrafast_memory.core.llm_config import (
        get_llm_config,
        restore_api_key_from_store,
    )
    from ultrafast_memory.llm.factory import create_llm_client
    from ultrafast_memory.llm.mock import MockLLMClient

    restore_api_key_from_store()
    client = create_llm_client(get_llm_config())
    if isinstance(client, MockLLMClient):
        raise RequirementResolutionError(
            "LLM 未配置：RESEARCH 模式科学精读需要真实 LLM"
        )
    return client


class ScientificSourceAdapter:
    """In-process adapter to the agent knowledge store."""

    def __init__(
        self,
        *,
        connection: Callable[[], Any] | None = None,
        llm_client: Any | None = None,
        model: str = "scientific-reading-v1",
        execution_mode: str = "DEMO_FIXTURE",
    ):
        self.connection = connection
        self.llm_client = llm_client
        self.model = model
        self.execution_mode = execution_mode

    def _client(self) -> Any:
        if self.llm_client is not None:
            return self.llm_client
        if self.execution_mode == "RESEARCH":
            return build_real_llm_client()
        return _CacheMissStubLLM(self.execution_mode)

    def build_corpus(
        self, task_scope: dict[str, Any], *, intents: list[str] | None = None
    ) -> dict[str, Any]:
        from ultrafast_knowledge.corpus.builder import ScientificCorpusBuilder
        from ultrafast_knowledge.corpus.schemas import RetrievalIntent

        builder = (
            ScientificCorpusBuilder(connection=self.connection)
            if self.connection
            else ScientificCorpusBuilder()
        )
        parsed_intents = None
        if intents:
            try:
                parsed_intents = [RetrievalIntent(value) for value in intents]
            except ValueError as exc:
                raise RequirementResolutionError(
                    f"invalid retrieval intent: {exc}"
                ) from exc
        try:
            pack = builder.build(task_scope, intents=parsed_intents)
        except Exception as exc:
            raise RequirementResolutionError(f"corpus build failed: {exc}") from exc
        return pack.model_dump(mode="json")

    def analyze(
        self,
        corpus_pack: dict[str, Any],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        from ultrafast_knowledge.corpus.schemas import EvidenceCorpusPack
        from ultrafast_knowledge.scientific.validator import (
            DeterministicScientificValidator,
        )
        from ultrafast_knowledge.scientific_analysis.cache import SQLiteSourceAnalysisCache
        from ultrafast_knowledge.scientific_analysis.service import (
            PipelineConfig,
            ScientificKnowledgeService,
        )

        pack = EvidenceCorpusPack.model_validate(corpus_pack)
        cache = (
            SQLiteSourceAnalysisCache(self.connection)
            if self.connection
            else SQLiteSourceAnalysisCache()
        )
        service = ScientificKnowledgeService(
            self._client(),
            model=self.model,
            config=PipelineConfig(level="FAST", primary_count=8),
            cache=cache,
            validator=DeterministicScientificValidator(),
        )
        return service.analyze(pack, progress_callback=progress_callback)

    def validate(self, knowledge_pack: dict[str, Any]) -> dict[str, Any]:
        from ultrafast_knowledge.scientific.schemas import ScientificKnowledgePack
        from ultrafast_knowledge.scientific.validator import (
            DeterministicScientificValidator,
        )

        pack = ScientificKnowledgePack.model_validate(knowledge_pack)
        result = DeterministicScientificValidator().validate(pack)
        return result.model_dump(mode="json")


def intents_for_requirements(requirements: list[dict[str, Any]]) -> list[str]:
    intents: list[str] = []
    seen: set[str] = set()
    for requirement in requirements:
        req_type = str(requirement.get("type") or "")
        for intent in REQUIREMENT_TYPE_INTENTS.get(req_type, []):
            if intent not in seen:
                seen.add(intent)
                intents.append(intent)
    return intents


def candidate_to_evidence_ir(
    candidate: dict[str, Any],
    task_scope: dict[str, Any],
    corpus_pack_id: str,
) -> dict[str, Any] | None:
    """Map one validated scientific candidate to an EvidenceIR item."""
    ctype = str(candidate.get("type") or "")
    claim_type = CLAIM_TYPE_MAP.get(ctype)
    if claim_type is None:
        return None
    evidence_id = str(
        candidate.get("candidate_id")
        or candidate.get("item_id")
        or "evidence-unassigned"
    )
    claim: dict[str, Any] = {
        "lower": candidate.get("lower"),
        "upper": candidate.get("upper"),
        "unit": candidate.get("unit"),
        "parameter_semantics": "PROVISIONAL",
        "assumptions": list(candidate.get("assumptions") or []),
    }
    if claim_type == "mechanism_model":
        claim["model_family"] = str(
            candidate.get("name")
            or candidate.get("expression")
            or "UNKNOWN_MODEL_FAMILY"
        )
        claim["alternatives"] = list(candidate.get("alternatives") or [])
    if claim_type == "range_preference":
        claim["preference"] = (
            f"literature soft preference for {candidate.get('parameter') or 'parameter'}"
        )
        if str(candidate.get("parameter") or "") == "path_strategy" and candidate.get(
            "name"
        ):
            claim["path_families"] = [str(candidate["name"])]
    if candidate.get("expression"):
        claim["expression"] = str(candidate["expression"])
    source_refs = [
        {
            "type": "Paper",
            "id": str(ref.get("paper_id")),
            "page": ref.get("page"),
            "chunk_ids": list(ref.get("chunk_ids") or []),
        }
        for ref in (candidate.get("supporting_sources") or [])
        if ref.get("paper_id")
    ]
    provenance: list[dict[str, Any]] = [
        {"type": "EvidenceCorpusPack", "id": corpus_pack_id},
        {"type": "ScientificKnowledgeCandidate", "id": evidence_id},
        *source_refs,
    ]
    return {
        "evidence_id": evidence_id,
        "source_type": "literature",
        "claim_type": claim_type,
        "parameter": candidate.get("parameter"),
        "target": candidate.get("target"),
        "claim": claim,
        "conditions": dict(candidate.get("conditions") or {}),
        "scope": {
            "material": task_scope.get("material"),
            "laser_type": task_scope.get("laser_type"),
            "geometry_type": task_scope.get("geometry_type"),
            "equipment_id": task_scope.get("equipment_id"),
        },
        "review_status": VALIDATED_REVIEW_STATUS,
        "applicability_status": "UNKNOWN",
        "provenance": provenance,
        "source_refs": source_refs,
    }


def assess_evidence_applicability(
    evidence_ir: dict[str, Any],
    task_scope: dict[str, Any],
    *,
    claim_id: str,
) -> dict[str, Any]:
    """Per-dimension applicability report for one EvidenceIR item."""
    from ultrafast_e2p.application.applicability import assess_applicability
    from ultrafast_e2p.domain.evidence import EvidenceClaim

    claim = EvidenceClaim(
        claim_id=claim_id,
        claim_type=str(evidence_ir.get("claim_type") or "preferred_range"),
        parameter=evidence_ir.get("parameter"),
        target=evidence_ir.get("target"),
        value=dict(evidence_ir.get("claim") or {}),
        scope=dict(evidence_ir.get("scope") or {}),
        source={"paper": (evidence_ir.get("source_refs") or [{}])[0].get("id")},
        review_status="accepted",
    )
    task = {
        "material_id": task_scope.get("material"),
        "laser_type": task_scope.get("laser_type"),
        "process_type": task_scope.get("process_type"),
        "geometry_type": task_scope.get("geometry_type"),
        "equipment_id": task_scope.get("equipment_id"),
        "target_metric": task_scope.get("target"),
    }
    report = assess_applicability(task, claim)
    transfer = str(report.transfer_class).upper()
    return {
        "evidence_id": claim_id,
        "material_match": report.material_match,
        "laser_type_match": report.laser_type_match,
        "process_type_match": report.process_type_match,
        "geometry_match": report.geometry_match,
        "equipment_match": report.equipment_match,
        "target_metric_match": report.target_metric_match,
        "transfer_level": transfer,
    }


@dataclass
class ResolutionResult:
    query_plans: list[dict[str, Any]] = field(default_factory=list)
    corpus_pack: dict[str, Any] = field(default_factory=dict)
    knowledge_pack: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    evidence_ir: list[dict[str, Any]] = field(default_factory=list)
    applicability: list[dict[str, Any]] = field(default_factory=list)
    mapping_report: dict[str, Any] = field(default_factory=dict)
    # mid-chain artifacts (阶段一 · 手册 §7/§9): each is persisted as an
    # independent frozen artifact, never wrapped into one blob.
    candidate_ledger: dict[str, Any] = field(default_factory=dict)
    source_conditions: list[dict[str, Any]] = field(default_factory=list)
    reconstructibility_reports: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "requirement-resolution-v1",
            "query_plans": self.query_plans,
            "corpus_pack": self.corpus_pack,
            "knowledge_pack": self.knowledge_pack,
            "validation": self.validation,
            "evidence_ir": self.evidence_ir,
            "applicability": self.applicability,
            "mapping_report": self.mapping_report,
            "candidate_ledger": self.candidate_ledger,
            "source_conditions": self.source_conditions,
            "reconstructibility_reports": self.reconstructibility_reports,
        }


def resolve_requirement_chain(
    task_scope: dict[str, Any],
    requirements: list[dict[str, Any]],
    *,
    execution_mode: str = "DEMO_FIXTURE",
    llm_client: Any | None = None,
    model: str = "scientific-reading-v1",
    progress_callback: ProgressCallback | None = None,
) -> ResolutionResult:
    """KR -> QueryPlan -> Corpus -> LLM reading (cache-first) -> validate -> EvidenceIR.

    Raises RequirementResolutionError when the chain cannot produce evidence
    (fail closed); callers decide BLOCK vs PARTIAL.
    """
    if not requirements:
        return ResolutionResult()
    query_plans = [
        plan_retrieval(requirement, task_scope).model_dump(mode="json")
        for requirement in requirements
    ]
    adapter = ScientificSourceAdapter(
        llm_client=llm_client,
        model=model,
        execution_mode=execution_mode,
    )
    corpus_pack = adapter.build_corpus(
        task_scope, intents=intents_for_requirements(requirements)
    )
    knowledge_pack = adapter.analyze(corpus_pack, progress_callback=progress_callback)
    validation = adapter.validate(knowledge_pack)
    rejected = set(validation.get("rejected_candidates") or [])
    evidence_ir: list[dict[str, Any]] = []
    applicability: list[dict[str, Any]] = []
    for candidate in knowledge_pack.get("candidates") or []:
        if str(candidate.get("candidate_id")) in rejected:
            continue
        item = candidate_to_evidence_ir(
            candidate, task_scope, corpus_pack.get("corpus_pack_id") or ""
        )
        if item is None:
            continue
        report = assess_evidence_applicability(
            item, task_scope, claim_id=str(item["evidence_id"])
        )
        item["applicability_status"] = str(report.get("transfer_level") or "UNKNOWN")
        applicability.append(report)
        evidence_ir.append(item)
    mapping_report = (knowledge_pack.get("pipeline_report") or {}).get("mapping") or {}
    validated_candidates = [
        candidate
        for candidate in knowledge_pack.get("candidates") or []
        if str(candidate.get("candidate_id")) not in rejected
    ]
    # mid-chain: CandidateLedger -> Condition Compiler -> SourceCondition ->
    # Reconstructibility -> EvidenceIR projection (全部复用现有模块)
    from apps.topic2_backend.application.condition_chain import (
        build_candidate_ledger,
        build_reconstructibility_reports,
        compile_source_conditions,
        project_evidence_ir,
    )

    corpus_pack_id = corpus_pack.get("corpus_pack_id") or "corpus"
    ledger = build_candidate_ledger(
        validated_candidates, corpus_pack_id=corpus_pack_id, model=model
    )
    conditions = compile_source_conditions(
        validated_candidates, corpus_pack_id=corpus_pack_id
    )
    reports = build_reconstructibility_reports(conditions)
    evidence_ir = project_evidence_ir(
        evidence_ir,
        ledger=ledger,
        conditions=conditions,
        reports=reports,
    )
    return ResolutionResult(
        query_plans=query_plans,
        corpus_pack=corpus_pack,
        knowledge_pack=knowledge_pack,
        validation=validation,
        evidence_ir=evidence_ir,
        applicability=applicability,
        mapping_report=mapping_report,
        candidate_ledger=ledger.to_canonical_dict(),
        source_conditions=[condition.to_dict() for condition in conditions],
        reconstructibility_reports=reports,
    )
