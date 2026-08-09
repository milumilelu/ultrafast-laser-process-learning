"""M2: ScientificNeedSet four-way classification.

RESOURCE_INPUT never becomes a knowledge requirement; CALIBRATION_OBSERVATION
and TARGET_DATA are honest non-literature needs; SCIENTIFIC_KNOWLEDGE stays
the only literature-routed class.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from packages.scientific_computation.capability import ScientificCapabilityAnalyzer
from packages.scientific_computation.needs import (
    ScientificNeedSet,
    ScientificNeedType,
    classify_requirement,
    compile_scientific_needs,
)

ROW = {
    "pulse_width_ps": 0.5,
    "frequency_kHz": 100.0,
    "scan_speed_mm_s": 50.0,
    "hatch_spacing_um": 5.0,
    "passes": 2,
    "depth_um": 4.0,
}


def _capability(machine_profile: dict | None = None) -> object:
    return ScientificCapabilityAnalyzer().analyze(
        task={
            "task_context_id": "T",
            "material": "SiC",
            "geometry_type": "rectangular_groove",
            "equipment_id": "EQ",
        },
        data_rows=[ROW],
        machine_profile=machine_profile,
    )


def test_missing_power_is_resource_need_not_knowledge() -> None:
    capability = _capability()
    needs = compile_scientific_needs(
        capability,
        machine_snapshot={
            "missing_required": ["actual_power_W", "beam_radius_um"],
            "fields": {},
        },
        data_rows=[ROW],
    )
    resources = needs.needs_of(ScientificNeedType.RESOURCE_INPUT)
    assert {need.target for need in resources} >= {
        "actual_power_W",
        "beam_radius_um",
    }
    assert all(
        str(need.resolution_target) == "EQUIPMENT_MANAGER" for need in resources
    )
    knowledge = needs.needs_of(ScientificNeedType.SCIENTIFIC_KNOWLEDGE)
    assert {need.target for need in knowledge} >= {"F_th_eff", "incubation_law", "path_strategy"}
    assert all(
        str(need.resolution_target) == "LITERATURE_RETRIEVAL" for need in knowledge
    )
    # resource needs never appear as literature requirements
    assert all(
        classify_requirement(req) != ScientificNeedType.RESOURCE_INPUT
        or req.type == "PHYSICS_DEPENDENCY"
        for req in capability.recommended_requirements
    )


def test_calibration_observation_and_target_data() -> None:
    capability = _capability(machine_profile={"actual_power_W": 10.0, "beam_radius_um": 8.0})
    needs = compile_scientific_needs(capability, data_rows=[])
    obs = needs.needs_of(ScientificNeedType.CALIBRATION_OBSERVATION)
    assert obs, "identifiability abstentions must surface as observation needs"
    assert all(
        str(need.resolution_target) == "EXPERIMENT_OBSERVATION" for need in obs
    )
    target = needs.needs_of(ScientificNeedType.TARGET_DATA)
    assert len(target) == 1
    assert str(target[0].resolution_target) == "DATASET"

    # with data rows, no TARGET_DATA need
    with_data = compile_scientific_needs(capability, data_rows=[ROW])
    assert not with_data.needs_of(ScientificNeedType.TARGET_DATA)


def test_need_set_roundtrip_and_required_fields() -> None:
    capability = _capability()
    needs = compile_scientific_needs(capability, data_rows=[ROW])
    assert isinstance(needs, ScientificNeedSet)
    restored = ScientificNeedSet.model_validate(needs.model_dump(mode="json"))
    assert restored == needs
    for need in needs.needs:
        assert need.need_id
        assert need.question
        assert need.required_for
        assert need.trigger_reasons
        assert need.priority in {"high", "medium", "low"}
