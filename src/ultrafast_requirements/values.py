"""Strict quantity input normalization and deterministic unit conversion."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ultrafast_requirements.schemas import (
    DecisionVariable,
    QuantityValue,
    RequirementSource,
    VerificationStatus,
)
from ultrafast_shared.units import convert

CANONICAL_UNITS: dict[str, str] = {
    "laser_power_W": "W",
    "frequency_Hz": "Hz",
    "scan_speed_m_s": "m/s",
    "pulse_width_s": "s",
    "hatch_spacing_m": "m",
    "beam_radius_m": "m",
    "spot_diameter_m": "m",
    "pulse_energy_J": "J",
    "ablation_threshold_J_m2": "J/m2",
    "optical_penetration_depth_m": "m",
    "passes": "",
    "incubation_coefficient": "",
}

QUANTITY_ALIASES: dict[str, str] = {
    "average_power_W": "laser_power_W",
    "frequency_kHz": "frequency_Hz",
    "repetition_rate_Hz": "frequency_Hz",
    "scan_speed_mm_s": "scan_speed_m_s",
    "pulse_width_fs": "pulse_width_s",
    "hatch_spacing_um": "hatch_spacing_m",
    "spot_radius_um": "beam_radius_m",
}


def canonical_quantity(quantity: str) -> str:
    return QUANTITY_ALIASES.get(quantity, quantity)


def _canonical_value(value: float, unit: str, canonical_unit: str) -> float:
    if canonical_unit == "":
        if unit.strip() not in {"", "1", "count"}:
            raise ValueError(f"dimensionless quantity cannot use unit {unit!r}")
        return float(value)
    converted = convert(float(value), unit, canonical_unit)
    if converted is None:
        raise ValueError(f"unit {unit!r} is not convertible to {canonical_unit!r}")
    return float(converted)


class QuantityInputNormalizer:
    def normalize_values(
        self,
        raw: Mapping[str, Any] | list[dict[str, Any]] | None,
    ) -> list[QuantityValue]:
        if raw is None:
            return []
        records: list[dict[str, Any]] = []
        if isinstance(raw, Mapping):
            for quantity, payload in raw.items():
                if not isinstance(payload, Mapping):
                    raise TypeError(
                        f"naked value forbidden for {quantity!r}; provide value, unit, and source"
                    )
                records.append({"quantity": quantity, **dict(payload)})
        else:
            records = [dict(item) for item in raw]
        output: list[QuantityValue] = []
        seen: set[str] = set()
        for record in records:
            quantity = str(record.get("quantity") or "").strip()
            required = {"value", "unit", "source"}
            if not quantity or not required.issubset(record):
                raise ValueError("QuantityValue requires quantity, value, unit, and source")
            canonical = canonical_quantity(quantity)
            canonical_unit = CANONICAL_UNITS.get(canonical)
            if canonical_unit is None:
                raise ValueError(f"unknown canonical quantity: {canonical}")
            if canonical in seen:
                raise ValueError(f"duplicate canonical quantity: {canonical}")
            source = RequirementSource(str(record["source"]))
            verification = VerificationStatus(
                str(record.get("verification_status") or "verified")
            )
            value = float(record["value"])
            unit = str(record["unit"])
            output.append(
                QuantityValue(
                    quantity=quantity,
                    value=value,
                    unit=unit,
                    canonical_quantity=canonical,
                    canonical_value=_canonical_value(value, unit, canonical_unit),
                    canonical_unit=canonical_unit,
                    source=source,
                    verification_status=verification,
                )
            )
            seen.add(canonical)
        return output

    def normalize_decisions(self, raw: list[dict[str, Any]] | None) -> list[DecisionVariable]:
        output: list[DecisionVariable] = []
        seen: set[str] = set()
        for record in raw or []:
            quantity = str(record.get("quantity") or "").strip()
            required = {"minimum", "maximum", "resolution", "unit"}
            if not quantity or not required.issubset(record):
                raise ValueError(
                    "DecisionVariable requires quantity, minimum, maximum, resolution, and unit"
                )
            canonical = canonical_quantity(quantity)
            canonical_unit = CANONICAL_UNITS.get(canonical)
            if canonical_unit is None:
                raise ValueError(f"unknown decision quantity: {canonical}")
            if canonical in seen:
                raise ValueError(f"duplicate decision variable: {canonical}")
            unit = str(record["unit"])
            minimum = float(record["minimum"])
            maximum = float(record["maximum"])
            resolution = float(record["resolution"])
            canonical_minimum = _canonical_value(minimum, unit, canonical_unit)
            canonical_maximum = _canonical_value(maximum, unit, canonical_unit)
            canonical_resolution = _canonical_value(resolution, unit, canonical_unit)
            if canonical_minimum >= canonical_maximum:
                raise ValueError(f"decision bounds must increase: {canonical}")
            if canonical_resolution <= 0 or canonical_resolution > (
                canonical_maximum - canonical_minimum
            ):
                raise ValueError(f"invalid decision resolution: {canonical}")
            admissible = []
            for pair in record.get("admissible_region") or []:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError(f"invalid admissible region for {canonical}")
                lower = _canonical_value(float(pair[0]), unit, canonical_unit)
                upper = _canonical_value(float(pair[1]), unit, canonical_unit)
                if lower >= upper or lower < canonical_minimum or upper > canonical_maximum:
                    raise ValueError(f"admissible region outside decision bounds: {canonical}")
                admissible.append((lower, upper))
            output.append(
                DecisionVariable(
                    quantity=quantity,
                    minimum=minimum,
                    maximum=maximum,
                    resolution=resolution,
                    unit=unit,
                    canonical_quantity=canonical,
                    canonical_minimum=canonical_minimum,
                    canonical_maximum=canonical_maximum,
                    canonical_resolution=canonical_resolution,
                    canonical_unit=canonical_unit,
                    admissible_region=admissible,
                    source=RequirementSource(str(record.get("source") or "task")),
                    verification_status=VerificationStatus(
                        str(record.get("verification_status") or "verified")
                    ),
                )
            )
            seen.add(canonical)
        return output
