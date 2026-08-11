from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from ultrafast_evidence_prior.e2p import compile_beliefs, compile_priors
from ultrafast_evidence_prior.extraction import TypedEvidenceExtractor
from ultrafast_evidence_prior.knowledge_store import StructuredKnowledgeStoreV2
from ultrafast_evidence_prior.requirements import KnowledgeRequirementTemplateCompiler
from ultrafast_evidence_prior.schemas import (
    ConditionValidationState,
    EquipmentContext,
    EvidenceIRSetV2,
    EvidenceType,
    KnowledgeRequirementType,
    KnowledgeRequirementV1,
    ResolvedTaskV1,
    TargetMetric,
    TaskRequestV1,
    ValidationState,
)
from ultrafast_evidence_prior.service import EvidencePriorAnalysisService
from ultrafast_knowledge.evidence_pipeline.hybrid_index import HybridScientificIndex
from ultrafast_knowledge.evidence_pipeline.schemas import (
    EvidenceWindow,
    PaperCandidate,
    SemanticBlock,
    SemanticBlockType,
    StructuredScientificPaper,
)
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore
from ultrafast_memory.equipment.validation import validate_equipment_payload


class _DeepSeekShapeClient:
    model = "deepseek-v4-flash"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, **_kwargs):
        self.calls += 1
        requirement = messages[-1]["content"]
        if "MATERIAL_PROPERTY" not in requirement:
            return {"content": json.dumps({"status": "NOT_FOUND", "items": []})}
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
                                "statement": "The ablation threshold is 3.0 J/cm2.",
                            },
                            "conditions": {
                                "material": "diamond",
                                "wavelength_nm": 800,
                                "pulse_width_fs": 30,
                                "target_metric": "depth_um",
                            },
                            "evidence_quote": "ablation threshold of 3.0 J/cm2",
                            "source_block_refs": ["block-1"],
                            "extraction_confidence": 0.91,
                        }
                    ],
                }
            )
        }


class _NumericClaimClient:
    model = "numeric-claim-test"

    def __init__(
        self,
        *,
        value: float,
        unit: str,
        quote: str,
        conditions: dict[str, object] | None = None,
    ) -> None:
        self.value = value
        self.unit = unit
        self.quote = quote
        self.conditions = conditions or {}

    def chat(self, _messages, **_kwargs):
        return {
            "content": json.dumps(
                {
                    "status": "FOUND",
                    "items": [
                        {
                            "content": {
                                "evidence_type": "PARAMETER_VALUE",
                                "parameter": "reported_parameter",
                                "value": self.value,
                                "unit": self.unit,
                                "statement": "A numeric parameter was reported.",
                            },
                            "conditions": self.conditions,
                            "evidence_quote": self.quote,
                            "source_block_refs": ["block-numeric"],
                            "extraction_confidence": 0.9,
                        }
                    ],
                }
            )
        }


class _RetryClient:
    provider = "deepseek"
    model = "retry-test"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if len(self.calls) == 1:
            return {"content": ""}
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
                                "statement": "The ablation threshold is 3.0 J/cm2.",
                            },
                            "conditions": {"material": "diamond"},
                            "evidence_quote": "ablation threshold of 3.0 J/cm2",
                            "source_block_refs": ["block-1"],
                            "extraction_confidence": 0.9,
                        }
                    ],
                }
            )
        }


def _numeric_claim(
    *,
    source_text: str,
    value: float,
    unit: str,
    quote: str | None = None,
    conditions: dict[str, object] | None = None,
):
    requirement = KnowledgeRequirementV1(
        requirement_id="kreq-numeric",
        requirement_type=KnowledgeRequirementType.MATERIAL_PROPERTY,
        scientific_question="Which numeric parameter is directly reported?",
        target_metric=TargetMetric.DEPTH_UM,
        evidence_types=[EvidenceType.PARAMETER_VALUE],
        query_terms=["numeric parameter"],
    )
    candidate = PaperCandidate(
        paper_id="paper-numeric",
        document_version_id="doc-numeric-v1",
        score=1,
    )
    block = SemanticBlock(
        paper_id=candidate.paper_id,
        document_version_id=candidate.document_version_id,
        block_id="block-numeric",
        block_type=SemanticBlockType.RESULT_STATEMENT,
        page=1,
        pdf_page_index=0,
        text=source_text,
        retrieval_text=source_text,
    )
    window = EvidenceWindow(
        window_id="window-numeric",
        requirement_id=requirement.requirement_id,
        paper_id=candidate.paper_id,
        center_block_id=block.block_id,
        blocks=[block],
        score=1,
    )
    return TypedEvidenceExtractor(
        _NumericClaimClient(
            value=value,
            unit=unit,
            quote=quote or source_text,
            conditions=conditions,
        ),
        model="numeric-claim-test",
    ).extract(requirement, candidate, [window]).items[0]


def _task() -> ResolvedTaskV1:
    return ResolvedTaskV1(
        material="diamond",
        target_metric=TargetMetric.DEPTH_UM,
        equipment=EquipmentContext(
            equipment_profile_id="eq-1",
            equipment_revision_id="rev-1",
            profile_name="30 fs system",
            wavelength_nm=800,
            pulse_width_min_fs=25,
            pulse_width_max_fs=35,
            frequency_min_kHz=10,
            frequency_max_kHz=100,
            scan_speed_min_mm_s=1,
            scan_speed_max_mm_s=1000,
            rated_max_power_W=20,
            effective_max_power_W=16,
            effective_max_power_source="DERIVED_FROM_ATTENUATION",
        ),
    )


def _paper() -> StructuredScientificPaper:
    block = SemanticBlock(
        paper_id="paper-diamond",
        document_version_id="doc-diamond-v1",
        block_id="block-1",
        block_type=SemanticBlockType.RESULT_STATEMENT,
        page=3,
        pdf_page_index=2,
        text="For 30 fs pulses at 800 nm, the ablation threshold of 3.0 J/cm2 was measured.",
        retrieval_text=(
            "diamond ablation depth material removal ablation threshold 3.0 J/cm2 "
            "30 fs 800 nm"
        ),
    )
    return StructuredScientificPaper(
        paper_id="paper-diamond",
        document_version_id="doc-diamond-v1",
        title="Ultrashort laser ablation of diamond",
        abstract="Diamond ablation depth and threshold measurements.",
        retrieval_text="diamond laser ablation depth threshold ultrashort pulse",
        metadata={"material": "diamond", "laser_type": "fs"},
        blocks=[block],
    )


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    @contextmanager
    def factory():
        yield connection

    return connection, factory


def test_requirement_templates_are_target_specific_and_model_independent():
    requirements = KnowledgeRequirementTemplateCompiler().compile(_task())
    assert {item.requirement_type for item in requirements} == set(KnowledgeRequirementType)
    assert all("diamond" in item.scientific_question for item in requirements)
    assert all(item.target_metric == TargetMetric.DEPTH_UM for item in requirements)
    assert not any("dataset" in item.scientific_question.casefold() for item in requirements)


def test_typed_extraction_accepts_transferable_conditions_and_validates_quote():
    requirement = KnowledgeRequirementV1(
        requirement_id="kreq-1",
        requirement_type=KnowledgeRequirementType.MATERIAL_PROPERTY,
        scientific_question="What threshold is directly reported?",
        target_metric=TargetMetric.DEPTH_UM,
        evidence_types=[EvidenceType.PARAMETER_VALUE],
        query_terms=["ablation threshold"],
    )
    candidate = PaperCandidate(
        paper_id="paper-diamond",
        document_version_id="doc-diamond-v1",
        score=1,
    )
    block = _paper().blocks[0]
    window = EvidenceWindow(
        window_id="window-1",
        requirement_id="kreq-1",
        paper_id=candidate.paper_id,
        center_block_id=block.block_id,
        blocks=[block],
        score=1,
        paper_title="Ultrashort laser ablation of diamond",
        paper_metadata={"material": "diamond"},
    )
    outcome = TypedEvidenceExtractor(
        _DeepSeekShapeClient(), model="deepseek-v4-flash"
    ).extract(requirement, candidate, [window])
    assert outcome.items[0].validation_state == ValidationState.VALIDATED
    assert outcome.items[0].conditions["pulse_width_fs"] == 30
    assert outcome.items[0].evidence_quote in block.text


def test_typed_extraction_retries_invalid_json_and_counts_real_calls():
    requirement = KnowledgeRequirementTemplateCompiler().compile(_task())[1]
    candidate = PaperCandidate(
        paper_id="paper-diamond",
        document_version_id="doc-diamond-v1",
        score=1,
    )
    block = _paper().blocks[0]
    window = EvidenceWindow(
        window_id="window-retry",
        requirement_id=requirement.requirement_id,
        paper_id=candidate.paper_id,
        center_block_id=block.block_id,
        blocks=[block],
        score=1,
        paper_metadata={"material": "diamond"},
    )
    client = _RetryClient()

    outcome = TypedEvidenceExtractor(client, model=client.model).extract(
        requirement, candidate, [window]
    )

    assert outcome.status.value == "FOUND"
    assert outcome.llm_call_count == 2
    assert len(client.calls) == 2
    assert client.calls[0]["kwargs"]["max_tokens"] == 3500
    assert client.calls[0]["kwargs"]["thinking"] == {"type": "disabled"}
    assert "RETRY_CORRECTION" in client.calls[1]["messages"][-1]["content"]
    assert outcome.items[0].validation_state == ValidationState.VALIDATED


def test_verbatim_validation_accepts_pdf_line_break_hyphenation():
    evidence = _numeric_claim(
        source_text="The ablation thresh-\nold was 3.0 J/cm2.",
        value=3,
        unit="J/cm2",
        quote="The ablation threshold was 3.0 J/cm2.",
    )

    assert evidence.validation_state == ValidationState.VALIDATED


def test_numeric_unit_validation_rejects_word_letter_false_positive():
    evidence = _numeric_claim(
        source_text="The value was 20 percent.",
        value=20,
        unit="W",
    )

    assert evidence.validation_state == ValidationState.REJECTED
    assert evidence.validation_errors == [
        "numeric_unit_not_co_located_or_compatible:20.0:W"
    ]


def test_numeric_unit_validation_accepts_unicode_unit_spelling():
    evidence = _numeric_claim(
        source_text="The ablation threshold was 3.0 J/cm².",
        value=3,
        unit="J/cm2",
    )

    assert evidence.validation_state == ValidationState.VALIDATED
    assert evidence.validation_errors == []


def test_numeric_unit_validation_accepts_dimensionally_equivalent_value():
    evidence = _numeric_claim(
        source_text="The ablation threshold was 30000 J/m².",
        value=3,
        unit="J/cm2",
    )

    assert evidence.validation_state == ValidationState.VALIDATED
    assert evidence.validation_errors == []


def test_condition_provenance_rejects_non_unit_word_overlap():
    evidence = _numeric_claim(
        source_text="The reported share was 20 percent.",
        value=20,
        unit="percent",
        conditions={"average_power_W": 20},
    )

    assert evidence.validation_state == ValidationState.VALIDATED
    assert evidence.condition_provenance["average_power_W"].validation_state == (
        ConditionValidationState.UNVERIFIED
    )


def test_structured_knowledge_is_reused_without_governance_filter():
    connection, factory = _connection()
    try:
        store = ScientificIndexStore(factory)
        knowledge = StructuredKnowledgeStoreV2(store)
        requirement = KnowledgeRequirementTemplateCompiler().compile(_task())[1]
        candidate = PaperCandidate(
            paper_id="paper-diamond",
            document_version_id="doc-diamond-v1",
            score=1,
        )
        block = _paper().blocks[0]
        window = EvidenceWindow(
            window_id="window-1",
            requirement_id=requirement.requirement_id,
            paper_id=candidate.paper_id,
            center_block_id=block.block_id,
            blocks=[block],
            score=1,
            paper_title="Ultrashort laser ablation of diamond",
            paper_metadata={"material": "diamond"},
        )
        evidence = TypedEvidenceExtractor(
            _DeepSeekShapeClient(), model="deepseek-v4-flash"
        ).extract(requirement, candidate, [window]).items[0]
        knowledge.upsert(evidence, requirement_signature="signature-1")
        reused = knowledge.for_requirement_paper(
            requirement_signature="signature-1",
            paper_id=candidate.paper_id,
            document_version_id=candidate.document_version_id,
            extractor_model="deepseek-v4-flash",
        )
        assert reused[0].governance_status == "unreviewed"
        assert reused[0].extraction_route == "structured_knowledge"
    finally:
        connection.close()


def test_beliefs_and_priors_do_not_gate_unreviewed_evidence():
    requirement = KnowledgeRequirementTemplateCompiler().compile(_task())[1]
    candidate = PaperCandidate(
        paper_id="paper-diamond",
        document_version_id="doc-diamond-v1",
        score=1,
    )
    block = _paper().blocks[0]
    window = EvidenceWindow(
        window_id="window-1",
        requirement_id=requirement.requirement_id,
        paper_id=candidate.paper_id,
        center_block_id=block.block_id,
        blocks=[block],
        score=1,
        paper_title="Ultrashort laser ablation of diamond",
        paper_metadata={"material": "diamond"},
    )
    evidence = TypedEvidenceExtractor(
        _DeepSeekShapeClient(), model="deepseek-v4-flash"
    ).extract(requirement, candidate, [window]).items[0]
    evidence_set = EvidenceIRSetV2(evidence_set_id="set-1", items=[evidence])
    beliefs = compile_beliefs(_task(), evidence_set)
    priors = compile_priors(evidence_set, beliefs)
    assert len(beliefs.beliefs) == 1
    belief = beliefs.beliefs[0]
    assert belief.applicability_score > 0
    assert belief.evidence_quality > 0
    assert belief.recommended_prior_strength <= belief.applicability_score
    assert {facet.facet for facet in belief.facets} >= {
        "frequency_kHz",
        "scan_speed_mm_s",
    }
    assert "mechanical_validation" not in {facet.facet for facet in belief.facets}
    assert "extraction_confidence" not in {facet.facet for facet in belief.facets}
    assert len(priors.priors) == 1
    assert priors.priors[0].status == "PROVISIONAL"


def test_full_service_uses_dual_index_llm_knowledge_belief_and_prior(monkeypatch):
    connection, factory = _connection()
    try:
        store = ScientificIndexStore(factory)
        store.upsert_paper(_paper())
        index = HybridScientificIndex(store)
        index.rebuild("paper")
        index.rebuild("block")
        client = _DeepSeekShapeClient()
        monkeypatch.setattr(
            "ultrafast_evidence_prior.service.resolve_task", lambda _request: _task()
        )
        service = EvidencePriorAnalysisService(
            client,
            connection=factory,
            paper_top_k=1,
            windows_per_paper=1,
        )
        result = service.analyze(
            TaskRequestV1(
                material="diamond",
                equipment_profile_id="eq-1",
                equipment_revision_id="rev-1",
                target_metric="depth_um",
            )
        )
        assert result.evidence.llm_call_count == 7
        assert len(result.evidence.items) == 1
        assert len(result.beliefs.beliefs) == 1
        assert len(result.priors.priors) == 1
        assert any("治理提醒" in warning for warning in result.warnings)

        second = service.analyze(
            TaskRequestV1(
                material="diamond",
                equipment_profile_id="eq-1",
                equipment_revision_id="rev-1",
                target_metric="depth_um",
            )
        )
        assert second.evidence.knowledge_reused_count == 1
        assert second.evidence.llm_call_count == 6
    finally:
        connection.close()


def test_equipment_v1_requires_provenance_but_not_measured_power_bounds():
    validate_equipment_payload(
        laser_source={
            "pulse_width_min_fs": 30,
            "pulse_width_max_fs": 300,
            "rated_max_power_W": 20,
            "power_transmission_ratio": 0.8,
            "frequency_min_kHz": 10,
            "frequency_max_kHz": 1000,
        },
        motion_system={
            "scan_speed_min_mm_s": 1,
            "scan_speed_max_mm_s": 2000,
        },
        field_verification={
            "pulse_width_min_fs": "MANUFACTURER_SPEC",
            "pulse_width_max_fs": "MANUFACTURER_SPEC",
            "rated_max_power_W": "MANUFACTURER_SPEC",
            "power_transmission_ratio": "ESTIMATED",
            "frequency_min_kHz": "MANUFACTURER_SPEC",
            "frequency_max_kHz": "MANUFACTURER_SPEC",
            "scan_speed_min_mm_s": "MANUFACTURER_SPEC",
            "scan_speed_max_mm_s": "MANUFACTURER_SPEC",
        },
        require_active_minimum=True,
    )
