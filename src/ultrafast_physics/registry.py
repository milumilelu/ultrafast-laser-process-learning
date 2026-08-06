"""Physics Feature Engine（文档 §28-29）。

独立公式 registry + 版本化执行引擎：
- 公式由 registry 管理；
- 输入单位必须统一（SI）；
- 缺少关键输入时输出 unavailable（禁止静默假设 spot radius / beam profile）；
- 近似量必须标记 approximate；
- 每个计算结果保存 source inputs 与公式版本。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

InputResolver = Callable[[str], float | None]


@dataclass(frozen=True, slots=True)
class FormulaDef:
    formula_id: str
    version: str
    description: str
    compute: Callable[[dict[str, float]], float]
    required_inputs: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    approximate: bool = False


@dataclass(slots=True)
class FeatureValue:
    feature_id: str
    value: float | None
    unit: str | None
    available: bool
    missing_inputs: list[str] = field(default_factory=list)
    formula_id: str | None = None
    formula_version: str | None = None
    source_inputs: dict[str, float] = field(default_factory=dict)
    approximate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "value": self.value,
            "unit": self.unit,
            "available": self.available,
            "missing_inputs": self.missing_inputs,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "source_inputs": self.source_inputs,
            "approximate": self.approximate,
        }


def _require(inputs: dict[str, float], names: list[str]) -> dict[str, float] | None:
    missing = [name for name in names if name not in inputs or inputs[name] is None]
    if missing:
        return None
    return {name: float(inputs[name]) for name in names}


# ---------------------------------------------------------------- formulas
def _pulse_energy(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["laser_power_W", "frequency_Hz"])
    if required is None:
        raise KeyError("pulse_energy requires laser_power_W and frequency_Hz")
    return required["laser_power_W"] / required["frequency_Hz"]


def _pulse_interval(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["frequency_Hz"])
    if required is None:
        raise KeyError("pulse_interval requires frequency_Hz")
    return 1.0 / required["frequency_Hz"]


def _pulse_spacing(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["scan_speed_m_s", "frequency_Hz"])
    if required is None:
        raise KeyError("pulse_spacing requires scan_speed_m_s and frequency_Hz")
    return required["scan_speed_m_s"] / required["frequency_Hz"]


def _line_energy(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["laser_power_W", "scan_speed_m_s"])
    if required is None:
        raise KeyError("line_energy requires laser_power_W and scan_speed_m_s")
    return required["laser_power_W"] / required["scan_speed_m_s"]


def _areal_energy(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["laser_power_W", "passes", "scan_speed_m_s", "hatch_spacing_m"])
    if required is None:
        raise KeyError("areal_energy requires power/passes/speed/hatch")
    return (
        required["laser_power_W"]
        * required["passes"]
        / (required["scan_speed_m_s"] * required["hatch_spacing_m"])
    )


def _peak_fluence(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["pulse_energy_J", "beam_radius_m"])
    if required is None:
        raise KeyError("peak_fluence requires pulse_energy_J and beam_radius_m")
    return 2.0 * required["pulse_energy_J"] / (3.141592653589793 * required["beam_radius_m"] ** 2)


def _pulse_overlap(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["pulse_spacing_m", "spot_diameter_m"])
    if required is None:
        raise KeyError("pulse_overlap requires pulse_spacing_m and spot_diameter_m")
    return 1.0 - required["pulse_spacing_m"] / required["spot_diameter_m"]


def _hatch_overlap(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["hatch_spacing_m", "spot_diameter_m"])
    if required is None:
        raise KeyError("hatch_overlap requires hatch_spacing_m and spot_diameter_m")
    return 1.0 - required["hatch_spacing_m"] / required["spot_diameter_m"]


def _pulses_per_spot(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["spot_diameter_m", "frequency_Hz", "scan_speed_m_s"])
    if required is None:
        raise KeyError("pulses_per_spot requires diameter/frequency/speed")
    return required["spot_diameter_m"] * required["frequency_Hz"] / required["scan_speed_m_s"]


def _normalized_fluence(inputs: dict[str, float]) -> float:
    required = _require(inputs, ["peak_fluence_J_m2", "ablation_threshold_J_m2"])
    if required is None:
        raise KeyError("normalized_fluence requires peak_fluence_J_m2 and ablation_threshold_J_m2")
    return required["peak_fluence_J_m2"] / required["ablation_threshold_J_m2"]


def _thermal_accumulation(inputs: dict[str, float]) -> float:
    """工程描述符 H = f·w0²/(4·α)（文档 §27.11，明确标记 engineering_descriptor）。"""
    required = _require(inputs, ["frequency_Hz", "beam_radius_m", "thermal_diffusivity_m2_s"])
    if required is None:
        raise KeyError("thermal_accumulation requires frequency/radius/diffusivity")
    return (
        required["frequency_Hz"]
        * required["beam_radius_m"] ** 2
        / (4.0 * required["thermal_diffusivity_m2_s"])
    )


FORMULAS: dict[str, FormulaDef] = {
    "pulse_energy": FormulaDef(
        "pulse_energy", "v1", "Ep = Pavg / f", _pulse_energy,
        ("laser_power_W", "frequency_Hz"), ("mean_power_definition",),
    ),
    "pulse_interval": FormulaDef(
        "pulse_interval", "v1", "dt = 1 / f", _pulse_interval, ("frequency_Hz",),
    ),
    "pulse_spacing": FormulaDef(
        "pulse_spacing", "v1", "dx = v / f", _pulse_spacing,
        ("scan_speed_m_s", "frequency_Hz"),
    ),
    "line_energy": FormulaDef(
        "line_energy", "v1", "Eline = Pavg / v", _line_energy,
        ("laser_power_W", "scan_speed_m_s"),
    ),
    "areal_energy": FormulaDef(
        "areal_energy", "v1", "Earea = Pavg * Npass / (v * hatch)", _areal_energy,
        ("laser_power_W", "passes", "scan_speed_m_s", "hatch_spacing_m"),
    ),
    "peak_fluence": FormulaDef(
        "peak_fluence", "v1", "F0 = 2 * Ep / (pi * w0^2)", _peak_fluence,
        ("pulse_energy_J", "beam_radius_m"),
        ("gaussian_spatial_profile", "beam_radius_m_is_1e2_radius"),
    ),
    "pulse_overlap": FormulaDef(
        "pulse_overlap", "v1", "Ox = 1 - dx / d", _pulse_overlap,
        ("pulse_spacing_m", "spot_diameter_m"),
    ),
    "hatch_overlap": FormulaDef(
        "hatch_overlap", "v1", "Oy = 1 - hatch / d", _hatch_overlap,
        ("hatch_spacing_m", "spot_diameter_m"),
    ),
    "pulses_per_spot": FormulaDef(
        "pulses_per_spot", "v1", "Nspot ~ d * f / v", _pulses_per_spot,
        ("spot_diameter_m", "frequency_Hz", "scan_speed_m_s"), (), approximate=True,
    ),
    "normalized_fluence": FormulaDef(
        "normalized_fluence", "v1", "Phi = F0 / Fth", _normalized_fluence,
        ("peak_fluence_J_m2", "ablation_threshold_J_m2"),
        ("governed_threshold_required",),
    ),
    "thermal_accumulation_number": FormulaDef(
        "thermal_accumulation_number", "v1", "H = f * w0^2 / (4 * alpha)",
        _thermal_accumulation,
        ("frequency_Hz", "beam_radius_m", "thermal_diffusivity_m2_s"),
        ("engineering_descriptor_not_full_thermal_model",),
    ),
}


def get_formula(formula_id: str) -> FormulaDef:
    if formula_id not in FORMULAS:
        raise KeyError(f"unknown formula: {formula_id}")
    return FORMULAS[formula_id]


def available_formulas() -> tuple[str, ...]:
    return tuple(FORMULAS)
