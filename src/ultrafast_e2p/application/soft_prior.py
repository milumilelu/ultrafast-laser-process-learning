"""Smooth soft search prior: 文献只产生搜索偏好 π_E(x)，绝不删除合法机器空间。

与 BOPrO / πBO 思路一致：先验可以引导先探索哪些区域，
先验不完全正确时算法仍能恢复 —— 先验区间不是不可突破的墙。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from ultrafast_e2p.domain.evidence import PREFERRED_RANGE_CLAIM_TYPES, EvidenceBundle

PRIOR_SPEC_VERSION = "e2p-soft-prior-v1"
STRENGTH_WEIGHT = {"strong": 1.0, "medium": 0.5, "weak": 0.25}

PREFERRED_RANGE_ROLES = ("recommended_range", "reported_optimum", "observed_relation")


def compile_prior_spec(bundle: EvidenceBundle) -> dict[str, Any]:
    applicability = {item["claim_id"]: item for item in bundle.applicability_results}
    preferences = []
    for claim in bundle.accepted:
        if claim.claim_type not in PREFERRED_RANGE_CLAIM_TYPES or not claim.parameter:
            continue
        lower = claim.value.get("lower")
        upper = claim.value.get("upper")
        if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
            continue
        if lower >= upper:
            continue
        if claim.semantic_role not in PREFERRED_RANGE_ROLES:
            continue
        level = str(applicability.get(claim.claim_id, {}).get("transfer_class", "weak"))
        weight = STRENGTH_WEIGHT.get(level, 0.25)
        preferences.append(
            {
                "claim_id": claim.claim_id,
                "parameter": claim.parameter,
                "lower": float(lower),
                "upper": float(upper),
                "strength": level,
                "fixed_weight": weight,
                "semantic_role": claim.semantic_role,
            }
        )
    return {
        "prior_spec_version": PRIOR_SPEC_VERSION,
        "range_preferences": preferences,
    }


def _smooth_range_penalty(
    values: np.ndarray, lower: float, upper: float, scale: float | None = None
) -> np.ndarray:
    # 惩罚距离相对"参数空间的机器范围"归一化（scale 提供），而不是 prior
    # 区间自身宽度：窄 prior（5 kHz）除以自身宽度会在远处产生数百量级的
    # 二次惩罚，使归一化后绝大多数候选的 prior 分数坍缩为 0，prior 退化为
    # "只惩罚最远点"。
    width = max(float(scale) if scale else (upper - lower), np.finfo(float).eps)
    below = np.maximum(lower - values, 0) / width
    above = np.maximum(values - upper, 0) / width
    return -(below**2 + above**2)


def log_prior_score(
    candidates: Mapping[str, np.ndarray],
    prior_spec: dict[str, Any],
    scale_by: Mapping[str, tuple[float, float]] | None = None,
) -> np.ndarray:
    first = next(iter(candidates.values()))
    scores = np.zeros_like(np.asarray(first, dtype=float))
    for preference in prior_spec.get("range_preferences", []):
        values = np.asarray(candidates[preference["parameter"]], dtype=float)
        scale = None
        if scale_by and preference["parameter"] in scale_by:
            lower, upper = scale_by[preference["parameter"]]
            scale = max(float(upper) - float(lower), np.finfo(float).eps)
        scores += float(preference["fixed_weight"]) * _smooth_range_penalty(
            values,
            float(preference["lower"]),
            float(preference["upper"]),
            scale=scale,
        )
    return scores


def decayed_evidence_weight(
    lambda_0: float, alpha: float, n_unique_designs: int
) -> float:
    return float(lambda_0 / (1 + alpha * n_unique_designs))
