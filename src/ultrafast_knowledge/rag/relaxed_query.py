"""Relaxed material retrieval（三分协议，P0-A）。

RAG 的 material 过滤采用三分档位（metadata_filter.match_tier）：
- known_match    → 保留（boost 依据）
- unknown        → 保留（允许语义检索；metadata 无标签 ≠ 不相关）
- known_mismatch → 过滤（强惩罚）

本模块在三分过滤之上做最后一级兜底：purpose_eligible 命中为 0 时，
移除 material 过滤重查（语义查询文本仍含材料词），结果携带
retrieval_metadata.three_way（档位统计）与 relaxed 标记。
放宽检索 ≠ 放宽治理：来源适用性仍由下游 E2P applicability 逐维判定。
"""

from __future__ import annotations

from typing import Any

from ultrafast_knowledge.rag.metadata_filter import enforce_purpose, tier_for_hit
from ultrafast_knowledge.rag.query_service import query_rag


def _purpose_eligible_count(pack: dict[str, Any], purpose: str) -> int:
    return sum(
        1
        for hit in pack.get("hits") or []
        if enforce_purpose(hit, purpose)
    )


def _three_way_stats(hits: list[dict[str, Any]], filters: dict[str, Any]) -> dict[str, int]:
    counts = {"known_match": 0, "unknown": 0, "known_mismatch": 0, "no_filter": 0}
    for hit in hits:
        tiers = tier_for_hit(hit, filters)
        if not tiers:
            counts["no_filter"] += 1
            continue
        if "known_mismatch" in tiers.values():
            counts["known_mismatch"] += 1
            continue
        counts["known_match" if "unknown" not in tiers.values() else "unknown"] += 1
    return counts


def _pre_filter_stats(pack: dict[str, Any], filters: dict[str, Any]) -> dict[str, int]:
    waterfall = (pack.get("retrieval_metadata") or {}).get("evidence_waterfall") or {}
    counts = waterfall.get("three_way")
    if isinstance(counts, dict):
        return {
            key: int(counts.get(key, 0))
            for key in ("known_match", "unknown", "known_mismatch", "no_filter")
        }
    return _three_way_stats(pack.get("hits") or [], filters)


def query_rag_relaxed(
    request: dict[str, Any],
    *,
    material_key: str = "material",
) -> dict[str, Any]:
    """material 三分过滤 + 最终放宽兜底的检索入口。"""
    purpose = request.get("purpose", "literature_background")
    filters = dict(request.get("filters") or {})
    material = filters.get(material_key)
    strict = query_rag({**request, "filters": filters})
    tier_stats = _pre_filter_stats(strict, filters)
    metadata = dict(strict.get("retrieval_metadata") or {})
    metadata["three_way"] = tier_stats
    if material and _purpose_eligible_count(strict, purpose) == 0:
        relaxed_filters = {
            key: value for key, value in filters.items() if key != material_key
        }
        relaxed = query_rag({**request, "filters": relaxed_filters})
        metadata = dict(relaxed.get("retrieval_metadata") or {})
        metadata["three_way"] = tier_stats
        metadata["relaxed"] = {
            "material_filter_relaxed": True,
            "strict_material": material,
            "reason": "no purpose-eligible hits under three-way scope filter; material filter dropped",
            "three_way_tiers": tier_stats,
        }
        relaxed["retrieval_metadata"] = metadata
        return relaxed
    metadata["relaxed"] = {"material_filter_relaxed": False, "three_way_tiers": tier_stats}
    strict["retrieval_metadata"] = metadata
    return strict
