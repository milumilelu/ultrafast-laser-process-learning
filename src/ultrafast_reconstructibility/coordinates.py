"""M6-2: Physics dependency evaluation.

P1: no hand-written formulas. The only authority is the Formula Registry:
  - required inputs come from get_formula(id).required_inputs
  - availability comes from PhysicsFeatureEngine.compute (missing_inputs)
Missing-input classification (contract §1/§3):

  input from a condition field:
      field REPORTED_CLEAR        -> provided
      field CONFLICT/LINKAGE_AMB  -> coordinate AMBIGUOUS
      field absent, coverage OK   -> NOT_REPORTED
      field absent, coverage bad  -> TEXT_COVERAGE_BLOCKED
  input is a device/material property -> DEPENDENCY_MISSING
"""

from __future__ import annotations

from ultrafast_physics.engine import PhysicsFeatureEngine
from ultrafast_physics.registry import FORMULAS, get_formula
from ultrafast_reconstructibility.models import (
    CoordinateResult,
    CoordinateStatus,
    CoverageStatus,
    FieldStatus,
    SourceConditionSpec,
    ValueShape,
)

# condition canonical parameter -> physics engine input name (contract §3)
CONDITION_TO_INPUT: dict[str, str] = {
    "frequency": "frequency_Hz",
    "pulse_width": "pulse_width_s",
    "scan_speed": "scan_speed_m_s",
    "hatch_spacing": "hatch_spacing_m",
    "passes": "passes",
    "pulse_energy": "pulse_energy_J",
    "average_power": "laser_power_W",
    "spot_size": "spot_diameter_m",
    "fluence": "peak_fluence_J_m2",
    "accumulated_dose": "areal_energy_J_m2",
}

# J_m2 coordinates are aliases of registry formulas (V2-1): no coordinate-specific
# bypass - RECONSTRUCTIBLE iff direct point report or the dependency chain is
# genuinely satisfied (P1: Formula Registry is the only authority).
COORDINATE_ALIASES: dict[str, str] = {
    "peak_fluence_J_m2": "peak_fluence",
    "areal_energy_J_m2": "areal_energy",
}

# device/material properties never come from the source paper (contract §3)
DEVICE_PROPERTY_INPUTS = frozenset(
    {
        "beam_radius_m",
        "spot_diameter_m",
        "ablation_threshold_J_m2",
        "thermal_diffusivity_m2_s",
    }
)

# coordinates evaluated by M6 (CFA V1 candidate set is frozen later from stats)
COORDINATES = tuple(FORMULAS) + ("peak_fluence_J_m2", "areal_energy_J_m2")


class CoordinateEvaluator:
    """Evaluates physics coordinates against one SourceConditionSpec."""

    def __init__(self) -> None:
        self.engine = PhysicsFeatureEngine()

    def evaluate(self, spec: SourceConditionSpec) -> list[CoordinateResult]:
        field_by_param = {f.parameter: f for f in spec.fields}
        inputs: dict[str, tuple[float, str]] = {}
        ambiguous: dict[str, str] = {}
        non_point: dict[str, str] = {}
        for param, input_name in CONDITION_TO_INPUT.items():
            field = field_by_param.get(param)
            if field is None:
                continue
            if field.field_status != FieldStatus.REPORTED_CLEAR:
                ambiguous[input_name] = param
                continue
            if not field.values:
                continue
            # V2-2: RANGE/LIST/SET/SWEEP is not a point observation - a range
            # endpoint (or list head) must never act as a verified value.
            if field.value_shape != ValueShape.POINT:
                non_point[input_name] = param
                continue
            inputs[input_name] = (float(field.values[0]), field.unit)
        # spot_size is a diameter: beam_radius = d/2 is a deterministic
        # derivation (same convention as feature_builder); provide it so
        # peak_fluence can consume it.
        if "spot_diameter_m" in inputs and "beam_radius_m" not in inputs:
            d, unit = inputs["spot_diameter_m"]
            inputs["beam_radius_m"] = (d / 2.0, unit)

        results: list[CoordinateResult] = []
        for coordinate in COORDINATES:
            results.append(
                self._evaluate_coordinate(spec, coordinate, inputs, ambiguous, non_point)
            )
        return results

    def _evaluate_coordinate(
        self,
        spec: SourceConditionSpec,
        coordinate: str,
        inputs: dict[str, tuple[float, str]],
        ambiguous: dict[str, str],
        non_point: dict[str, str],
    ) -> CoordinateResult:
        if coordinate in COORDINATE_ALIASES:
            if coordinate in non_point:
                # the paper reports this coordinate itself, but as a range/list:
                # AMBIGUOUS, never a point value (V2-2).
                return CoordinateResult(
                    coordinate=coordinate,
                    status=CoordinateStatus.AMBIGUOUS,
                    missing_inputs=(coordinate,),
                    blocking_status="REPORTED_NON_POINT",
                )
            if coordinate in inputs:
                # paper directly reports the coordinate (point value)
                value, unit = inputs[coordinate]
                return CoordinateResult(
                    coordinate=coordinate,
                    status=CoordinateStatus.RECONSTRUCTIBLE,
                    value=value,
                    unit=unit,
                )
        formula_id = COORDINATE_ALIASES.get(coordinate, coordinate)
        try:
            formula = get_formula(formula_id)
        except KeyError:
            return CoordinateResult(coordinate=coordinate, status=CoordinateStatus.NOT_APPLICABLE)
        blocked_non_point = [
            name for name in formula.required_inputs if name in non_point
        ]
        if blocked_non_point:
            return CoordinateResult(
                coordinate=coordinate,
                status=CoordinateStatus.AMBIGUOUS,
                missing_inputs=tuple(blocked_non_point),
                blocking_status="REPORTED_NON_POINT",
            )
        blocked_by_ambiguous = [
            name for name in formula.required_inputs if name in ambiguous
        ]
        if blocked_by_ambiguous:
            return CoordinateResult(
                coordinate=coordinate,
                status=CoordinateStatus.AMBIGUOUS,
                missing_inputs=tuple(blocked_by_ambiguous),
                blocking_status="REPORTED_AMBIGUOUS",
            )
        result = self.engine.compute_chain(formula_id, inputs)
        if result.available:
            return CoordinateResult(
                coordinate=coordinate,
                status=CoordinateStatus.RECONSTRUCTIBLE,
                value=result.value,
                unit=result.unit,
                formula_version=result.formula_version,
                approximate=result.approximate,
            )
        status, detail = self._classify_missing(spec, result.missing_inputs)
        return CoordinateResult(
            coordinate=coordinate,
            status=status,
            missing_inputs=tuple(result.missing_inputs),
            blocking_status=detail,
        )

    def _classify_missing(
        self, spec: SourceConditionSpec, missing: list[str]
    ) -> tuple[CoordinateStatus, str]:
        """Five-way classification per contract §1."""
        statuses: list[CoordinateStatus] = []
        for name in missing:
            if name in DEVICE_PROPERTY_INPUTS:
                statuses.append(CoordinateStatus.DEPENDENCY_MISSING)
                continue
            if spec.coverage_status != CoverageStatus.TEXT_COVERAGE_OK:
                statuses.append(CoordinateStatus.TEXT_COVERAGE_BLOCKED)
            else:
                statuses.append(CoordinateStatus.NOT_REPORTED)
        if not statuses:
            return CoordinateStatus.NOT_APPLICABLE, ""
        # most specific status wins: DEPENDENCY_MISSING > COVERAGE > NOT_REPORTED
        if CoordinateStatus.DEPENDENCY_MISSING in statuses:
            return CoordinateStatus.DEPENDENCY_MISSING, "device_or_material_property"
        if CoordinateStatus.TEXT_COVERAGE_BLOCKED in statuses:
            return CoordinateStatus.TEXT_COVERAGE_BLOCKED, "text_coverage_blocked"
        return CoordinateStatus.NOT_REPORTED, "not_reported"
