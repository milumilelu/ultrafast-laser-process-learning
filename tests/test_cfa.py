"""M9 unit tests: uncalibrated CFA facets, Unknown != Mismatch, no probabilities."""

from __future__ import annotations

import pytest

from tests.test_t2_vertical_slice import CSV_PATH
from ultrafast_cfa.cfa import (
    FacetStatus,
    assess_all,
    assess_interaction,
    assess_material,
    assess_reachability,
    assess_reconstructibility,
    assess_task,
)
from ultrafast_interaction.canonical import source_state, target_state
from ultrafast_interaction.target import (
    TargetCoordinateEvaluator,
    build_target_condition_spec,
)
from ultrafast_reconstructibility.models import (
    FieldStatus,
    SourceConditionSpec,
    SourceField,
)
from ultrafast_reconstructibility.report import build_report

pytestmark = pytest.mark.unit

TASK_SCOPE = {
    "material_id": "SiC",
    "laser_type": "fs",
    "process_type": "fs_laser_processing",
    "geometry_type": "rectangular_groove",
    "target_metric": "depth_um",
}


def _source_state():
    spec = SourceConditionSpec(
        condition_id="c1",
        paper_id="p1",
        document_version_id="d1",
        fields=(
            SourceField("frequency", (200.0,), "kHz", FieldStatus.REPORTED_CLEAR),
            SourceField("scan_speed", (50.0,), "mm/s", FieldStatus.REPORTED_CLEAR),
            SourceField("pulse_energy", (2.0e-7,), "J", FieldStatus.REPORTED_CLEAR),
            SourceField("spot_size", (15.0,), "um", FieldStatus.REPORTED_CLEAR),
        ),
    )
    return source_state(build_report(spec))


def _target_state(spot_verified: bool = True):
    spec = build_target_condition_spec(
        CSV_PATH, equipment_profile={"spot_radius_um": (5.0, "um", spot_verified)}
    )
    return target_state(TargetCoordinateEvaluator().evaluate(spec), condition_id="target")


def test_material_known_match() -> None:
    facet = assess_material(TASK_SCOPE, {"material_id": "SiC"})
    assert facet.status == FacetStatus.KNOWN


def test_material_mismatch_explicit() -> None:
    facet = assess_material(TASK_SCOPE, {"material_id": "CFRP"})
    assert facet.status == FacetStatus.MISMATCH


def test_material_unknown_is_not_mismatch() -> None:
    facet = assess_material(TASK_SCOPE, {})
    assert facet.status == FacetStatus.UNKNOWN
    assert facet.status != FacetStatus.MISMATCH


def test_task_facet_partial_on_unknown_dimension() -> None:
    facet = assess_task(TASK_SCOPE, {"laser_type": "fs", "process_type": "fs_laser_processing"})
    assert facet.status == FacetStatus.PARTIAL
    assert facet.matches["laser_type"] == "match"
    assert facet.matches["geometry_type"] == "unknown"


def test_interaction_facet_full_comparable() -> None:
    facet = assess_interaction(_source_state(), _target_state())
    comparable = {k: v for k, v in facet.coordinates.items() if v["comparability"] == "COMPARABLE"}
    assert facet.status == FacetStatus.PARTIAL  # power-blocked coords exist
    assert "pulse_interval" in comparable
    assert "pulse_spacing" in comparable
    # no probability anywhere
    payload = facet.to_dict()
    assert "confidence" not in str(payload)
    assert "probability" not in str(payload)


def test_interaction_unverified_coordinates_excluded_from_comparison() -> None:
    facet = assess_interaction(_source_state(), _target_state(spot_verified=False))
    for name, entry in facet.coordinates.items():
        if entry["comparability"] == "UNVERIFIED":
            assert entry["reason"] == "unverified_on_one_side"


def test_reconstructibility_and_reachability() -> None:
    source = _source_state()
    target = _target_state()
    rec = assess_reconstructibility(source)
    reach = assess_reachability(target)
    assert rec.reconstructible > 0
    assert rec.total > 0
    assert reach.reachable > 0
    assert rec.status in (FacetStatus.KNOWN, FacetStatus.PARTIAL)
    assert reach.status in (FacetStatus.KNOWN, FacetStatus.PARTIAL)


def test_assess_all_report_shape() -> None:
    report = assess_all(
        task_scope=TASK_SCOPE,
        evidence_scope={"material_id": "SiC", "laser_type": "fs"},
        source=_source_state(),
        target=_target_state(),
        evidence_claim_id="claim_1",
    )
    payload = report.to_dict()
    assert payload["version"] == "uncalibrated-cfa-v1"
    assert payload["calibration_status"] == "NOT_YET_CALIBRATED"
    assert len(payload["facets"]) == 5
    facet_names = {f["facet"] for f in payload["facets"]}
    assert facet_names == {
        "Material",
        "Task",
        "InteractionState",
        "Reconstructibility",
        "Reachability",
    }
    # hard rule: no probability claims in the entire report
    assert "probability" not in str(payload).lower()
    assert "confidence" not in str(payload).lower()
    assert "transfer" not in str(payload).lower()


def test_unknown_facet_warns_not_fails() -> None:
    report = assess_all(
        task_scope=TASK_SCOPE,
        evidence_scope={},  # no material/laser info at all
        source=_source_state(),
        target=_target_state(),
    )
    material = next(f for f in report.facets if f.to_dict()["facet"] == "Material")
    assert material.status == FacetStatus.UNKNOWN
    assert any("UNKNOWN (not a mismatch)" in w for w in report.warnings)
