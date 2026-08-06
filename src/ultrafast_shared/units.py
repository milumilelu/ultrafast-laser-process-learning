"""单位统一（Deterministic Unit Normalization）。

单位换算由确定性代码完成，禁止依赖 LLM（文档 §18.2）：
    W / kHz·MHz→Hz / fs·ps→s / μm·mm→m / J/cm² / mm/s
"""

from __future__ import annotations

from dataclasses import dataclass

# 目标单位（规范单位制）
NORM_UNIT_POWER = "W"
NORM_UNIT_FREQUENCY = "Hz"
NORM_UNIT_TIME = "s"
NORM_UNIT_LENGTH = "m"
NORM_UNIT_FLUENCE = "J/m2"
NORM_UNIT_SPEED = "m/s"
NORM_UNIT_ENERGY = "J"

# 换算表：源单位 -> (规范单位, 系数)
_FACTORS: dict[str, tuple[str, float]] = {
    # 功率
    "w": (NORM_UNIT_POWER, 1.0),
    "mw": (NORM_UNIT_POWER, 1e-3),
    "kw": (NORM_UNIT_POWER, 1e3),
    # 频率
    "hz": (NORM_UNIT_FREQUENCY, 1.0),
    "khz": (NORM_UNIT_FREQUENCY, 1e3),
    "mhz": (NORM_UNIT_FREQUENCY, 1e6),
    # 时间
    "s": (NORM_UNIT_TIME, 1.0),
    "ms": (NORM_UNIT_TIME, 1e-3),
    "us": (NORM_UNIT_TIME, 1e-6),
    "ns": (NORM_UNIT_TIME, 1e-9),
    "ps": (NORM_UNIT_TIME, 1e-12),
    "fs": (NORM_UNIT_TIME, 1e-15),
    # 长度
    "m": (NORM_UNIT_LENGTH, 1.0),
    "mm": (NORM_UNIT_LENGTH, 1e-3),
    "um": (NORM_UNIT_LENGTH, 1e-6),
    "μm": (NORM_UNIT_LENGTH, 1e-6),
    "µm": (NORM_UNIT_LENGTH, 1e-6),
    "nm": (NORM_UNIT_LENGTH, 1e-9),
    # 能量
    "j": (NORM_UNIT_ENERGY, 1.0),
    "mj": (NORM_UNIT_ENERGY, 1e-3),
    "uj": (NORM_UNIT_ENERGY, 1e-6),
    "μj": (NORM_UNIT_ENERGY, 1e-6),
    "µj": (NORM_UNIT_ENERGY, 1e-6),
    # 通量 / 注量
    "j/m2": (NORM_UNIT_FLUENCE, 1.0),
    "j/cm2": (NORM_UNIT_FLUENCE, 1e4),
    "mj/cm2": (NORM_UNIT_FLUENCE, 1e1),
    # 速度
    "m/s": (NORM_UNIT_SPEED, 1.0),
    "mm/s": (NORM_UNIT_SPEED, 1e-3),
    "m/s²": (NORM_UNIT_SPEED, 1.0),
    "mm/min": (NORM_UNIT_SPEED, 1e-3 / 60.0),
    # 温度扩散系数（thermal diffusivity）
    "m2/s": ("m2/s", 1.0),
    "mm2/s": ("m2/s", 1e-6),
    "cm2/s": ("m2/s", 1e-4),
}


def normalize_unit(unit: str | None) -> tuple[str | None, float | None]:
    """返回 (规范单位, 换算系数)；系数 None 表示单位无法识别/不可换算。"""
    if unit is None:
        return None, None
    key = str(unit).strip().lower().replace(" ", "")
    found = _FACTORS.get(key)
    if found is None:
        return None, None
    return found


def convert(value: float, from_unit: str | None, to_unit: str | None = None) -> float | None:
    """把 value 从 from_unit 换算到规范单位（或 to_unit）。不可换算返回 None。"""
    normalized, factor = normalize_unit(from_unit)
    if factor is None:
        return None
    converted = float(value) * factor
    if to_unit is None or to_unit == normalized:
        return converted
    target_norm, target_factor = normalize_unit(to_unit)
    if target_factor is None:
        return None
    return converted / target_factor


@dataclass(frozen=True, slots=True)
class UnitConverted:
    value: float
    unit: str

    def __bool__(self) -> bool:
        return True
