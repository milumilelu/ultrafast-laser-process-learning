"""Canonical Ontology: 用户/UI/Agent 的自由文本 → Canonical ID。

系统内部不得使用自由文本作为正式实体标识：

    碳纤维复合板 / CFRP / carbon fiber reinforced polymer / 碳纤维复合材料
    → material_id = CFRP

Web UI 选择后的 TaskContext 本身就是 RAG / E2P / 数据库 的 TaskScope，
而不是让 Agent 再从自然语言重新识别一遍。
"""

from __future__ import annotations

import re
from typing import Any

CANONICAL_MATERIALS = (
    "Aluminum",
    "CFRP",
    "Copper",
    "Diamond",
    "Epoxy",
    "FusedSilica",
    "Glass",
    "GlassCeramic",
    "NickelSuperalloy",
    "Sapphire",
    "SiC",
    "SiCp/Al",
    "Silicon",
    "Steel",
    "TBC",
    "Ti6Al4V",
    "ZrO2",
)

CANONICAL_LASER_TYPES = ("fs", "ps")

CANONICAL_PROCESS_TYPES = (
    "milling",
    "cutting",
    "rectangular_groove",
    "circular_hole",
    "single_line",
    "custom",
    "surface_roughening",
    "surface_texturing",
)

CANONICAL_GEOMETRY_TYPES = (
    "rectangular_groove",
    "circular_hole",
    "single_line",
    "custom",
    "surface_texture",
)

CANONICAL_TARGETS = (
    "depth_um",
    "roughness_um",
    "Sa_um",
    "Ra_um",
    "removal_rate_um3_s",
)

MATERIAL_ALIASES: dict[str, tuple[str, ...]] = {
    "SiCp/Al": (
        "alsic",
        "al sic",
        "al-sic",
        "sicp/al",
        "sicp al",
        "sic particle reinforced aluminum",
        "sic particle reinforced aluminium",
        "sic reinforced aluminum",
        "aluminium silicon carbide",
        "aluminum silicon carbide",
        "铝碳化硅",
        "铝碳化硅复合材料",
        "碳化硅颗粒增强铝基复合材料",
        "碳化硅颗粒增强铝",
    ),
    "Aluminum": (
        "aluminum",
        "aluminium",
        "al alloy",
        "aluminum alloy",
        "aluminium alloy",
        "aa2024",
        "aa6061",
        "铝合金",
        "铝",
    ),
    "CFRP": (
        "cfrp",
        "carbon fiber reinforced polymer",
        "carbon fibre reinforced polymer",
        "carbon fiber reinforced plastic",
        "carbon fibre reinforced plastic",
        "carbon fiber composite",
        "carbon fibre composite",
        "t300",
        "碳纤维复合材料",
        "碳纤维复合板",
        "碳纤维增强复合材料",
        "碳纤维增强塑料",
        "碳纤维",
    ),
    "Copper": ("copper", "cu", "cu sheet", "铜", "无氧铜"),
    "Diamond": ("diamond", "金刚石", "金刚石材料", "单晶金刚石", "cvd diamond", "polycrystalline diamond"),
    "Epoxy": ("epoxy", "epoxy resin", "epoxy adhesive", "poss", "环氧", "环氧树脂", "环氧胶"),
    "FusedSilica": (
        "fused silica",
        "fused quartz",
        "quartz glass",
        "sio2 glass",
        "silicon dioxide",
        "silica",
        "sio2",
        "熔融石英",
        "石英玻璃",
        "熔石英",
        "二氧化硅",
    ),
    "Glass": (
        "glass",
        "borosilicate glass",
        "boro-aluminosilicate glass",
        "boroaluminosilicate glass",
        "aluminosilicate glass",
        "soda-lime glass",
        "soda lime glass",
        "ultra-thin glass",
        "thin glass",
        "cover glass",
        "chemically strengthened glass",
        "glass wafer",
        "glass substrate",
        "glass sheet",
        "玻璃",
        "玻璃基板",
        "玻璃晶圆",
        "玻璃盖板",
        "超薄玻璃",
        "硼硅酸盐玻璃",
        "化学强化玻璃",
    ),
    "GlassCeramic": (
        "glass ceramic",
        "glass-ceramic",
        "glassceramic",
        "microcrystalline glass",
        "las glass-ceramic",
        "微晶玻璃",
        "微晶玻璃陶瓷",
    ),
    "NickelSuperalloy": (
        "nickel based superalloy",
        "nickel-based superalloy",
        "nickel superalloy",
        "nickel alloy",
        "nickel-base superalloy",
        "inconel",
        "cmsx",
        "gh4169",
        "ni-based superalloy",
        "镍基高温合金",
        "镍基合金",
        "高温合金",
    ),
    "Sapphire": ("sapphire", "al2o3", "alumina", "蓝宝石", "氧化铝", "氧化铝陶瓷"),
    "SiC": (
        "sic",
        "silicon carbide",
        "sicp",
        "sic particle",
        "sic composite",
        "sic composites",
        "碳化硅",
        "碳化硅陶瓷",
        "碳化硅材料",
        "碳化硅复合材料",
    ),
    "Silicon": ("silicon", "si wafer", "si substrate", "silicon wafer", "单晶硅", "硅片", "硅基板"),
    "Steel": ("steel", "stainless steel", "steel plate", "steel structure", "q345b", "x100", "钢", "钢板", "不锈钢"),
    "TBC": (
        "thermal barrier coating",
        "thermal barrier coated",
        "thermal barrier ceramic",
        "tbc",
        "热障涂层",
        "陶瓷热障涂层",
    ),
    "Ti6Al4V": ("ti6al4v", "ti-6al-4v", "tc4", "titanium alloy", "titanium", "钛合金", "钛合金tc4", "钛"),
    "ZrO2": (
        "zro2",
        "zirconia",
        "zirconium dioxide",
        "tbc ysz",
        "tbc_ysz",
        "ysz",
        "yttria stabilized zirconia",
        "yttria-stabilized zirconia",
        "氧化锆",
        "氧化锆陶瓷",
        "氧化钇稳定氧化锆",
    ),
}

LASER_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "fs": ("fs", "femtosecond", "femtosecond laser", "飞秒", "飞秒激光", "超快飞秒"),
    "ps": ("ps", "picosecond", "picosecond laser", "皮秒", "皮秒激光"),
}

PROCESS_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "milling": ("milling", "铣削", "面铣", "平面铣削", "微铣削"),
    "cutting": ("cutting", "切割", "激光切割", "划切", "dicing"),
    "rectangular_groove": ("rectangular groove", "rectangular_groove", "groove", "矩形槽", "矩形沟槽", "沟槽加工", "微槽"),
    "circular_hole": ("circular hole", "circular_hole", "round hole", "hole", "圆孔", "圆孔加工", "微孔", "盲孔"),
    "single_line": ("single line", "single_line", "line scribing", "scribing", "单线", "单线刻划", "划线"),
    "custom": ("custom", "自定义", "自定义加工"),
    "surface_roughening": ("surface roughening", "surface_roughening", "roughening", "表面毛化", "表面粗化"),
    "surface_texturing": ("surface texturing", "surface_texturing", "texturing", "表面织构", "表面微织构"),
}

GEOMETRY_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "rectangular_groove": ("rectangular groove", "rectangular_groove", "groove", "矩形槽", "矩形沟槽", "沟槽"),
    "circular_hole": ("circular hole", "circular_hole", "round hole", "圆孔", "孔"),
    "single_line": ("single line", "single_line", "单线", "线"),
    "custom": ("custom", "自定义"),
    "surface_texture": ("surface texture", "surface_texture", "表面织构", "表面形貌"),
}

TARGET_ALIASES: dict[str, tuple[str, ...]] = {
    "depth_um": ("depth", "depth_um", "加工深度", "深度", "槽深", "孔深"),
    "roughness_um": (
        "roughness",
        "surface roughness",
        "roughness_um",
        "sa",
        "sa_um",
        "ra",
        "ra_um",
        "表面粗糙度",
        "粗糙度",
        "表面质量",
    ),
    "Sa_um": ("sa", "sa_um", "surface roughness sa"),
    "Ra_um": ("ra", "ra_um", "surface roughness ra"),
    "removal_rate_um3_s": ("removal rate", "removal_rate_um3_s", "去除率", "材料去除率"),
}


def _normalize(value: str) -> str:
    return re.sub(r"[\s\-_/]+", " ", value.strip().lower())


def _build_index(alias_map: dict[str, tuple[str, ...]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for canonical, aliases in alias_map.items():
        index[_normalize(canonical)] = canonical
        for alias in aliases:
            index[_normalize(alias)] = canonical
    return index


_MATERIAL_INDEX = _build_index(MATERIAL_ALIASES)
_LASER_INDEX = _build_index(LASER_TYPE_ALIASES)
_PROCESS_INDEX = _build_index(PROCESS_TYPE_ALIASES)
_GEOMETRY_INDEX = _build_index(GEOMETRY_TYPE_ALIASES)
_TARGET_INDEX = _build_index(TARGET_ALIASES)

_KIND_INDEXES = {
    "material": _MATERIAL_INDEX,
    "laser_type": _LASER_INDEX,
    "process_type": _PROCESS_INDEX,
    "geometry_type": _GEOMETRY_INDEX,
    "target": _TARGET_INDEX,
}


def resolve(kind: str, value: str | None) -> str | None:
    """把自由文本解析为 Canonical ID；无法解析返回 None（不猜测）。"""
    if value is None:
        return None
    index = _KIND_INDEXES.get(kind)
    if index is None:
        return value if _looks_canonical(value) else None
    return index.get(_normalize(value))


def _looks_canonical(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", value))


def resolve_material(value: str | None) -> str | None:
    return resolve("material", value)


def resolve_process_type(value: str | None) -> str | None:
    return resolve("process_type", value)


def resolve_laser_type(value: str | None) -> str | None:
    return resolve("laser_type", value)


def resolve_target(value: str | None) -> str | None:
    return resolve("target", value)


def canonical_task_scope(
    *,
    material: str | None = None,
    material_grade: str | None = None,
    laser_type: str | None = None,
    process_type: str | None = None,
    geometry_type: str | None = None,
    equipment_id: str | None = None,
    target_metric: str | None = None,
) -> dict[str, str | None]:
    """把任意来源的任务描述规范化为 Canonical TaskScope。

    material_id 等正式字段只接受 canonical ID；无法解析的输入保留原值但标记
    normalized=False，由调用方决定拒绝或进入人工澄清。
    """
    scope: dict[str, str | None] = {}
    normalized: dict[str, bool] = {}
    mapping = {
        "material_id": ("material", material),
        "laser_type": ("laser_type", laser_type),
        "process_type": ("process_type", process_type),
        "geometry_type": ("geometry_type", geometry_type),
        "target_metric": ("target", target_metric),
    }
    for key, (kind, raw) in mapping.items():
        canonical = resolve(kind, raw)
        scope[key] = canonical or raw
        if raw is not None:
            normalized[kind] = canonical is not None
    scope["material_grade"] = material_grade
    scope["equipment_id"] = equipment_id
    return {**scope, "normalized": all(normalized.values()) if normalized else True}


def normalize_scope_dict(scope: dict[str, Any]) -> dict[str, Any]:
    """就地规范化一个 scope dict（RAG 查询 / 文档元数据共用）。"""
    result = dict(scope)
    for key in ("material", "process_type", "laser_type", "geometry_type", "target"):
        if result.get(key):
            result[key] = resolve(key, str(result[key])) or result[key]
    return result
