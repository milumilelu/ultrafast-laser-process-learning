"""批次4 回归：Physics Feature Engine + E2P Knowledge Router（文档 F4/F5、§23-29、§41）。"""

from __future__ import annotations

import pytest

from ultrafast_knowledge.scientific.knowledge_router import E2PKnowledgeRouter
from ultrafast_knowledge.scientific.schemas import (
    CandidateType,
    ScientificKnowledgeCandidate,
    SemanticRole,
    SourceRef,
)
from ultrafast_physics.engine import PhysicsFeatureEngine
from ultrafast_physics.registry import available_formulas, get_formula


def _candidate(**kwargs) -> ScientificKnowledgeCandidate:
    defaults = {
        "candidate_id": "KC-X",
        "supporting_sources": [SourceRef(paper_id="P-1", page=1)],
        "semantic_role": SemanticRole.REPORTED_OPTIMUM,
    }
    defaults.update(kwargs)
    return ScientificKnowledgeCandidate(**defaults)


def test_all_documented_formulas_registered() -> None:
    """文档 §26：第一批 11 个特征全部注册。"""
    expected = {
        "pulse_energy", "pulse_interval", "pulse_spacing", "line_energy", "areal_energy",
        "peak_fluence", "pulse_overlap", "hatch_overlap", "pulses_per_spot",
        "normalized_fluence", "thermal_accumulation_number",
    }
    assert expected <= set(available_formulas())


def test_pulse_energy_from_power_and_frequency() -> None:
    engine = PhysicsFeatureEngine()
    result = engine.compute("pulse_energy", {"laser_power_W": (20.0, "W"), "frequency_Hz": (100e3, "Hz")})
    assert result.available
    assert result.value == pytest.approx(20.0 / 100e3)
    assert result.unit == "J"


def test_peak_fluence_requires_spot_radius() -> None:
    """文档 §29：禁止静默假设 spot radius → unavailable。"""
    engine = PhysicsFeatureEngine()
    result = engine.compute("peak_fluence", {"pulse_energy_J": (1e-3, "J")})
    assert result.available is False
    assert "beam_radius_m" in result.missing_inputs


def test_peak_fluence_formula() -> None:
    engine = PhysicsFeatureEngine()
    result = engine.compute(
        "peak_fluence",
        {"pulse_energy_J": (1e-3, "J"), "beam_radius_m": (10e-6, "m")},
    )
    assert result.available
    assert result.value == pytest.approx(2 * 1e-3 / (3.141592653589793 * (10e-6) ** 2))


def test_pulse_overlap() -> None:
    engine = PhysicsFeatureEngine()
    result = engine.compute(
        "pulse_overlap",
        {"pulse_spacing_m": (5e-6, "m"), "spot_diameter_m": (20e-6, "m")},
    )
    assert result.available
    assert result.value == pytest.approx(1 - 5e-6 / 20e-6)


def test_thermal_accumulation_marked_engineering_descriptor() -> None:
    engine = PhysicsFeatureEngine()
    result = engine.compute(
        "thermal_accumulation_number",
        {
            "frequency_Hz": (100e3, "Hz"),
            "beam_radius_m": (10e-6, "m"),
            "thermal_diffusivity_m2_s": (1e-6, "m2/s"),
        },
    )
    assert result.available
    assert result.approximate is False
    formula = get_formula("thermal_accumulation_number")
    assert any("engineering_descriptor" in a for a in formula.assumptions)


def test_unit_normalization_in_engine() -> None:
    """kHz→Hz、μm→m、J/cm2→J/m2 统一换算后计算。"""
    engine = PhysicsFeatureEngine()
    result = engine.compute(
        "peak_fluence",
        {"pulse_energy_J": (0.1, "mJ"), "beam_radius_m": (10, "um")},
    )
    assert result.available
    assert result.value == pytest.approx(2 * 1e-4 / (3.141592653589793 * (10e-6) ** 2))


def test_formula_router_builds_feature_specs() -> None:
    router = E2PKnowledgeRouter(approval_checker=lambda _candidate_id: True)
    decision = router.route(
        [
            _candidate(
                candidate_id="KC-F1",
                type=CandidateType.FORMULA,
                name="gaussian_peak_fluence",
                expression="F0 = 2 * Ep / (pi * w0^2)",
                assumptions=["gaussian_spatial_profile", "w0_is_1e2_radius"],
            ),
            _candidate(
                candidate_id="KC-T1",
                type=CandidateType.THRESHOLD,
                property="ablation_threshold",
                value=0.82,
                unit="J/cm2",
                conditions={"material_id": "sic", "wavelength_nm": 1030},
            ),
        ],
        {"material": "SiC", "laser_type": "fs"},
    )
    assert decision.e2p_run_id
    feature_ids = {spec.feature_id for spec in decision.feature_specs}
    assert "peak_fluence" in feature_ids
    assert "normalized_fluence" in feature_ids
    normalized = next(spec for spec in decision.feature_specs if spec.feature_id == "normalized_fluence")
    assert "ablation_threshold_J_m2" in normalized.required_properties
    assert "KC-T1" in normalized.source_knowledge_ids
    # 单位换算：0.82 J/cm2 → J/m2 数值层面由 physics engine 消费；FeatureSpec 只携带属性名


def test_router_reported_optimum_becomes_governed_prior() -> None:
    router = E2PKnowledgeRouter(approval_checker=lambda _candidate_id: True)
    decision = router.route(
        [
            _candidate(
                candidate_id="KC-O1",
                type=CandidateType.REPORTED_OPTIMUM,
                parameter="frequency_kHz",
                lower=90.0,
                upper=110.0,
                unit="kHz",
            )
        ],
        {"material": "SiC", "laser_type": "fs", "objective_metric": "depth_um"},
    )
    assert len(decision.prior_specs) == 1
    artifact = decision.prior_specs[0]
    assert artifact["approval_ids"] == ["KC-O1"]
    assert artifact["content_hash"]
    assert artifact["verification"] == "repository_verified"
    preference = artifact["prior_spec"]["range_preferences"][0]
    assert preference["parameter"] == "frequency_kHz"
    assert preference["semantic_role"] == "reported_optimum"
    assert artifact["prior_spec"]["prior_spec_version"]


def test_router_rejects_unroutable_and_keeps_reasons() -> None:
    router = E2PKnowledgeRouter(approval_checker=lambda _candidate_id: True)
    decision = router.route(
        [
            _candidate(
                candidate_id="KC-V1",
                type=CandidateType.PARAMETER_VALUE,
                parameter="laser_power_W",
                value=20.0,
                unit="W",
            )
        ],
        {"material": "SiC"},
    )
    assert decision.knowledge_rejected == ["KC-V1"]
    assert any("parameter_value" in reason for reason in decision.reason_codes)
    assert decision.prior_specs == []


def test_router_fails_closed_without_approval_checker() -> None:
    decision = E2PKnowledgeRouter().route(
        [
            _candidate(
                candidate_id="KC-NO-GATE",
                type=CandidateType.REPORTED_OPTIMUM,
                parameter="frequency_kHz",
                lower=90.0,
                upper=110.0,
                unit="kHz",
            )
        ],
        {"material": "SiC", "laser_type": "fs"},
    )
    assert decision.knowledge_used == []
    assert decision.knowledge_rejected == ["KC-NO-GATE"]
    assert decision.prior_specs == []
    assert "approval_checker_unavailable" in decision.reason_codes[0]
