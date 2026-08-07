from __future__ import annotations

from typing import Any

from ultrafast_knowledge.rag.metadata_filter import (
    enforce_purpose,
    metadata_for_hit,
    tier_for_hit,
)

PREFERRED_SECTIONS = {"results", "discussion", "conclusion"}

# 意图感知 section 加分（文档 §8 purpose-specific reranking）
INTENT_SECTION_BONUS = 0.12


def _intent_priority_sections(intent: str | None) -> tuple[str, ...]:
    if not intent:
        return PREFERRED_SECTIONS
    from ultrafast_knowledge.corpus.planner import section_priority_for

    try:
        return section_priority_for(intent)  # type: ignore[arg-type]
    except (KeyError, ValueError):
        return PREFERRED_SECTIONS


def rerank_hits(
    hits: list[dict[str, Any]],
    filters: dict[str, Any] | None = None,
    purpose: str = "literature_background",
    top_k: int = 8,
    intent: str | None = None,
) -> list[dict[str, Any]]:
    filters = filters or {}
    priority_sections = _intent_priority_sections(intent)
    output = []
    for hit in hits:
        if hit.get("review_status") == "rejected" or not enforce_purpose(hit, purpose):
            continue
        metadata = metadata_for_hit(hit)
        tiers = tier_for_hit(hit, filters) or {}
        if "known_mismatch" in tiers.values():
            continue
        score = float(hit.get("score") or 0.0)
        for key, bonus in (("material", 0.12), ("process_type", 0.1), ("component_type", 0.08)):
            if filters.get(key) and tiers.get(key) == "known_match":
                score += bonus
        section_type = hit.get("section_type") or metadata.get("section_type")
        if section_type in priority_sections:
            score += INTENT_SECTION_BONUS
        elif section_type in PREFERRED_SECTIONS:
            score += 0.07
        if metadata.get("doi"):
            score += 0.03
        if hit.get("page_start") and hit.get("page_end"):
            score += 0.02
        if purpose in (metadata.get("not_usable_for") or []):
            score -= 0.5
        output.append({**hit, "score": score})
    return sorted(output, key=lambda row: row["score"], reverse=True)[:top_k]
