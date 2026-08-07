"""Scientific Retrieval Planner（文档 §5）。

根据 TaskScope 自动生成多类检索任务（不是单个自然语言 query），
每个 RetrievalIntent 有独立的查询扩展与 section 优先级。
"""

from __future__ import annotations

from typing import Any

from ultrafast_knowledge.corpus.schemas import RetrievalIntent

# 文档 §5.1 示例：SiC / fs / 1030nm / rectangular groove / depth+Sa
# 应自动形成 A 直接工艺关系 / B 材料与阈值 / C 工艺机理 / D 设备光学 / E 公式

_LASER_TERM = {"fs": "femtosecond", "ps": "picosecond"}

# 意图 → 查询模板关键词（query expansion，与语料语义匹配）
_INTENT_QUERY_TERMS: dict[RetrievalIntent, tuple[str, ...]] = {
    RetrievalIntent.PARAMETER_EFFECT: (
        "effect influence dependence relation depth roughness scan speed frequency power",
    ),
    RetrievalIntent.PARAMETER_CONDITION: (
        "experimental conditions parameters settings used setup table",
    ),
    RetrievalIntent.MATERIAL_PROPERTY: (
        "material property thermal conductivity diffusivity absorptance heat capacity",
    ),
    RetrievalIntent.OPTICAL_PROPERTY: (
        "optical property absorption penetration depth bandgap refractive index",
    ),
    RetrievalIntent.THRESHOLD: (
        "ablation threshold fluence incubation coefficient single pulse",
    ),
    RetrievalIntent.FORMULA: (
        "formula equation fluence overlap pulses per spot peak fluence calculation",
    ),
    RetrievalIntent.MECHANISM: (
        "mechanism heat accumulation incubation multiphoton absorption plasma shielding",
    ),
    RetrievalIntent.INTERACTION: (
        "interaction wavelength pulse duration material laser parameter interplay",
    ),
    RetrievalIntent.REPORTED_OPTIMUM: (
        "optimum optimal best parameters reported maximum quality minimum roughness",
    ),
    RetrievalIntent.HISTORICAL_ANALOG: (
        "similar material process analog comparable parameter window",
    ),
}

# 意图 → section 优先级（文档 §8：purpose-specific reranking）
_INTENT_SECTION_PRIORITY: dict[RetrievalIntent, tuple[str, ...]] = {
    RetrievalIntent.PARAMETER_EFFECT: ("results", "discussion", "conclusion"),
    RetrievalIntent.PARAMETER_CONDITION: ("methods", "experimental_setup", "table", "figure_caption"),
    RetrievalIntent.MATERIAL_PROPERTY: ("table", "methods", "results"),
    RetrievalIntent.OPTICAL_PROPERTY: ("table", "methods", "results"),
    RetrievalIntent.THRESHOLD: ("results", "table", "methods"),
    RetrievalIntent.FORMULA: ("methods", "equation", "introduction"),
    RetrievalIntent.MECHANISM: ("introduction", "discussion", "methods"),
    RetrievalIntent.INTERACTION: ("discussion", "results"),
    RetrievalIntent.REPORTED_OPTIMUM: ("results", "table", "figure_caption", "discussion"),
    RetrievalIntent.HISTORICAL_ANALOG: ("results", "table", "methods"),
}

# in-paper 上下文扩展：除 priority 之外，每个 intent 额外带上的 section 类型
_INTENT_CONTEXT_SECTIONS: dict[RetrievalIntent, tuple[str, ...]] = {
    RetrievalIntent.PARAMETER_EFFECT: ("experimental_setup", "table"),
    RetrievalIntent.PARAMETER_CONDITION: ("results", "figure_caption", "table"),
    RetrievalIntent.MATERIAL_PROPERTY: ("experimental_setup",),
    RetrievalIntent.THRESHOLD: ("methods", "experimental_setup"),
    RetrievalIntent.FORMULA: ("results", "table"),
    RetrievalIntent.MECHANISM: ("results", "conclusion"),
    RetrievalIntent.REPORTED_OPTIMUM: ("abstract", "conclusion"),
}


def default_intents(task_scope: dict[str, Any]) -> list[RetrievalIntent]:
    """按 TaskScope 生成默认意图集（文档 §5.1 A-E）。"""
    intents = [
        RetrievalIntent.PARAMETER_EFFECT,
        RetrievalIntent.PARAMETER_CONDITION,
    ]
    material = task_scope.get("material")
    if material:
        intents.append(RetrievalIntent.MATERIAL_PROPERTY)
        intents.append(RetrievalIntent.THRESHOLD)
    intents.append(RetrievalIntent.MECHANISM)
    intents.append(RetrievalIntent.FORMULA)
    intents.append(RetrievalIntent.REPORTED_OPTIMUM)
    return list(dict.fromkeys(intents))


def build_queries(
    task_scope: dict[str, Any], intents: list[RetrievalIntent] | None = None
) -> dict[RetrievalIntent, str]:
    """意图 → 检索查询（含参数词注入与 material/laser 上下文）。"""
    intents = intents or default_intents(task_scope)
    material = task_scope.get("material")
    laser = _LASER_TERM.get(str(task_scope.get("laser_type") or "").lower(), "ultrafast")
    process = task_scope.get("process_type") or task_scope.get("geometry_type")
    target = task_scope.get("target")
    base_parts = [str(item) for item in (material, laser, process, target) if item]
    queries: dict[RetrievalIntent, str] = {}
    for intent in intents:
        terms = _INTENT_QUERY_TERMS.get(intent, ())
        parts = [*base_parts, *terms]
        queries[intent] = " ".join(str(item) for item in parts if item)
    return queries


def section_priority_for(intent: RetrievalIntent) -> tuple[str, ...]:
    return _INTENT_SECTION_PRIORITY.get(intent, ("results", "discussion"))


def context_sections_for(intent: RetrievalIntent) -> tuple[str, ...]:
    return _INTENT_CONTEXT_SECTIONS.get(intent, ("results", "methods", "table"))
