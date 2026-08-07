"""M7: Target Physics Readiness.

Contract: docs/contracts/TARGET_PHYSICS_READINESS_V0_1.md.

Core rule (frozen):
    Unverified input cannot silently satisfy a physics dependency.
A coordinate whose inputs are all verified/measured -> AVAILABLE;
with any UNVERIFIED input -> AVAILABLE_WITH_UNVERIFIED_ASSUMPTION
(recorded in readiness, NEVER consumed by formal CFA); with a missing
input -> BLOCKED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from ultrafast_physics.engine import PhysicsFeatureEngine
from ultrafast_physics.registry import FORMULAS, get_formula


class TargetInputSource(StrEnum):
    DATASET = "DATASET"
    EQUIPMENT_PROFILE = "EQUIPMENT_PROFILE"
    DEVICE_PROPERTY = "DEVICE_PROPERTY"
    DERIVED = "DERIVED"


class InputVerificationStatus(StrEnum):
    MEASURED = "MEASURED"
    VERIFIED_EQUIPMENT_PROPERTY = "VERIFIED_EQUIPMENT_PROPERTY"
    DERIVED = "DERIVED"
    UNVERIFIED = "UNVERIFIED"
    MISSING = "MISSING"


class TargetCoordinateStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    AVAILABLE_WITH_UNVERIFIED_ASSUMPTION = "AVAILABLE_WITH_UNVERIFIED_ASSUMPTION"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class TargetInputFact:
    input_name: str  # physics engine input (frequency_Hz, ...)
    value: float | None
    unit: str
    source: TargetInputSource
    verification_status: InputVerificationStatus
    field_name: str  # originating dataset column / profile key
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_name": self.input_name,
            "value": self.value,
            "unit": self.unit,
            "source": self.source.value,
            "verification_status": self.verification_status.value,
            "field_name": self.field_name,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class TargetConditionSpec:
    """Deterministic projection of dataset + equipment profile into
    physics-consumable target inputs."""

    input_facts: tuple[TargetInputFact, ...]
    dataset_name: str = ""
    equipment_profile_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "equipment_profile_id": self.equipment_profile_id,
            "input_facts": [f.to_dict() for f in self.input_facts],
        }


@dataclass(frozen=True, slots=True)
class TargetCoordinateResult:
    coordinate: str
    status: TargetCoordinateStatus
    value: float | None = None
    unit: str | None = None
    formula_version: str | None = None
    approximate: bool = False
    unverified_inputs: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "coordinate": self.coordinate,
            "status": self.status.value,
            "value": self.value,
            "unit": self.unit,
            "formula_version": self.formula_version,
            "approximate": self.approximate,
            "unverified_inputs": list(self.unverified_inputs),
            "missing_inputs": list(self.missing_inputs),
        }


@dataclass(slots=True)
class TargetPhysicsReadinessReport:
    verified_inputs: list[TargetInputFact] = field(default_factory=list)
    unverified_inputs: list[TargetInputFact] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    available_coordinates: list[TargetCoordinateResult] = field(default_factory=list)
    unverified_assumption_coordinates: list[TargetCoordinateResult] = field(default_factory=list)
    blocked_coordinates: list[TargetCoordinateResult] = field(default_factory=list)
    blocking_dependencies: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified_inputs": [f.to_dict() for f in self.verified_inputs],
            "unverified_inputs": [f.to_dict() for f in self.unverified_inputs],
            "missing_inputs": list(self.missing_inputs),
            "available_coordinates": [c.to_dict() for c in self.available_coordinates],
            "unverified_assumption_coordinates": [
                c.to_dict() for c in self.unverified_assumption_coordinates
            ],
            "blocked_coordinates": [c.to_dict() for c in self.blocked_coordinates],
            "blocking_dependencies": list(self.blocking_dependencies),
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class TargetPhysicsReadiness:
    """Simplified projection for CFA/M8 (contract M7 §4)."""

    verified_input_count: int = 0
    unverified_input_count: int = 0
    missing_input_count: int = 0
    available_coordinate_count: int = 0
    unverified_assumption_coordinate_count: int = 0
    blocked_coordinate_count: int = 0
    coordinate_status: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified_input_count": self.verified_input_count,
            "unverified_input_count": self.unverified_input_count,
            "missing_input_count": self.missing_input_count,
            "available_coordinate_count": self.available_coordinate_count,
            "unverified_assumption_coordinate_count": self.unverified_assumption_coordinate_count,
            "blocked_coordinate_count": self.blocked_coordinate_count,
            "coordinate_status": dict(self.coordinate_status),
        }


# dataset column -> (engine input name, unit)
_DATASET_COLUMN_TO_INPUT: dict[str, tuple[str, str]] = {
    "pulse_width_ps": ("pulse_width_s", "ps"),
    "frequency_kHz": ("frequency_Hz", "kHz"),
    "scan_speed_mm_s": ("scan_speed_m_s", "mm/s"),
    "hatch_spacing_um": ("hatch_spacing_m", "um"),
    "passes": ("passes", ""),
    "laser_power_W": ("laser_power_W", "W"),
}

# equipment profile key -> (engine input name, unit)
_PROFILE_TO_INPUT: dict[str, tuple[str, str]] = {
    "spot_radius_um": ("beam_radius_m", "um"),
    "ablation_threshold_J_m2": ("ablation_threshold_J_m2", "J/m2"),
    "thermal_diffusivity_m2_s": ("thermal_diffusivity_m2_s", "m2/s"),
}


def build_target_condition_spec(
    csv_path: Path,
    *,
    equipment_profile: dict[str, tuple[float, str, bool]] | None = None,
    dataset_name: str = "",
    equipment_profile_id: str = "",
) -> TargetConditionSpec:
    """Dataset columns + equipment profile -> TargetConditionSpec.

    equipment_profile values: (value, unit, verified). A present-but-unverified
    profile value (e.g. spot=5um) is UNVERIFIED - never AVAILABLE (M7 rule).
    """
    df = pd.read_csv(csv_path)
    facts: list[TargetInputFact] = []
    for column, (input_name, unit) in _DATASET_COLUMN_TO_INPUT.items():
        if column not in df.columns:
            facts.append(
                TargetInputFact(
                    input_name=input_name,
                    value=None,
                    unit=unit,
                    source=TargetInputSource.DATASET,
                    verification_status=InputVerificationStatus.MISSING,
                    field_name=column,
                    provenance=f"dataset:{csv_path.name}",
                )
            )
            continue
        values = df[column].dropna()
        if values.empty:
            facts.append(
                TargetInputFact(
                    input_name=input_name,
                    value=None,
                    unit=unit,
                    source=TargetInputSource.DATASET,
                    verification_status=InputVerificationStatus.MISSING,
                    field_name=column,
                    provenance=f"dataset:{csv_path.name}",
                )
            )
            continue
        facts.append(
            TargetInputFact(
                input_name=input_name,
                value=float(values.median()),
                unit=unit,
                source=TargetInputSource.DATASET,
                verification_status=InputVerificationStatus.MEASURED,
                field_name=column,
                provenance=f"dataset:{csv_path.name}",
            )
        )
    for key, (value, unit, verified) in (equipment_profile or {}).items():
        mapped: tuple[str, str] | None = _PROFILE_TO_INPUT.get(key)
        if mapped is None:
            continue
        input_name, input_unit = mapped
        facts.append(
            TargetInputFact(
                input_name=input_name,
                value=float(value),
                unit=input_unit,
                source=TargetInputSource.EQUIPMENT_PROFILE,
                verification_status=(
                    InputVerificationStatus.VERIFIED_EQUIPMENT_PROPERTY
                    if verified
                    else InputVerificationStatus.UNVERIFIED
                ),
                field_name=key,
                provenance=f"equipment_profile:{equipment_profile_id or key}",
            )
        )
    return TargetConditionSpec(
        input_facts=tuple(facts),
        dataset_name=dataset_name or csv_path.name,
        equipment_profile_id=equipment_profile_id,
    )


class TargetCoordinateEvaluator:
    """Physics dependency evaluation for the target side (P1: registry only)."""

    def __init__(self) -> None:
        self.engine = PhysicsFeatureEngine()

    def evaluate(self, spec: TargetConditionSpec) -> TargetPhysicsReadinessReport:
        fact_by_input = {f.input_name: f for f in spec.input_facts}
        # beam_radius from spot radius is a deterministic derivation (d=2w0);
        # derived from an UNVERIFIED profile value keeps the UNVERIFIED state.
        radius_fact = fact_by_input.get("beam_radius_m")
        if radius_fact is not None and radius_fact.verification_status == InputVerificationStatus.UNVERIFIED:
            fact_by_input["beam_radius_m"] = TargetInputFact(
                input_name="beam_radius_m",
                value=radius_fact.value,
                unit=radius_fact.unit,
                source=TargetInputSource.DERIVED,
                verification_status=InputVerificationStatus.UNVERIFIED,
                field_name=radius_fact.field_name,
                provenance=radius_fact.provenance,
            )
        # spot_diameter = 2 * beam_radius is a deterministic derivation;
        # verification state propagates from its source.
        radius_fact = fact_by_input.get("beam_radius_m")
        if radius_fact is not None and radius_fact.value is not None:
            fact_by_input["spot_diameter_m"] = TargetInputFact(
                input_name="spot_diameter_m",
                value=radius_fact.value * 2.0,
                unit=radius_fact.unit,
                source=TargetInputSource.DERIVED,
                verification_status=radius_fact.verification_status,
                field_name=radius_fact.field_name,
                provenance=radius_fact.provenance,
            )
        report = TargetPhysicsReadinessReport()
        for fact in spec.input_facts:
            if fact.verification_status == InputVerificationStatus.MISSING:
                report.missing_inputs.append(fact.input_name)
            elif fact.verification_status == InputVerificationStatus.UNVERIFIED:
                report.unverified_inputs.append(fact)
            else:
                report.verified_inputs.append(fact)
        inputs = {
            name: (fact.value, fact.unit)
            for name, fact in fact_by_input.items()
            if fact.value is not None
        }
        verified = {
            name
            for name, fact in fact_by_input.items()
            if fact.verification_status
            not in (InputVerificationStatus.MISSING, InputVerificationStatus.UNVERIFIED)
        }
        for coordinate in tuple(FORMULAS):
            result = self._evaluate(coordinate, inputs, verified)
            if result.status == TargetCoordinateStatus.AVAILABLE:
                report.available_coordinates.append(result)
            elif result.status == TargetCoordinateStatus.AVAILABLE_WITH_UNVERIFIED_ASSUMPTION:
                report.unverified_assumption_coordinates.append(result)
            else:
                report.blocked_coordinates.append(result)
                report.blocking_dependencies.extend(result.missing_inputs)
        report.blocking_dependencies = sorted(set(report.blocking_dependencies))
        if report.unverified_inputs:
            report.warnings.append(
                "unverified inputs: "
                + ", ".join(sorted(f.input_name for f in report.unverified_inputs))
                + " (not consumable by formal CFA)"
            )
        return report

    def _evaluate(
        self,
        coordinate: str,
        inputs: dict[str, tuple[float, str]],
        verified: set[str],
    ) -> TargetCoordinateResult:
        try:
            formula = get_formula(coordinate)
        except KeyError:
            return TargetCoordinateResult(coordinate=coordinate, status=TargetCoordinateStatus.BLOCKED)
        unverified = [name for name in formula.required_inputs if name not in verified]
        result = self.engine.compute_chain(coordinate, inputs)
        if not result.available:
            return TargetCoordinateResult(
                coordinate=coordinate,
                status=TargetCoordinateStatus.BLOCKED,
                missing_inputs=tuple(result.missing_inputs),
            )
        if unverified:
            return TargetCoordinateResult(
                coordinate=coordinate,
                status=TargetCoordinateStatus.AVAILABLE_WITH_UNVERIFIED_ASSUMPTION,
                value=result.value,
                unit=result.unit,
                formula_version=result.formula_version,
                approximate=result.approximate,
                unverified_inputs=tuple(unverified),
            )
        return TargetCoordinateResult(
            coordinate=coordinate,
            status=TargetCoordinateStatus.AVAILABLE,
            value=result.value,
            unit=result.unit,
            formula_version=result.formula_version,
            approximate=result.approximate,
        )


def readiness_projection(report: TargetPhysicsReadinessReport) -> TargetPhysicsReadiness:
    projection = TargetPhysicsReadiness()
    projection.verified_input_count = len(report.verified_inputs)
    projection.unverified_input_count = len(report.unverified_inputs)
    projection.missing_input_count = len(report.missing_inputs)
    projection.available_coordinate_count = len(report.available_coordinates)
    projection.unverified_assumption_coordinate_count = len(report.unverified_assumption_coordinates)
    projection.blocked_coordinate_count = len(report.blocked_coordinates)
    status_counts: dict[str, int] = {}
    for result in (
        report.available_coordinates
        + report.unverified_assumption_coordinates
        + report.blocked_coordinates
    ):
        status_counts[result.status.value] = status_counts.get(result.status.value, 0) + 1
    projection.coordinate_status = status_counts
    return projection
