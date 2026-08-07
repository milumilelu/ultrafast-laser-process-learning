"""批次1 回归：Schema 冻结 + 确定性验证器（文档 F0/F3、§18、§51）。"""

from __future__ import annotations

import pytest

from ultrafast_knowledge.corpus.schemas import (
    CorpusSection,
    CorpusSource,
    EvidenceCorpusPack,
    RetrievalIntent,
    RetrievalTrace,
)
from ultrafast_knowledge.scientific.schemas import (
    CandidateType,
    ScientificKnowledgeCandidate,
    ScientificKnowledgePack,
    SemanticRole,
    SourceRef,
)
from ultrafast_knowledge.scientific.validator import DeterministicScientificValidator
from ultrafast_shared.units import convert, normalize_unit


def _pack() -> ScientificKnowledgePack:
    return ScientificKnowledgePack(
        knowledge_pack_id="KP-1",
        source_corpus_pack_id="CP-1",
        task_scope={"material": "SiC", "laser_type": "fs"},
    )


def test_corpus_pack_schema_round_trip() -> None:
    pack = EvidenceCorpusPack(
        corpus_pack_id="CP-1",
        task_context_id="TASK-001",
        task_context_version=3,
        task_scope={"material": "SiC", "laser_type": "fs"},
        retrieval_intents=[RetrievalIntent.PARAMETER_EFFECT, RetrievalIntent.FORMULA],
        sources=[
            CorpusSource(
                source_id="S1",
                source_type="literature",
                paper_id="P-018",
                sections=[
                    CorpusSection(
                        section_type="results",
                        page=7,
                        chunk_ids=["C-181", "C-182"],
                        text="depth decreases with scan speed",
                        retrieval_score=0.9,
                    )
                ],
            )
        ],
        retrieval_trace=RetrievalTrace(
            retrieval_run_id="R-1",
            intents=[RetrievalIntent.PARAMETER_EFFECT],
            raw_hit_count=10,
            filtered_hit_count=4,
            source_count=1,
        ),
    )
    data = pack.model_dump(mode="json")
    restored = EvidenceCorpusPack.model_validate(data)
    assert restored.corpus_pack_id == "CP-1"
    assert restored.source_count() == 1
    assert restored.section_count() == 1
    assert restored.chunk_count() == 2
    assert restored.retrieval_trace.raw_hit_count == 10


def test_all_retrieval_intents_are_defined() -> None:
    expected = {
        "parameter_effect", "parameter_condition", "material_property", "optical_property",
        "threshold", "formula", "mechanism", "interaction", "reported_optimum", "historical_analog",
    }
    assert {intent.value for intent in RetrievalIntent} == expected


def test_all_candidate_types_are_defined() -> None:
    expected = {
        "parameter_value", "parameter_range", "parameter_effect", "relative_importance",
        "interaction", "functional_shape", "material_property", "optical_property",
        "threshold", "formula", "mechanism", "reported_optimum", "experimental_condition",
        "historical_pattern", "historical_model",
    }
    assert {candidate.value for candidate in CandidateType} == expected


def test_parameter_effect_candidate_schema() -> None:
    candidate = ScientificKnowledgeCandidate(
        candidate_id="KC-001",
        type=CandidateType.PARAMETER_EFFECT,
        parameter="scan_speed_mm_s",
        target="depth_um",
        relation="negative",
        conditions={"material_id": "sic", "laser_type": "fs", "wavelength_nm": 1030},
        semantic_role=SemanticRole.OBSERVED_RELATION,
        supporting_sources=[SourceRef(paper_id="P-018", page=7, chunk_ids=["C-181"])],
    )
    assert candidate.type == CandidateType.PARAMETER_EFFECT
    assert candidate.relation == "negative"
    assert candidate.source_ids() == ["P-018"]


def test_formula_candidate_schema() -> None:
    candidate = ScientificKnowledgeCandidate(
        candidate_id="KC-011",
        type=CandidateType.FORMULA,
        name="gaussian_peak_fluence",
        expression="F0 = 2 * Ep / (pi * w0^2)",
        variables={"Ep": "pulse_energy_J", "w0": "beam_radius_1e2_m"},
        assumptions=["gaussian_spatial_profile", "w0_is_1e2_radius"],
        supporting_sources=[SourceRef(paper_id="P-031", page=4)],
    )
    assert candidate.expression.startswith("F0")


def test_threshold_candidate_schema() -> None:
    candidate = ScientificKnowledgeCandidate(
        candidate_id="KC-021",
        type=CandidateType.THRESHOLD,
        property="ablation_threshold",
        value=0.82,
        unit="J/cm2",
        conditions={
            "material_id": "sic",
            "wavelength_nm": 1030,
            "pulse_width_fs": 500,
            "pulse_number": 1,
        },
        supporting_sources=[SourceRef(paper_id="P-045", page=6)],
    )
    assert candidate.value == 0.82


def test_unit_normalization() -> None:
    # 文档 §51 陷阱：kHz vs MHz、fs vs ps、radius vs diameter
    assert convert(1.0, "kHz") == pytest.approx(1000.0)
    assert convert(1.0, "MHz") == pytest.approx(1_000_000.0)
    assert convert(500.0, "fs") == pytest.approx(500e-15)
    assert convert(1.0, "ps") == pytest.approx(1e-12)
    assert convert(50.0, "um") == pytest.approx(50e-6)
    assert convert(1.0, "J/cm2") == pytest.approx(1e4)
    assert convert(1.0, "mm/s") == pytest.approx(1e-3)
    assert normalize_unit("kW")[1] == pytest.approx(1e3)
    assert convert(1.0, "fortnights") is None


def test_validator_rejects_missing_source() -> None:
    pack = _pack()
    pack.candidates = [
        ScientificKnowledgeCandidate(
            candidate_id="KC-BAD",
            type=CandidateType.PARAMETER_VALUE,
            parameter="laser_power_W",
            value=20.0,
            unit="W",
        )
    ]
    result = DeterministicScientificValidator().validate(pack)
    assert result.rejected_candidates == ["KC-BAD"]
    assert any(issue.code == "missing_source" for issue in result.issues)


def test_validator_rejects_unrecognized_unit() -> None:
    pack = _pack()
    pack.candidates = [
        ScientificKnowledgeCandidate(
            candidate_id="KC-U",
            type=CandidateType.PARAMETER_VALUE,
            parameter="frequency_kHz",
            value=100.0,
            unit="parsecs",
            supporting_sources=[SourceRef(paper_id="P-045", page=6)],
        )
    ]
    result = DeterministicScientificValidator().validate(pack)
    assert result.rejected_candidates == ["KC-U"]
    assert any(issue.code == "unrecognized_unit" for issue in result.issues)


def test_validator_flags_unit_trap() -> None:
    pack = _pack()
    pack.candidates = [
        ScientificKnowledgeCandidate(
            candidate_id="KC-T",
            type=CandidateType.PARAMETER_VALUE,
            parameter="pulse_width_fs",
            value=500.0,
            unit="fs",
            extraction_notes=["pulse width 500 fs, alternative 500 ps reported"],
            supporting_sources=[SourceRef(paper_id="P-045", page=6)],
        )
    ]
    result = DeterministicScientificValidator().validate(pack)
    assert result.validated_candidates == ["KC-T"]
    assert any(issue.code == "unit_trap_confusion" for issue in result.issues)


def test_validator_rejects_missing_required_field() -> None:
    pack = _pack()
    pack.candidates = [
        ScientificKnowledgeCandidate(
            candidate_id="KC-R",
            type=CandidateType.PARAMETER_RANGE,
            parameter="scan_speed_mm_s",
            lower=1.0,
            supporting_sources=[SourceRef(paper_id="P-045", page=6)],
        )
    ]
    result = DeterministicScientificValidator().validate(pack)
    assert result.rejected_candidates == ["KC-R"]
    assert any(issue.code == "missing_field_upper" for issue in result.issues)


def test_validator_checks_source_existence() -> None:
    pack = _pack()
    pack.candidates = [
        ScientificKnowledgeCandidate(
            candidate_id="KC-S",
            type=CandidateType.PARAMETER_VALUE,
            parameter="laser_power_W",
            value=20.0,
            unit="W",
            supporting_sources=[SourceRef(paper_id="P-GHOST")],
        )
    ]
    result = DeterministicScientificValidator().validate(pack,)
    # 未注入 source_checker 时只校验必填；注入后校验存在性
    assert result.validated_candidates == ["KC-S"]


def test_feature_spec_and_e2p_decision_schema() -> None:
    from ultrafast_e2p.domain.specs import ConstraintSpec, E2PDecision, FeatureSpec, ModelPolicySpec

    spec = FeatureSpec(
        feature_id="FS-1",
        feature_name="normalized_fluence",
        formula_id="norm-fluence-v1",
        required_inputs=["peak_fluence"],
        required_properties=["ablation_threshold"],
        assumptions=["governed_threshold_available"],
        source_knowledge_ids=["KC-021"],
    )
    decision = E2PDecision(
        e2p_run_id="E2P-1",
        task_scope={"material": "SiC"},
        feature_specs=[spec],
        model_policy=ModelPolicySpec(candidate_models=["GPR"]),
        constraint_specs=[
            ConstraintSpec(
                constraint_id="C1",
                constraint_type="pulse_energy_max",
                parameters={"pulse_energy_J": 1e-4},
                hard=True,
            )
        ],
        knowledge_used=["KC-021"],
        knowledge_rejected=["KC-022"],
        reason_codes=["missing_spot_radius"],
    )
    data = decision.model_dump(mode="json")
    assert data["feature_specs"][0]["feature_name"] == "normalized_fluence"
    assert data["constraint_specs"][0]["hard"] is True
    assert data["reason_codes"] == ["missing_spot_radius"]
