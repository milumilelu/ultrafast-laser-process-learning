from __future__ import annotations

import json
from typing import Any

from ultrafast_shared.ontology import resolve

FILTER_FIELDS = {
    "scenario_id", "material", "material_grade", "process_type", "component_type",
    "laser_type", "evidence_level", "review_status", "section_type",
}

# Query filters keep their public, legacy-compatible names, while comparisons are
# always made against the semantic extraction fields when those fields exist.
CANONICAL_METADATA_FIELDS = {
    "material": "primary_material",
    "material_grade": "primary_material_grade",
    "process_type": "primary_process",
}

# 这些字段在比较前先做 Canonical ID 解析（碳纤维复合板 == CFRP == carbon fiber reinforced polymer）
CANONICAL_FILTER_KEYS = {"material", "process_type", "laser_type"}

REVIEWED_STATUSES = {
    "accepted", "approved", "reviewed", "accepted_to_rag",
    "accepted_as_literature_evidence",
}
TARGET_LEVEL_RANK = {
    "LEVEL_0_UNVERIFIED_CANDIDATE": 0,
    "LEVEL_1_RAG_BACKGROUND": 1,
    "LEVEL_2_LITERATURE_EVIDENCE": 2,
    "LEVEL_3_PROCESS_PRIOR": 3,
    "LEVEL_4_VALIDATED_RULE": 4,
    "LEVEL_5_BO_TRAINING_SAMPLE": 5,
}


def _canonical_for(key: str, value: Any) -> Any:
    if key not in CANONICAL_FILTER_KEYS or not isinstance(value, str):
        return value
    return resolve(key, value) or value


def metadata_for_hit(hit: dict[str, Any]) -> dict[str, Any]:
    metadata = hit.get("metadata")
    if isinstance(metadata, dict):
        value = dict(metadata)
    else:
        value = {}
        raw = hit.get("metadata_json")
        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    value = decoded
            except json.JSONDecodeError:
                pass
    return _project_canonical_metadata(value, hit)


def _decode_structured(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _canonical_metadata_value(
    metadata: dict[str, Any],
    hit: dict[str, Any],
    canonical_key: str,
) -> tuple[bool, Any]:
    if canonical_key in metadata and metadata[canonical_key] is not None:
        return True, _decode_structured(metadata[canonical_key])
    if canonical_key in hit and hit[canonical_key] is not None:
        return True, _decode_structured(hit[canonical_key])
    return False, None


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    if isinstance(value, dict):
        return str(next(iter(value.values()))) if value else ""
    return str(value) if value not in (None, "") else ""


def _project_canonical_metadata(
    metadata: dict[str, Any],
    hit: dict[str, Any],
) -> dict[str, Any]:
    """Expose legacy keys as projections without letting them override V2 metadata."""
    projected = dict(metadata)
    for legacy_key, canonical_key in CANONICAL_METADATA_FIELDS.items():
        present, value = _canonical_metadata_value(metadata, hit, canonical_key)
        if not present:
            continue
        projected[canonical_key] = value
        projected[legacy_key] = _first_text(value)
    return projected


def scope_value_for_hit(hit: dict[str, Any], key: str) -> Any:
    """Return the authoritative value used by a public scope-filter key."""
    metadata = metadata_for_hit(hit)
    canonical_key = CANONICAL_METADATA_FIELDS.get(key)
    if canonical_key and canonical_key in metadata:
        return metadata[canonical_key]
    return metadata.get(key, hit.get(key))


def matches_filters(hit: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    if not filters:
        return hit.get("review_status") != "rejected"
    metadata = metadata_for_hit(hit)
    if (hit.get("review_status") or metadata.get("review_status")) == "rejected":
        return False
    for key, expected in filters.items():
        if expected in (None, "", []):
            continue
        if key == "year_min":
            year = str(metadata.get("year") or hit.get("year") or "")
            if not year.isdigit() or int(year) < int(expected):
                return False
        elif key == "year_max":
            year = str(metadata.get("year") or hit.get("year") or "")
            if not year.isdigit() or int(year) > int(expected):
                return False
        elif key in FILTER_FIELDS:
            actual = scope_value_for_hit(hit, key)
            allowed = expected if isinstance(expected, list) else [expected]
            if not _value_matches(actual, allowed, key):
                return False
    return True


def _value_matches(actual: Any, allowed: list[Any], key: str) -> bool:
    if isinstance(actual, dict):
        actual_values = list(actual.values())
    else:
        actual_values = actual if isinstance(actual, list) else [actual]
    for item in actual_values:
        for expected in allowed:
            if _canonical_for(key, item) == _canonical_for(key, expected):
                return True
    return False


# ---- 三分协议：known_match / unknown / known_mismatch（P0-A）----
# known_match    → 保留并标记（下游 boost）
# unknown        → 保留（允许语义检索），标记 metadata_match_tiers[key]=unknown
# known_mismatch → 过滤（强惩罚）
THREE_WAY_KEYS = {"material", "process_type", "laser_type", "material_grade"}


def match_tier(actual: Any, expected: Any, key: str) -> str:
    """判定单个过滤字段的三分档位（key 必须是 THREE_WAY_KEYS）。"""
    if expected in (None, "", []):
        return "no_filter"
    if actual in (None, "", []):
        return "unknown"
    if isinstance(actual, dict):
        actual_values = list(actual.values())
    else:
        actual_values = actual if isinstance(actual, list) else [actual]
    allowed = expected if isinstance(expected, list) else [expected]
    for item in actual_values:
        for candidate in allowed:
            if _canonical_for(key, item) == _canonical_for(key, candidate):
                return "known_match"
    return "known_mismatch"


def tier_for_hit(hit: dict[str, Any], filters: dict[str, Any] | None) -> dict[str, str] | None:
    if not filters:
        return None
    metadata = metadata_for_hit(hit)
    tiers: dict[str, str] = {}
    for key, expected in filters.items():
        if expected in (None, "", []):
            continue
        if key in ("year_min", "year_max"):
            actual = metadata.get("year", hit.get("year"))
            actual_year = _parse_year(actual)
            expected_year = _parse_year(expected)
            if actual_year is None or expected_year is None:
                tiers[key] = "unknown"
            else:
                matched = actual_year >= expected_year if key == "year_min" else actual_year <= expected_year
                tiers[key] = "known_match" if matched else "known_mismatch"
            continue
        if key not in THREE_WAY_KEYS:
            tiers[key] = "known_match" if _value_matches(metadata.get(key, hit.get(key)), expected if isinstance(expected, list) else [expected], key) else "known_mismatch"
            continue
        tiers[key] = match_tier(scope_value_for_hit(hit, key), expected, key)
    return tiers


def _parse_year(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if 0 < year < 10000 else None


def matches_filters_three_way(hit: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    """三分语义：unknown 保留、mismatch 过滤；无过滤器恒真。"""
    if not filters:
        return hit.get("review_status") != "rejected"
    if (hit.get("review_status") or metadata_for_hit(hit).get("review_status")) == "rejected":
        return False
    tiers = tier_for_hit(hit, filters)
    if tiers is None:
        return True
    return "known_mismatch" not in tiers.values()


def apply_metadata_filters_three_way(
    hits: list[dict[str, Any]],
    filters: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """三分过滤：返回 (保留集, 档位计数)，并在命中上标注 metadata_match_tiers。"""
    counts = {"known_match": 0, "unknown": 0, "known_mismatch": 0, "no_filter": 0}
    kept: list[dict[str, Any]] = []
    for hit in hits:
        if (hit.get("review_status") or metadata_for_hit(hit).get("review_status")) == "rejected":
            continue
        tiers = tier_for_hit(hit, filters)
        if not tiers:
            counts["no_filter"] += 1
            kept.append(hit)
            continue
        if "known_mismatch" in tiers.values():
            counts["known_mismatch"] += 1
            continue
        hit["metadata_match_tiers"] = tiers
        counts["known_match" if "unknown" not in tiers.values() else "unknown"] += 1
        kept.append(hit)
    return kept, counts


def apply_metadata_filters(hits: list[dict[str, Any]], filters: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [hit for hit in hits if matches_filters(hit, filters)]


def evidence_waterfall(
    raw_hits: list[dict[str, Any]],
    filters: dict[str, Any] | None,
    purpose: str,
) -> dict[str, int]:
    """检索漏斗：raw → scope_match → reviewed → purpose_eligible → prior_eligible。

    每一层被过滤掉的证据都能说明原因（scope 不匹配 / 未审核 / 权限不足）。
    scope 层使用三分协议：known_mismatch 过滤、unknown 保留（P0-A）。
    """
    scope_matched, three_way_counts = apply_metadata_filters_three_way(raw_hits, filters)
    reviewed = [
        hit
        for hit in scope_matched
        if str(hit.get("review_status") or metadata_for_hit(hit).get("review_status") or "")
        in REVIEWED_STATUSES
    ]
    purpose_eligible = [hit for hit in reviewed if enforce_purpose(hit, purpose)]
    prior_eligible = [
        hit
        for hit in purpose_eligible
        if evidence_authority(hit) in {"process_prior", "validated_rule"}
        and enforce_purpose(hit, "bo")
    ]
    return {
        "raw_hits": len(raw_hits),
        "scope_match": len(scope_matched),
        "reviewed": len(reviewed),
        "purpose_eligible": len(purpose_eligible),
        "prior_eligible": len(prior_eligible),
        "three_way": three_way_counts,
    }


def enforce_purpose(hit: dict[str, Any], purpose: str) -> bool:
    metadata = metadata_for_hit(hit)
    normalized_purpose = purpose.strip().lower()
    not_usable = metadata.get("not_usable_for") or []
    if isinstance(not_usable, str):
        try:
            not_usable = json.loads(not_usable)
        except json.JSONDecodeError:
            not_usable = [not_usable]
    normalized_not_usable = {str(item).strip().lower() for item in not_usable}
    if normalized_purpose in normalized_not_usable:
        return False
    status = str(hit.get("review_status") or metadata.get("review_status") or "pending_review")
    evidence_level = str(hit.get("evidence_level") or metadata.get("evidence_level") or "")
    target_rank = TARGET_LEVEL_RANK.get(str(metadata.get("target_level") or ""), 0)
    reviewed = status in REVIEWED_STATUSES
    if normalized_purpose in {
        "parameter_recommendation", "rag_parameter_recommendation",
    }:
        return reviewed and (
            target_rank >= 2
            or evidence_level in {"literature_evidence", "process_prior", "validated_rule"}
        )
    if normalized_purpose in {
        "formal_process", "direct_parameter_recommendation", "bo", "bo_boundary",
    }:
        return reviewed and (
            target_rank >= 3 or evidence_level in {"process_prior", "validated_rule"}
        )
    return True


def evidence_authority(hit: dict[str, Any]) -> str:
    metadata = metadata_for_hit(hit)
    status = str(hit.get("review_status") or metadata.get("review_status") or "pending_review")
    evidence_level = str(hit.get("evidence_level") or metadata.get("evidence_level") or "")
    target_rank = TARGET_LEVEL_RANK.get(str(metadata.get("target_level") or ""), 0)
    if status not in REVIEWED_STATUSES:
        return "candidate"
    if target_rank >= 4 or evidence_level == "validated_rule":
        return "validated_rule"
    if target_rank >= 3 or evidence_level == "process_prior":
        return "process_prior"
    if target_rank >= 2 or evidence_level == "literature_evidence":
        return "reviewed_literature"
    return "reviewed_background"
