"""Feature Engine：按 FeatureSpec 计算物理特征（文档 §28-29）。

- 输入统一单位（由 resolver 提供 SI 值 + 单位声明）；
- 缺输入 → unavailable（不静默假设）；
- 结果带 provenance（formula version + source inputs + approximate 标记）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ultrafast_physics.registry import FeatureValue, get_formula
from ultrafast_shared.units import convert

# 派生链：feature 可由上游物理特征提供（避免重复计算）
DERIVED_FROM_FORMULA: dict[str, dict[str, Any]] = {
    "pulse_energy_J": {"formula": "pulse_energy", "from": {"laser_power_W", "frequency_Hz"}},
    "pulse_spacing_m": {"formula": "pulse_spacing", "from": {"scan_speed_m_s", "frequency_Hz"}},
    "peak_fluence_J_m2": {"formula": "peak_fluence", "from": {"pulse_energy_J", "beam_radius_m"}},
}

# 输入名 → 规范单位（SI）
INPUT_UNITS: dict[str, str] = {
    "laser_power_W": "W",
    "frequency_Hz": "Hz",
    "pulse_width_s": "s",
    "scan_speed_m_s": "m/s",
    "hatch_spacing_m": "m",
    "passes": "",
    "pulse_energy_J": "J",
    "beam_radius_m": "m",
    "spot_diameter_m": "m",
    "ablation_threshold_J_m2": "J/m2",
    "thermal_diffusivity_m2_s": "m2/s",
}

Resolver = Callable[[str], tuple[float, str] | None]


class PhysicsFeatureEngine:
    """执行引擎：resolver 提供 (值, 单位)，engine 统一换算并计算。"""

    def __init__(self, resolver: Resolver | None = None):
        self.resolver = resolver

    def compute(
        self, feature_id: str, inputs: dict[str, tuple[float, str]] | None = None
    ) -> FeatureValue:
        formula = get_formula(feature_id)
        resolved: dict[str, float] = {}
        missing: list[str] = []
        for name in formula.required_inputs:
            value = self._resolve_input(name, inputs)
            if value is None:
                missing.append(name)
            else:
                resolved[name] = value
        if missing:
            return FeatureValue(
                feature_id=feature_id,
                value=None,
                unit=self._output_unit(feature_id),
                available=False,
                missing_inputs=missing,
                formula_id=feature_id,
                formula_version=formula.version,
                source_inputs={name: value for name, value in resolved.items()},
                approximate=formula.approximate,
            )
        try:
            value = formula.compute(resolved)
        except (KeyError, ZeroDivisionError, TypeError, ValueError):
            return FeatureValue(
                feature_id=feature_id,
                value=None,
                unit=self._output_unit(feature_id),
                available=False,
                missing_inputs=list(resolved),
                formula_id=feature_id,
                formula_version=formula.version,
                source_inputs=resolved,
                approximate=formula.approximate,
            )
        return FeatureValue(
            feature_id=feature_id,
            value=float(value),
            unit=self._output_unit(feature_id),
            available=True,
            formula_id=feature_id,
            formula_version=formula.version,
            source_inputs=resolved,
            approximate=formula.approximate,
        )

    def compute_many(self, feature_ids: list[str], inputs: dict[str, tuple[float, str]]) -> dict[str, FeatureValue]:
        results: dict[str, FeatureValue] = {}
        for feature_id in feature_ids:
            results[feature_id] = self.compute(feature_id, inputs)
        return results

    def compute_chain(
        self,
        feature_id: str,
        inputs: dict[str, tuple[float, str]],
        depth: int = 0,
    ) -> FeatureValue:
        """Compute with derived-input resolution (DERIVED_FROM_FORMULA chain).

        Formula outputs feed later formulas as inputs (pulse_spacing_m,
        pulse_energy_J, peak_fluence_J_m2). Still registry-driven - no
        hand-written math here.
        """
        if depth > 8:
            return self.compute(feature_id, inputs)
        result = self.compute(feature_id, inputs)
        if result.available or not result.missing_inputs:
            return result
        derived_inputs = dict(inputs)
        for name in result.missing_inputs:
            derived = DERIVED_FROM_FORMULA.get(name)
            if derived is None:
                continue
            sub = self.compute_chain(derived["formula"], derived_inputs, depth + 1)
            if sub.available and sub.value is not None and sub.unit is not None:
                derived_inputs[name] = (sub.value, sub.unit)
        return self.compute(feature_id, derived_inputs)

    def _resolve_input(
        self, name: str, inputs: dict[str, tuple[float, str]] | None
    ) -> float | None:
        if inputs and name in inputs:
            value, unit = inputs[name]
            converted = convert(value, unit, INPUT_UNITS.get(name))
            if converted is not None:
                return converted
            return None
        if self.resolver is not None:
            resolved = self.resolver(name)
            if resolved is None:
                return None
            value, unit = resolved
            converted = convert(value, unit, INPUT_UNITS.get(name))
            if converted is not None:
                return converted
        return None

    @staticmethod
    def _output_unit(feature_id: str) -> str | None:
        output_units = {
            "pulse_energy": "J",
            "pulse_interval": "s",
            "pulse_spacing": "m",
            "line_energy": "J/m",
            "areal_energy": "J/m2",
            "peak_fluence": "J/m2",
            "pulse_overlap": "",
            "hatch_overlap": "",
            "pulses_per_spot": "",
            "normalized_fluence": "",
            "thermal_accumulation_number": "",
        }
        return output_units.get(feature_id)
