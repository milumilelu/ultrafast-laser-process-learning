"""M7 unit tests: target input verification semantics + dependency rule."""

from __future__ import annotations

import pytest

from tests.test_t2_vertical_slice import CSV_PATH
from ultrafast_interaction.target import (
    InputVerificationStatus,
    TargetCoordinateEvaluator,
    TargetCoordinateStatus,
    build_target_condition_spec,
    readiness_projection,
)

pytestmark = pytest.mark.unit


def test_power_missing_blocks_pulse_energy() -> None:
    """Known target fact: the CSV has no power column."""
    spec = build_target_condition_spec(CSV_PATH, equipment_profile={})
    facts = {f.input_name: f for f in spec.input_facts}
    assert facts["laser_power_W"].verification_status == InputVerificationStatus.MISSING
    assert facts["frequency_Hz"].verification_status == InputVerificationStatus.MEASURED
    report = TargetCoordinateEvaluator().evaluate(spec)
    results = {c.coordinate: c for c in report.blocked_coordinates}
    assert results["pulse_energy"].status == TargetCoordinateStatus.BLOCKED
    assert "laser_power_W" in results["pulse_energy"].missing_inputs


def test_spot_unverified_never_available() -> None:
    """spot=5um is present in the profile but unverified -> UNVERIFIED, and a
    coordinate consuming it may never be AVAILABLE."""
    spec = build_target_condition_spec(
        CSV_PATH,
        equipment_profile={"spot_radius_um": (5.0, "um", False)},
    )
    facts = {f.input_name: f for f in spec.input_facts}
    assert facts["beam_radius_m"].verification_status == InputVerificationStatus.UNVERIFIED
    report = TargetCoordinateEvaluator().evaluate(spec)
    # pulse_overlap needs pulse_spacing (verified) + spot_diameter (derived from
    # beam_radius -> unverified propagation)
    overlap = next(
        c for c in report.unverified_assumption_coordinates if c.coordinate == "pulse_overlap"
    )
    assert overlap.status == TargetCoordinateStatus.AVAILABLE_WITH_UNVERIFIED_ASSUMPTION
    assert "beam_radius_m" in overlap.unverified_inputs or "spot_diameter_m" in overlap.unverified_inputs
    assert not any(
        c.coordinate == "pulse_overlap" and c.status == TargetCoordinateStatus.AVAILABLE
        for c in report.available_coordinates
    )


def test_verified_profile_enables_available() -> None:
    spec = build_target_condition_spec(
        CSV_PATH,
        equipment_profile={"spot_radius_um": (5.0, "um", True)},
    )
    report = TargetCoordinateEvaluator().evaluate(spec)
    # pulse_interval needs only frequency (verified) -> AVAILABLE
    interval = next(
        c for c in report.available_coordinates if c.coordinate == "pulse_interval"
    )
    assert interval.status == TargetCoordinateStatus.AVAILABLE
    assert interval.value is not None


def test_peak_fluence_blocked_by_power_even_with_verified_spot() -> None:
    spec = build_target_condition_spec(
        CSV_PATH,
        equipment_profile={"spot_radius_um": (5.0, "um", True)},
    )
    report = TargetCoordinateEvaluator().evaluate(spec)
    fluence = next(
        c for c in report.blocked_coordinates if c.coordinate == "peak_fluence"
    )
    assert fluence.status == TargetCoordinateStatus.BLOCKED
    assert "laser_power_W" in fluence.missing_inputs or "pulse_energy_J" in fluence.missing_inputs


def test_readiness_projection_counts() -> None:
    spec = build_target_condition_spec(
        CSV_PATH,
        equipment_profile={"spot_radius_um": (5.0, "um", False)},
    )
    report = TargetCoordinateEvaluator().evaluate(spec)
    projection = readiness_projection(report)
    assert projection.missing_input_count == 1  # laser_power_W
    assert projection.unverified_input_count == 1  # beam_radius_m
    assert projection.available_coordinate_count >= 1
    assert projection.unverified_assumption_coordinate_count >= 1
    assert projection.coordinate_status


def test_deterministic() -> None:
    spec = build_target_condition_spec(CSV_PATH, equipment_profile={"spot_radius_um": (5.0, "um", False)})
    first = readiness_projection(TargetCoordinateEvaluator().evaluate(spec)).to_dict()
    second = readiness_projection(TargetCoordinateEvaluator().evaluate(spec)).to_dict()
    assert first == second


def test_missing_spot_reports_dependency() -> None:
    spec = build_target_condition_spec(CSV_PATH, equipment_profile={})
    report = TargetCoordinateEvaluator().evaluate(spec)
    # beam_radius is a device property: absent -> BLOCKED for overlap family
    overlap = next(
        c for c in report.blocked_coordinates if c.coordinate == "pulse_overlap"
    )
    assert overlap.status == TargetCoordinateStatus.BLOCKED
