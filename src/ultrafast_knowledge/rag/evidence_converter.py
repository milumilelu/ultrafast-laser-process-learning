"""RAG → EvidenceClaim → Topic2 Evidence[] 转换链（唯一转换入口）。

RAG 负责发现证据（EvidencePack），本转换器用确定性抽取把文献中的
数值观测编译为待审核 Topic2 Evidence candidate[]。来源文献已审核不等于
新生成的数值/区间 claim 已获批准；candidate 必须另行治理后才能进入 E2P/BO。
LLM 不参与数值编译；参数名/单位/范围均来自受控抽取器。
"""

from __future__ import annotations

from typing import Any

from ultrafast_knowledge.rag.metadata_filter import enforce_purpose
from ultrafast_knowledge.rag.parameter_recommendation import (
    PARAMETER_SPECS,
    _source_ref,
    _text_observations,
)
from ultrafast_knowledge.rag.relaxed_query import query_rag_relaxed

# Agent 抽取参数名 → Topic2 核心参数名（含单位换算）
PARAMETER_MAPPING = {
    "pulse_width_fs": ("pulse_width_ps", 1.0 / 1000.0),
    "laser_power_W": ("laser_power_W", 1.0),
    "frequency_kHz": ("frequency_kHz", 1.0),
    "scan_speed_mm_s": ("scan_speed_mm_s", 1.0),
    "hatch_spacing_um": ("hatch_spacing_um", 1.0),
    "passes": ("passes", 1.0),
}

# Topic2 Evidence 契约只接受 5 个核心工艺参数（与实验库列一致）。
# RAG 检索到的其他参数（如 laser_power_W）不进入 Evidence[]，
# 避免 E2P 编译阶段契约拒绝（extra/unsupported parameter）。
TOPIC2_CORE_PARAMETERS = frozenset(
    {"pulse_width_ps", "frequency_kHz", "hatch_spacing_um", "passes", "scan_speed_mm_s"}
)

SUPPORTED_TARGETS = {"depth_um", "roughness_um"}

# 工艺参数导向的检索词：没有这些词时，"CFRP depth" 会命中土木工程 CFRP
# 加固混凝土论文（effective depth of steel reinforcement），而非激光加工文献。
LASER_PROCESS_TERMS = (
    "laser machining ablation scanning femtosecond picosecond pulse "
    "repetition rate frequency power hatch spacing scan speed passes depth"
)

_LASER_TYPE_TERM = {"fs": "femtosecond laser", "ps": "picosecond laser"}


def _build_evidence_query(task_scope: dict[str, Any], query: str | None) -> str:
    if query:
        return query
    laser = _LASER_TYPE_TERM.get(str(task_scope.get("laser_type") or "").lower())
    parts = [
        task_scope.get("material"),
        laser,
        "laser machining ablation",
        task_scope.get("process_type") or task_scope.get("geometry_type"),
        task_scope.get("target"),
        LASER_PROCESS_TERMS,
    ]
    return " ".join(str(item) for item in parts if item)


def rag_evidence_to_topic2(
    task_scope: dict[str, Any],
    query: str | None = None,
    top_k: int = 20,
    include_unreviewed_candidates: bool = False,
    auto_approve: bool = False,
) -> dict[str, Any]:
    """按任务 scope 检索 RAG，抽取参数观测并生成待审核 Evidence[]。

    auto_approve=True 为流程验证期约定：所有 RAG 候选标记 approved 直接进入
    E2P/BO（绕过审核）；生产与真实治理流程必须保持 False。
    """
    material = task_scope.get("material")
    target = task_scope.get("target")
    if target not in SUPPORTED_TARGETS:
        raise ValueError(f"unsupported target: {target}")
    filters: dict[str, Any] = {}
    if material:
        filters["material"] = material
    # 工艺/几何只进入查询文本，不做硬过滤：文献语料的 process 元数据覆盖不全，
    # 语义匹配由查询完成，scope 适用性由下游 E2P compile 逐维判定。
    # material 过滤分级放宽（语料标签不一致时自动去掉 material 过滤重查）。
    pack = query_rag_relaxed(
        {
            "query": _build_evidence_query(task_scope, query),
            "filters": filters,
            "top_k": top_k,
            "purpose": "parameter_recommendation",
            "index_name": "literature_default",
        }
    )
    hits = list(pack.get("hits") or [])
    reviewed_hits: list[dict[str, Any]] = []
    unreviewed_hits: list[dict[str, Any]] = []
    for hit in hits:
        if enforce_purpose(hit, "parameter_recommendation"):
            reviewed_hits.append(hit)
        elif include_unreviewed_candidates:
            unreviewed_hits.append(hit)

    # 同一论文的重复 chunk（同内容）只保留一条，避免挤占候选名额
    seen_content: set[str] = set()
    ordered_candidates: list[dict[str, Any]] = []
    for hit in [*reviewed_hits, *unreviewed_hits]:
        content = str(hit.get("content") or "").strip()
        if not content or content in seen_content:
            continue
        seen_content.add(content)
        ordered_candidates.append(hit)

    evidence: list[dict[str, Any]] = []
    extraction: dict[str, dict[str, Any]] = {}
    for hit in ordered_candidates:
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        content = str(hit.get("content") or "")
        for agent_parameter, (topic2_parameter, factor) in PARAMETER_MAPPING.items():
            spec = PARAMETER_SPECS.get(agent_parameter)
            if not spec:
                continue
            observations = _text_observations(content, agent_parameter, _source_ref(hit))
            structured = metadata.get("parameter")
            if isinstance(structured, dict) and agent_parameter in structured:
                observations.extend(
                    _text_observations(
                        f"{spec['aliases'][0]} {structured[agent_parameter]}",
                        agent_parameter,
                        _source_ref(hit),
                    )
                )
            for observation in observations:
                value = observation.get("value")
                if not isinstance(value, (int, float)):
                    continue
                bucket = extraction.setdefault(
                    topic2_parameter,
                    {"values": [], "source_refs": [], "unreviewed": False},
                )
                bucket["values"].append(float(value) * float(factor))
                bucket["source_refs"].append(str(observation["source_ref"]))
                if hit in unreviewed_hits:
                    bucket["unreviewed"] = True

    for topic2_parameter, bucket in extraction.items():
        if not bucket["values"]:
            continue
        if topic2_parameter not in TOPIC2_CORE_PARAMETERS:
            # 非核心参数（如 laser_power_W）不在 Topic2 Evidence 契约内，
            # 不生成候选，避免 E2P 编译阶段契约拒绝。
            continue
        lower, upper = min(bucket["values"]), max(bucket["values"])
        derived_single = False
        if lower == upper:
            # 单一观测：按 ±10% 生成显式标记的推导区间（可追溯，不冒充实测范围）
            if topic2_parameter == "passes":
                lower, upper = max(1, int(lower) - 1), int(upper) + 1
            else:
                lower, upper = lower * 0.9, upper * 1.1
            derived_single = True
        sources = list(dict.fromkeys(bucket["source_refs"]))
        paper, _chunk = _paper_chunk_from_ref(sources[0])
        claim: dict[str, Any] = {"lower": lower, "upper": upper}
        if derived_single:
            claim["derived"] = True
            claim["derived_basis"] = "single_observation_plus_minus_10_percent"
        evidence.append(
            {
                "evidence_id": f"RAG-{paper[-12:]}-{topic2_parameter}",
                "source_type": "literature",
                "claim_type": "range_preference",
                "parameter": topic2_parameter,
                "target": target,
                "claim": claim,
                "scope": {
                    "material": task_scope.get("material"),
                    "laser_type": task_scope.get("laser_type"),
                    "geometry_type": task_scope.get("geometry_type"),
                    "equipment_id": task_scope.get("equipment_id"),
                    "target": target,
                },
                "provenance": {
                    "source_id": paper,
                    "review_id": None,
                },
                # 转换器默认只产 candidate。即使来源 chunk 已审核，聚合/单位换算/
                # 单点扩区间均形成了新 claim，不能继承来源的 approval。
                # auto_approve=True 为流程验证期约定：全部标记 approved 放行。
                "review_status": "approved" if auto_approve else "pending",
                "version": "1",
            }
        )

    return {
        "evidence": evidence,
        "retrieved_hits": len(hits),
        "reviewed_hits": len(reviewed_hits),
        "unreviewed_hits_used": len(unreviewed_hits),
        "evidence_status": pack.get("evidence_status"),
        "auto_approved": bool(auto_approve),
        "waterfall": pack.get("retrieval_metadata", {}).get("evidence_waterfall", {}),
    }


def _paper_chunk_from_ref(source_ref: str) -> tuple[str, str]:
    paper = source_ref.split(":", 1)[0] if ":" in source_ref else source_ref
    chunk = source_ref.split(":")[1] if source_ref.count(":") >= 1 else "unknown"
    return paper, chunk
