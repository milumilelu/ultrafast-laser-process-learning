from __future__ import annotations

import json
from types import SimpleNamespace

from ultrafast_evidence_prior.acquisition import EvidenceAcquisitionSession
from ultrafast_evidence_prior.e2p import compile_beliefs
from ultrafast_evidence_prior.extraction import PaperExtractionOutcome, TypedEvidenceExtractor
from ultrafast_evidence_prior.requirements import KnowledgeRequirementTemplateCompiler
from ultrafast_evidence_prior.schemas import (
    ConditionProvenance,
    ConditionValidationState,
    EquipmentContext,
    EvidenceIRSetV2,
    EvidenceIRV2,
    EvidenceType,
    ExtractionStatus,
    ParameterValueContent,
    ResolvedTaskV1,
    TargetMetric,
    ValidationState,
)
from ultrafast_knowledge.evidence_pipeline.query import RequirementQueryCompiler
from ultrafast_knowledge.evidence_pipeline.schemas import (
    EvidenceWindow,
    PaperCandidate,
    SemanticBlock,
    SemanticBlockType,
)


def _task() -> ResolvedTaskV1:
    return ResolvedTaskV1(
        material="diamond",
        target_metric=TargetMetric.DEPTH_UM,
        equipment=EquipmentContext(
            equipment_profile_id="eq-1",
            equipment_revision_id="rev-1",
            profile_name="test",
            wavelength_nm=800,
            pulse_width_min_fs=30,
            pulse_width_max_fs=30,
            frequency_min_kHz=10,
            frequency_max_kHz=100,
        ),
    )


def _candidate(name: str) -> PaperCandidate:
    return PaperCandidate(
        paper_id=f"paper-{name}",
        document_version_id=f"doc-{name}",
        score=1.0,
    )


def _window(name: str, text: str) -> EvidenceWindow:
    block = SemanticBlock(
        paper_id=f"paper-{name}",
        document_version_id=f"doc-{name}",
        block_id=f"block-{name}",
        block_type=SemanticBlockType.RESULT_STATEMENT,
        page=1,
        pdf_page_index=0,
        text=text,
        retrieval_text=text,
        section_type="results",
    )
    return EvidenceWindow(
        window_id=f"window-{name}",
        requirement_id="requirement",
        paper_id=f"paper-{name}",
        center_block_id=block.block_id,
        blocks=[block],
        score=1.0,
        paper_title=f"Paper {name}",
        paper_metadata={"material": "diamond"},
    )


class _ConditionClient:
    model = "condition-test"

    def chat(self, _messages, **_kwargs):
        return {
            "content": json.dumps(
                {
                    "status": "FOUND",
                    "items": [
                        {
                            "content": {
                                "evidence_type": "PARAMETER_VALUE",
                                "parameter": "ablation_threshold",
                                "value": 3.0,
                                "unit": "J/cm2",
                                "statement": "The threshold is 3.0 J/cm2.",
                            },
                            "conditions": {
                                "material": "diamond",
                                "wavelength_nm": 800,
                                "pulse_width_fs": 30,
                                "frequency_kHz": 999,
                            },
                            "evidence_quote": "30 fs pulses at 800 nm have a threshold of 3.0 J/cm2",
                            "source_block_refs": ["block-a"],
                            "extraction_confidence": 0.9,
                        }
                    ],
                }
            )
        }


def test_unverified_conditions_cannot_influence_e2p() -> None:
    task = _task()
    requirement = KnowledgeRequirementTemplateCompiler().compile(task)[1]
    candidate = _candidate("a")
    window = _window(
        "a",
        "30 fs pulses at 800 nm have a threshold of 3.0 J/cm2.",
    ).model_copy(update={"requirement_id": requirement.requirement_id})
    outcome = TypedEvidenceExtractor(_ConditionClient(), model="condition-test").extract(
        requirement,
        candidate,
        [window],
    )
    evidence = outcome.items[0]

    assert evidence.condition_provenance["material"].source == "PAPER_METADATA"
    assert evidence.condition_provenance["wavelength_nm"].validation_state == (
        ConditionValidationState.VALIDATED
    )
    assert evidence.condition_provenance["pulse_width_fs"].validation_state == (
        ConditionValidationState.VALIDATED
    )
    assert evidence.condition_provenance["frequency_kHz"].validation_state == (
        ConditionValidationState.UNVERIFIED
    )
    assert "frequency_kHz" not in evidence.validated_conditions

    beliefs = compile_beliefs(
        task,
        EvidenceIRSetV2(evidence_set_id="set", items=[evidence]),
    )
    completeness = next(
        item for item in beliefs.beliefs[0].facets if item.facet == "condition_completeness"
    )
    assert "frequency" not in completeness.evidence_value


class _Store:
    @staticmethod
    def index_state(name: str):
        return {"revision": f"{name}-revision"}


class _Repository:
    def __init__(self, *, novel: bool = True) -> None:
        self.store = _Store()
        self.retriever = SimpleNamespace(query_compiler=RequirementQueryCompiler())
        self.novel = novel
        self.supplemental_queries: list[str] = []

    def retrieve(self, requirement, **_kwargs):
        candidate = _candidate("baseline")
        window = _window("baseline", "No relevant numeric evidence.").model_copy(
            update={"requirement_id": requirement.requirement_id}
        )
        key = f"{candidate.paper_id}::{candidate.document_version_id}"
        return [candidate], {key: [window]}

    def retrieve_query(self, requirement, query_text: str, **_kwargs):
        self.supplemental_queries.append(query_text)
        name = "novel" if self.novel else "baseline"
        candidate = _candidate(name)
        text = (
            "Diamond has an ablation threshold of 3.0 J/cm2."
            if self.novel
            else "No relevant numeric evidence."
        )
        window = _window(name, text).model_copy(
            update={"requirement_id": requirement.requirement_id}
        )
        key = f"{candidate.paper_id}::{candidate.document_version_id}"
        return [candidate], {key: [window]}


class _KnowledgeStore:
    def __init__(self) -> None:
        self.items: list[EvidenceIRV2] = []

    def for_requirement(self, **_kwargs):
        return []

    def upsert(self, evidence: EvidenceIRV2, **_kwargs):
        self.items.append(evidence)


class _GapExtractor:
    model = "gap-test"

    def extract(self, requirement, candidate, _windows):
        if candidate.paper_id != "paper-novel":
            return PaperExtractionOutcome(
                status=ExtractionStatus.NOT_FOUND,
                items=[],
                reason="not_found",
            )
        evidence = EvidenceIRV2(
            evidence_id="evidence-novel",
            requirement_id=requirement.requirement_id,
            paper_id=candidate.paper_id,
            document_version_id=candidate.document_version_id,
            content=ParameterValueContent(
                evidence_type=EvidenceType.PARAMETER_VALUE,
                parameter="ablation_threshold",
                value=3.0,
                unit="J/cm2",
                statement="Diamond has an ablation threshold of 3.0 J/cm2.",
            ),
            conditions={"material": "diamond"},
            condition_provenance={
                "material": ConditionProvenance(
                    source="BLOCK",
                    source_block_refs=["block-novel"],
                    validation_state=ConditionValidationState.VALIDATED,
                )
            },
            evidence_quote="Diamond has an ablation threshold of 3.0 J/cm2",
            source_block_refs=["block-novel"],
            source_pages=[1],
            extraction_confidence=0.9,
            validation_state=ValidationState.VALIDATED,
            extractor_model=self.model,
            prompt_version="test",
        )
        return PaperExtractionOutcome(status=ExtractionStatus.FOUND, items=[evidence])


def test_deterministic_gap_query_adds_novel_evidence_and_stops() -> None:
    task = _task()
    requirement = KnowledgeRequirementTemplateCompiler().compile(task)[1]
    repository = _Repository()
    session = EvidenceAcquisitionSession(
        repository=repository,
        knowledge_store=_KnowledgeStore(),
        extractor=_GapExtractor(),
        paper_top_k=1,
        windows_per_paper=1,
    )

    result = session.run(task, requirement)

    assert result.trace.stop_reason == "COVERAGE_SATISFIED"
    assert len(result.trace.rounds) == 2
    assert result.trace.rounds[1].planner_type == "DETERMINISTIC"
    assert result.trace.rounds[1].new_candidate_count == 1
    assert result.trace.rounds[1].coverage.operationally_sufficient
    assert result.items[0].evidence_id == "evidence-novel"
    assert repository.supplemental_queries
    assert all("diamond" in query.casefold() for query in repository.supplemental_queries)


def test_no_novel_hits_stops_without_reextracting_same_window() -> None:
    task = _task()
    requirement = KnowledgeRequirementTemplateCompiler().compile(task)[1]
    session = EvidenceAcquisitionSession(
        repository=_Repository(novel=False),
        knowledge_store=_KnowledgeStore(),
        extractor=_GapExtractor(),
        paper_top_k=1,
        windows_per_paper=1,
    )

    result = session.run(task, requirement)

    assert result.trace.stop_reason == "NO_NOVEL_HITS"
    assert result.llm_call_count == 1
    assert result.trace.rounds[1].extraction_calls == 0
