"""M6 unit tests: five-way unknown separation + Formula-Registry-driven evaluation.

V2-1/V2-2 regression coverage:
  - RECONSTRUCTIBLE implies the dependency chain is genuinely satisfied
    (global invariant over every registered coordinate, V2-G2)
  - RANGE/LIST values never degrade to point values and never claim
    COMPARABLE-positive evidence (V2-G3/V2-G4)
"""

from __future__ import annotations

import pytest

from ultrafast_reconstructibility.coordinates import (
    CONDITION_TO_INPUT,
    COORDINATE_ALIASES,
    COORDINATES,
    CoordinateEvaluator,
)
from ultrafast_reconstructibility.models import (
    CoordinateStatus,
    CoverageStatus,
    FieldStatus,
    SourceConditionSpec,
    SourceField,
    ValueShape,
)
from ultrafast_reconstructibility.report import build_readiness, build_report

pytestmark = pytest.mark.unit


def _spec(*fields: SourceField, coverage: CoverageStatus = CoverageStatus.TEXT_COVERAGE_OK) -> SourceConditionSpec:
    return SourceConditionSpec(
        condition_id="c1",
        paper_id="p1",
        document_version_id="d1",
        role="PROCESSING",
        coverage_status=coverage,
        fields=tuple(fields),
    )


def _field(param: str, value: float, unit: str, status: FieldStatus = FieldStatus.REPORTED_CLEAR) -> SourceField:
    return SourceField(parameter=param, values=(value,), unit=unit, field_status=status)


def _range_field(param: str, values: tuple[float, ...], unit: str) -> SourceField:
    return SourceField(
        parameter=param,
        values=values,
        unit=unit,
        field_status=FieldStatus.REPORTED_CLEAR,
        value_shape=ValueShape.RANGE,
    )


def test_pulse_interval_reconstructible_from_frequency() -> None:
    spec = _spec(_field("frequency", 200.0, "kHz"))
    results = {r.coordinate: r for r in CoordinateEvaluator().evaluate(spec)}
    interval = results["pulse_interval"]
    assert interval.status == CoordinateStatus.RECONSTRUCTIBLE
    assert interval.value == pytest.approx(1 / 200_000.0)  # 1/200 kHz in SI


def test_peak_fluence_blocked_by_dependency_missing() -> None:
    """frequency only: peak_fluence needs pulse_energy + beam_radius (device)."""
    spec = _spec(_field("frequency", 200.0, "kHz"))
    results = {r.coordinate: r for r in CoordinateEvaluator().evaluate(spec)}
    fluence = results["peak_fluence"]
    assert fluence.status == CoordinateStatus.DEPENDENCY_MISSING
    assert "beam_radius_m" in fluence.missing_inputs


def test_peak_fluence_reconstructible_from_energy_and_spot() -> None:
    spec = _spec(
        _field("pulse_energy", 2.0e-7, "J"),
        _field("spot_size", 15.0, "um"),
    )
    results = {r.coordinate: r for r in CoordinateEvaluator().evaluate(spec)}
    fluence = results["peak_fluence"]
    assert fluence.status == CoordinateStatus.RECONSTRUCTIBLE
    assert fluence.formula_version  # from the registry, not hand-written


def test_ambiguous_field_blocks_coordinate() -> None:
    spec = _spec(
        _field("frequency", 200.0, "kHz", status=FieldStatus.CONFLICT_PRESERVED),
    )
    results = {r.coordinate: r for r in CoordinateEvaluator().evaluate(spec)}
    interval = results["pulse_interval"]
    assert interval.status == CoordinateStatus.AMBIGUOUS
    assert interval.blocking_status == "REPORTED_AMBIGUOUS"


def test_missing_field_is_not_reported_not_covered() -> None:
    """G1: NOT_REPORTED (coverage OK) vs TEXT_COVERAGE_BLOCKED (coverage bad)."""
    ok = _spec(_field("frequency", 200.0, "kHz"))
    bad = _spec(_field("frequency", 200.0, "kHz"), coverage=CoverageStatus.TEXT_COVERAGE_PARTIAL)
    evaluator = CoordinateEvaluator()
    r_ok = {r.coordinate: r for r in evaluator.evaluate(ok)}["pulse_spacing"]
    r_bad = {r.coordinate: r for r in evaluator.evaluate(bad)}["pulse_spacing"]
    assert r_ok.status == CoordinateStatus.NOT_REPORTED
    assert r_bad.status == CoordinateStatus.TEXT_COVERAGE_BLOCKED


def test_report_classification_and_status() -> None:
    spec = _spec(
        _field("frequency", 200.0, "kHz"),
        _field("pulse_width", 300.0, "fs"),
    )
    report = build_report(spec)
    assert report.reported_fields == ["frequency", "pulse_width"]
    assert report.missing_fields
    assert report.reconstructibility_status.value in ("PARTIAL", "BLOCKED")
    assert report.blocking_dependencies


def test_ambiguous_warning() -> None:
    spec = _spec(_field("frequency", 200.0, "kHz", status=FieldStatus.LINKAGE_AMBIGUOUS))
    report = build_report(spec)
    assert report.ambiguous_fields == ["frequency"]
    assert any("ambiguous" in w for w in report.warnings)


def test_readiness_aggregate() -> None:
    reports = [
        build_report(_spec(_field("frequency", 200.0, "kHz"))),
        build_report(_spec(_field("pulse_energy", 2.0e-7, "J"), _field("spot_size", 15.0, "um"))),
    ]
    readiness = build_readiness(reports)
    assert readiness.total_conditions == 2
    assert readiness.computable_coordinate_count >= 2
    assert readiness.reported_field_count == 3
    assert readiness.coordinate_status


def test_deterministic_g6() -> None:
    spec = _spec(_field("frequency", 200.0, "kHz"), _field("pulse_width", 300.0, "fs"))
    first = [r.to_dict() for r in CoordinateEvaluator().evaluate(spec)]
    second = [r.to_dict() for r in CoordinateEvaluator().evaluate(spec)]
    assert first == second


def test_no_hand_written_formulas_g2() -> None:
    """P1: evaluator must call the registry - verify coordinates come from FORMULAS."""
    import inspect

    from ultrafast_reconstructibility import coordinates as mod

    source = inspect.getsource(mod)
    assert "get_formula" in source
    assert "engine.compute" in source


# ---------------------------------------------------------------- V2-1 / V2-2


def _independent_reconstructible_truth(
    evaluator: CoordinateEvaluator,
    coordinate: str,
    inputs: dict[str, tuple[float, str]],
) -> bool:
    """Independent truth for the V2-G2 invariant.

    RECONSTRUCTIBLE iff (a) the coordinate is directly reported as a point
    value, or (b) the registry formula chain genuinely computes it
    (compute_chain succeeded with no missing inputs). Mirrors the evaluator's
    documented spot_diameter -> beam_radius derivation only.
    """
    if coordinate in inputs:
        return True
    formula_id = COORDINATE_ALIASES.get(coordinate, coordinate)
    chain_inputs = dict(inputs)
    if "spot_diameter_m" in chain_inputs and "beam_radius_m" not in chain_inputs:
        d, unit = chain_inputs["spot_diameter_m"]
        chain_inputs["beam_radius_m"] = (d / 2.0, unit)
    try:
        result = evaluator.engine.compute_chain(formula_id, chain_inputs)
    except KeyError:
        return False
    return result.available and not result.missing_inputs


@pytest.mark.parametrize("coordinate", COORDINATES)
def test_v2g2_reconstructible_implies_dependency_satisfied(coordinate: str) -> None:
    """V2-G2: for every registered coordinate, RECONSTRUCTIBLE requires the
    dependency chain to be genuinely satisfied - no coordinate-specific
    bypass may ever claim availability without inputs."""
    evaluator = CoordinateEvaluator()
    # battery: empty spec, partial inputs, every single input, full input set
    param_to_input = {p: n for p, n in CONDITION_TO_INPUT.items()}
    specs: list[SourceConditionSpec] = [_spec()]
    for param, value, unit in (
        ("frequency", 200.0, "kHz"),
        ("pulse_energy", 2.0e-7, "J"),
        ("spot_size", 15.0, "um"),
        ("average_power", 4.0, "W"),
        ("scan_speed", 0.5, "mm/s"),
        ("hatch_spacing", 50.0, "um"),
        ("passes", 3.0, ""),
        ("fluence", 18.8, "J/cm2"),
        ("accumulated_dose", 120.0, "J/cm2"),
    ):
        specs.append(_spec(_field(param, value, unit)))
    full = _spec(
        _field("frequency", 200.0, "kHz"),
        _field("pulse_energy", 2.0e-7, "J"),
        _field("spot_size", 15.0, "um"),
        _field("average_power", 4.0, "W"),
        _field("scan_speed", 0.5, "mm/s"),
        _field("hatch_spacing", 50.0, "um"),
        _field("passes", 3.0, ""),
    )
    specs.append(full)
    for spec in specs:
        result = next(
            r for r in evaluator.evaluate(spec) if r.coordinate == coordinate
        )
        inputs: dict[str, tuple[float, str]] = {}
        for field in spec.fields:
            input_name = param_to_input.get(field.parameter)
            if input_name and field.field_status == FieldStatus.REPORTED_CLEAR:
                inputs[input_name] = (field.values[0], field.unit)
        if result.status == CoordinateStatus.RECONSTRUCTIBLE:
            assert _independent_reconstructible_truth(
                evaluator, coordinate, inputs
            ), f"{coordinate}: RECONSTRUCTIBLE without satisfied dependency chain"


def test_v2g2_jm2_coordinates_no_longer_unconditionally_available() -> None:
    """V2-1: J_m2 aliases follow the dependency chain; empty spec -> five-way
    classification (the v1.1 bypass made them AVAILABLE with value=None)."""
    results = {r.coordinate: r for r in CoordinateEvaluator().evaluate(_spec())}
    assert results["peak_fluence_J_m2"].status == CoordinateStatus.DEPENDENCY_MISSING
    assert results["peak_fluence_J_m2"].value is None
    assert results["areal_energy_J_m2"].status == CoordinateStatus.NOT_REPORTED
    assert results["areal_energy_J_m2"].value is None


def test_v2g2_jm2_alias_reconstructible_via_formula_chain() -> None:
    """V2-1: peak_fluence_J_m2 is available when pulse_energy + spot are
    reported (registry formula path, not a bypass)."""
    spec = _spec(
        _field("pulse_energy", 2.0e-7, "J"),
        _field("spot_size", 15.0, "um"),
    )
    results = {r.coordinate: r for r in CoordinateEvaluator().evaluate(spec)}
    fluence = results["peak_fluence_J_m2"]
    assert fluence.status == CoordinateStatus.RECONSTRUCTIBLE
    assert fluence.value is not None
    assert fluence.formula_version


def test_v2g2_jm2_direct_report_is_reconstructible() -> None:
    """V2-1: a directly reported point fluence is a genuine observation."""
    spec = _spec(_field("fluence", 18.8, "J/cm2"))
    results = {r.coordinate: r for r in CoordinateEvaluator().evaluate(spec)}
    assert results["peak_fluence_J_m2"].status == CoordinateStatus.RECONSTRUCTIBLE
    assert results["peak_fluence_J_m2"].value == pytest.approx(18.8)


def test_v2g3_range_frequency_blocks_pulse_interval() -> None:
    """V2-2: '0.2-25 MHz' must not degrade to a point - pulse_interval becomes
    AMBIGUOUS (REPORTED_NON_POINT), never a verified value."""
    spec = _spec(_range_field("frequency", (0.2, 25.0), "MHz"))
    results = {r.coordinate: r for r in CoordinateEvaluator().evaluate(spec)}
    interval = results["pulse_interval"]
    assert interval.status == CoordinateStatus.AMBIGUOUS
    assert interval.blocking_status == "REPORTED_NON_POINT"
    assert results["pulse_energy"].status == CoordinateStatus.AMBIGUOUS
    assert results["pulse_spacing"].status == CoordinateStatus.AMBIGUOUS
    assert results["pulses_per_spot"].status == CoordinateStatus.AMBIGUOUS


def test_v2g3_range_fluence_blocks_fluence_coordinate() -> None:
    """V2-2: a fluence range report is AMBIGUOUS for peak_fluence_J_m2 itself
    (and for normalized_fluence which depends on it)."""
    spec = _spec(_range_field("fluence", (2.3, 7.0), "J/cm2"))
    results = {r.coordinate: r for r in CoordinateEvaluator().evaluate(spec)}
    assert results["peak_fluence_J_m2"].status == CoordinateStatus.AMBIGUOUS
    assert results["peak_fluence_J_m2"].blocking_status == "REPORTED_NON_POINT"
    assert results["normalized_fluence"].status == CoordinateStatus.AMBIGUOUS


def test_v2g4_range_never_contributes_positive_interaction_evidence() -> None:
    """V2-G4: a range-derived coordinate must never be AVAILABLE, so canonical
    comparison can never claim COMPARABLE on it (V2-2 conservative rule)."""
    from ultrafast_ingestion.conditions.models import ConditionField, ExperimentalConditionSpec
    from ultrafast_ingestion.linking.models import ConditionRole, Scope
    from ultrafast_interaction.canonical import (
        CoordinateAvailability,
        source_state,
    )
    from ultrafast_reconstructibility.adapter import to_source_condition_spec

    condition = ExperimentalConditionSpec(
        condition_id="c1",
        paper_id="p1",
        role=ConditionRole.PROCESSING,
        scope=Scope.EXPERIMENT_GROUP,
    )
    condition.fields["frequency"] = ConditionField(
        parameter="frequency",
        status=FieldStatus.REPORTED_CLEAR,
        values=[0.2, 25.0],
        unit="MHz",
        value_shape="RANGE",
    )
    from ultrafast_reconstructibility.report import build_report

    spec = to_source_condition_spec(condition)
    state = source_state(build_report(spec))
    interval = state.coordinates["pulse_interval"]
    assert interval.availability == CoordinateAvailability.AMBIGUOUS
    assert interval.availability != CoordinateAvailability.AVAILABLE
