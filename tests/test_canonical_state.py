"""M8: Canonical Interaction State tests."""

from __future__ import annotations

import pytest

from tests.test_t2_vertical_slice import CSV_PATH
from ultrafast_interaction.canonical import (
    CoordinateAvailability,
    compare_canonical,
    source_state,
    target_state,
)
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


def _source_report(frequency_khz: float = 200.0, with_spot: bool = True):
    fields = [
        SourceField(
            parameter="frequency",
            values=(frequency_khz,),
            unit="kHz",
            field_status=FieldStatus.REPORTED_CLEAR,
        ),
        SourceField(
            parameter="scan_speed",
            values=(50.0,),
            unit="mm/s",
            field_status=FieldStatus.REPORTED_CLEAR,
        ),
        SourceField(
            parameter="pulse_energy",
            values=(2.0e-7,),
            unit="J",
            field_status=FieldStatus.REPORTED_CLEAR,
        ),
    ]
    if with_spot:
        fields.append(
            SourceField(
                parameter="spot_size",
                values=(15.0,),
                unit="um",
                field_status=FieldStatus.REPORTED_CLEAR,
            )
        )
    spec = SourceConditionSpec(
        condition_id="c1",
        paper_id="p1",
        document_version_id="d1",
        fields=tuple(fields),
    )
    return build_report(spec)


def test_tier_a_coordinates_available_both_sides() -> None:
    """pulse_interval/pulse_spacing comparable when target has frequency+speed."""
    source = source_state(_source_report())
    target_spec = build_target_condition_spec(
        CSV_PATH, equipment_profile={"spot_radius_um": (5.0, "um", True)}
    )
    target = target_state(
        TargetCoordinateEvaluator().evaluate(target_spec), condition_id="target"
    )
    comparison = compare_canonical(source, target)
    for coordinate in ("pulse_interval", "pulse_spacing"):
        assert comparison[coordinate]["comparability"] == "COMPARABLE"
        assert comparison[coordinate]["source"] == "AVAILABLE"
        assert comparison[coordinate]["target"] == "AVAILABLE"


def test_fluence_incomparable_when_power_missing() -> None:
    source = source_state(_source_report())
    target_spec = build_target_condition_spec(CSV_PATH, equipment_profile={"spot_radius_um": (5.0, "um", True)})
    target = target_state(TargetCoordinateEvaluator().evaluate(target_spec), condition_id="target")
    comparison = compare_canonical(source, target)
    # source has pulse_energy+spot -> peak_fluence AVAILABLE; target lacks power
    assert source.coordinates["peak_fluence"].availability == CoordinateAvailability.AVAILABLE
    assert comparison["peak_fluence"]["comparability"] == "INCOMPARABLE"
    assert comparison["peak_fluence"]["target"] != "AVAILABLE"


def test_unverified_target_never_comparable() -> None:
    """spot unverified on the target -> overlap family is UNVERIFIED, and CFA
    must not consume it."""
    source = source_state(_source_report())
    target_spec = build_target_condition_spec(
        CSV_PATH, equipment_profile={"spot_radius_um": (5.0, "um", False)}
    )
    target = target_state(TargetCoordinateEvaluator().evaluate(target_spec), condition_id="target")
    comparison = compare_canonical(source, target)
    for coordinate in ("pulse_overlap", "hatch_overlap", "pulses_per_spot"):
        entry = comparison[coordinate]
        assert entry["comparability"] == "UNVERIFIED", f"{coordinate}: {entry}"
        assert entry["reason"] == "unverified_on_one_side"


def test_unknown_is_not_mismatch() -> None:
    """A coordinate missing on one side is INCOMPARABLE with a reason, never a
    value-level mismatch."""
    source = source_state(_source_report())
    empty_target = build_target_condition_spec(CSV_PATH, equipment_profile={})
    target = target_state(
        TargetCoordinateEvaluator().evaluate(empty_target), condition_id="target"
    )
    comparison = compare_canonical(source, target)
    for name, entry in comparison.items():
        assert entry["comparability"] in ("COMPARABLE", "UNVERIFIED", "INCOMPARABLE")
        if entry["comparability"] == "INCOMPARABLE":
            assert entry["reason"]


def test_source_state_carries_provenance() -> None:
    state = source_state(_source_report())
    interval = state.coordinates["pulse_interval"]
    assert interval.formula_version
    assert interval.availability == CoordinateAvailability.AVAILABLE
    assert interval.value is not None


def test_canonical_dict_roundtrip() -> None:
    state = source_state(_source_report())
    payload = state.to_dict()
    assert payload["side"] == "source"
    assert "pulse_interval" in payload["coordinates"]
    assert payload["coordinates"]["pulse_interval"]["availability"] == "AVAILABLE"
