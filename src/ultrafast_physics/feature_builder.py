"""Feature Builder：原始工艺列 + 设备/材料属性 → 物理特征列（文档 §32-34）。

用于参数辨识 V2 的 physics/hybrid 模式：
- 由 FeatureSpec/公式注册表驱动；
- 缺失设备/材料输入时对应特征列标记 unavailable（不静默假设）；
- 每个构建行保留 provenance。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ultrafast_physics.engine import PhysicsFeatureEngine

# 原始控制列（规范化名）→ 引擎输入名
RAW_TO_INPUT: dict[str, str] = {
    "laser_power_W": "laser_power_W",
    "frequency_kHz": "frequency_Hz",
    "scan_speed_mm_s": "scan_speed_m_s",
    "hatch_spacing_um": "hatch_spacing_m",
    "passes": "passes",
    "pulse_width_fs": "pulse_width_s",
}

# 设备/材料属性 → 引擎输入名
DEVICE_PROPERTY_TO_INPUT: dict[str, str] = {
    "spot_radius_um": "beam_radius_m",
    "thermal_diffusivity_m2_s": "thermal_diffusivity_m2_s",
    "ablation_threshold_J_m2": "ablation_threshold_J_m2",
}

# 物理特征 → 机理组（文档 §37 grouped importance）
FEATURE_GROUPS: dict[str, str] = {
    "pulse_energy": "energy_delivery",
    "line_energy": "energy_delivery",
    "areal_energy": "energy_delivery",
    "peak_fluence": "energy_delivery",
    "peak_power": "energy_delivery",
    "peak_intensity": "energy_delivery",
    "pulse_interval": "thermal",
    "pulse_overlap": "overlap",
    "hatch_overlap": "overlap",
    "pulse_spacing": "overlap",
    "pulses_per_spot": "overlap",
    "normalized_fluence": "energy_delivery",
    "thermal_accumulation_number": "thermal",
}

FEATURE_ORDER = (
    "pulse_energy",
    "pulse_interval",
    "pulse_spacing",
    "line_energy",
    "areal_energy",
    "peak_fluence",
    "pulse_overlap",
    "hatch_overlap",
    "pulses_per_spot",
    "normalized_fluence",
    "thermal_accumulation_number",
)

# 派生：pulse_energy/peak_fluence 等由其他特征组合，构建器内部按序计算
_DERIVED_CHAIN: dict[str, tuple[str, ...]] = {
    "peak_fluence": ("pulse_energy",),
    "pulse_spacing": (),
    "pulse_overlap": ("pulse_spacing",),
    "pulses_per_spot": (),
    "normalized_fluence": ("peak_fluence",),
    "thermal_accumulation_number": (),
}


@dataclass(slots=True)
class BuiltFeatures:
    rows: list[dict[str, Any]] = field(default_factory=list)
    available_features: list[str] = field(default_factory=list)
    unavailable_features: list[str] = field(default_factory=list)
    missing_device_properties: list[str] = field(default_factory=list)

    def feature_frame(self) -> dict[str, list[float | None]]:
        names = self.available_features
        return {name: [row.get(name) for row in self.rows] for name in names}


# 派生：已计算的物理特征回填为后续特征的输入（feature → 引擎输入名）
FEATURE_TO_INPUT: dict[str, str] = {
    "pulse_energy": "pulse_energy_J",
    "pulse_spacing": "pulse_spacing_m",
    "peak_fluence": "peak_fluence_J_m2",
}


class PhysicsFeatureBuilder:
    """按原始控制列 + 设备属性构建物理特征行。"""

    def __init__(
        self,
        *,
        engine: PhysicsFeatureEngine | None = None,
        features: tuple[str, ...] | None = None,
        require_spot_radius: bool = True,
    ):
        self.engine = engine or PhysicsFeatureEngine()
        # None → 固定公式表；显式传入 → E2P FeatureSpec 驱动的特征列表
        self.features = features or FEATURE_ORDER
        self.require_spot_radius = require_spot_radius

    def build(
        self,
        raw_rows: list[dict[str, Any]],
        device_properties: dict[str, tuple[float, str]] | None = None,
    ) -> BuiltFeatures:
        device_properties = dict(device_properties or {})
        spot_available = "spot_radius_um" in device_properties
        if self.require_spot_radius and not spot_available:
            return BuiltFeatures(
                rows=[],
                unavailable_features=list(self.features),
                missing_device_properties=["spot_radius_um"],
            )
        built = BuiltFeatures()
        for raw in raw_rows:
            inputs: dict[str, tuple[float, str]] = {}
            for raw_name, input_name in RAW_TO_INPUT.items():
                value = raw.get(raw_name)
                if value is None:
                    continue
                unit = raw_name.split("_")[-1]
                unit_map = {"kHz": "kHz", "mm_s": "mm/s", "um": "um", "fs": "fs", "W": "W"}
                normalized_unit = unit_map.get(unit)
                inputs[input_name] = (float(value), normalized_unit or "")
            for prop_name, input_name in DEVICE_PROPERTY_TO_INPUT.items():
                if prop_name in device_properties:
                    value, unit = device_properties[prop_name]
                    inputs[input_name] = (float(value), unit)
            # spot radius → spot diameter 严格换算（d = 2*w0，文档 §27.7；
            # 非静默假设：radius/diameter 关系是定义一致的确定性推导）
            if "beam_radius_m" in inputs and "spot_diameter_m" not in inputs:
                radius_value, _unit = inputs["beam_radius_m"]
                inputs["spot_diameter_m"] = (2.0 * radius_value, "m")
            row: dict[str, Any] = {"source_row": raw.get("sample_id") or raw.get("experiment_id")}
            for feature_id in self.features:
                result = self.engine.compute(feature_id, inputs)
                if result.available:
                    row[feature_id] = result.value
                    if feature_id not in built.available_features:
                        built.available_features.append(feature_id)
                    # 派生链回填：后续特征（如 peak_fluence）消费已算特征
                    input_name = FEATURE_TO_INPUT.get(feature_id)
                    if input_name and result.unit is not None:
                        inputs[input_name] = (result.value, result.unit)
                else:
                    if feature_id not in built.unavailable_features:
                        built.unavailable_features.append(feature_id)
            built.rows.append(row)
        for prop_name in DEVICE_PROPERTY_TO_INPUT:
            if prop_name not in device_properties:
                built.missing_device_properties.append(prop_name)
        return built
