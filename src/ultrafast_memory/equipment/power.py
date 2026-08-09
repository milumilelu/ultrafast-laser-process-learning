"""Deterministic workpiece-effective maximum power derivation."""

from __future__ import annotations

from typing import Any


def resolve_effective_max_power(
    laser_source: dict[str, Any],
) -> tuple[float | None, str]:
    measured = _number(laser_source.get("measured_max_power_W"))
    rated = _number(laser_source.get("rated_max_power_W"))
    transmission = _number(laser_source.get("power_transmission_ratio"))
    if measured is not None:
        return measured, "MEASURED"
    if rated is not None and transmission is not None:
        return rated * transmission, "DERIVED_FROM_ATTENUATION"
    if rated is not None:
        return rated, "MANUFACTURER_SPEC"
    return None, "UNKNOWN"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
