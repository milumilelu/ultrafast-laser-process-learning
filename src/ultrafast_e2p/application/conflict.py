"""Prior–Data Conflict：目标实验是否否定 Evidence？

数据量衰减（λ_t）对所有证据一视同仁；冲突检查按 Evidence 与观测的一致性
逐条调整权重：

    compatible        → multiplier 1.0
    uncertain         → multiplier 0.5
    conflicting       → multiplier 0.1
    insufficient_data → multiplier 1.0（数据不足不做否定）

第一版使用 rank association（π_E(x_i) 与观测效用 y_i 的 Spearman 相关），
后续可升级为 prior predictive likelihood / Bayes factor。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ultrafast_e2p.application.soft_prior import log_prior_score

MIN_OBSERVATIONS = 8
COMPATIBLE_THRESHOLD = 0.3
CONFLICT_THRESHOLD = -0.3

LEVEL_MULTIPLIER = {
    "compatible": 1.0,
    "uncertain": 0.5,
    "conflicting": 0.1,
    "insufficient_data": 1.0,
}


def _spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < MIN_OBSERVATIONS or len(y) < MIN_OBSERVATIONS:
        return None
    from scipy.stats import spearmanr

    correlation = spearmanr(x, y, nan_policy="omit").statistic
    if not np.isfinite(correlation):
        return None
    return float(correlation)


def _claim_id(preference: dict[str, Any]) -> str:
    return str(
        preference.get("claim_id")
        or preference.get("evidence_id")
        or preference.get("parameter")
    )


def compile_conflict_report(
    prior_spec: dict[str, Any],
    rows: list[dict[str, Any]],
    target: str,
    lower_is_better: bool = False,
) -> dict[str, Any]:
    """对每个 range preference 计算与观测的一致性。"""
    preferences = prior_spec.get("range_preferences") or []
    if not preferences:
        return {"status": "no_prior", "claims": [], "overall": "no_prior"}

    x_by_parameter: dict[str, list[float]] = {}
    utility: list[float] = []
    for row in rows:
        value = row.get(target)
        if value is None or not isinstance(value, (int, float)):
            continue
        for preference in preferences:
            parameter = preference["parameter"]
            if parameter in row and isinstance(row[parameter], (int, float)):
                x_by_parameter.setdefault(parameter, []).append(float(row[parameter]))
        utility.append(-float(value) if lower_is_better else float(value))
    utility_array = np.asarray(utility, dtype=float)

    claims = []
    for preference in preferences:
        parameter = preference["parameter"]
        x = np.asarray(x_by_parameter.get(parameter, []), dtype=float)
        if len(x) < MIN_OBSERVATIONS or len(x) != len(utility_array):
            level, multiplier = "insufficient_data", 1.0
            rho = None
        else:
            prior_score = log_prior_score(
                {parameter: x}, {"range_preferences": [preference]}
            )
            rho = _spearman(prior_score, utility_array)
            if rho is None:
                level, multiplier = "insufficient_data", 1.0
            elif rho >= COMPATIBLE_THRESHOLD:
                level, multiplier = "compatible", 1.0
            elif rho <= CONFLICT_THRESHOLD:
                level, multiplier = "conflicting", 0.1
            else:
                level, multiplier = "uncertain", 0.5
        claims.append(
            {
                "claim_id": _claim_id(preference),
                "parameter": parameter,
                "level": level,
                "multiplier": multiplier,
                "spearman_rho": rho,
                "n_observations": len(x),
            }
        )
    overall = "conflicting" if any(c["level"] == "conflicting" for c in claims) else (
        "compatible" if all(c["level"] in {"compatible", "insufficient_data"} for c in claims) else "uncertain"
    )
    return {"status": "assessed", "claims": claims, "overall": overall}


def apply_conflict_multiplier(
    prior_spec: dict[str, Any], conflict_report: dict[str, Any]
) -> dict[str, Any]:
    """按冲突报告调整 fixed_weight：错误证据的影响比时间衰减更快下降。"""
    multipliers = {
        claim["claim_id"]: claim["multiplier"]
        for claim in conflict_report.get("claims", [])
    }
    updated = dict(prior_spec)
    updated["range_preferences"] = [
        {
            **preference,
            "fixed_weight": float(preference["fixed_weight"])
            * float(multipliers.get(_claim_id(preference), 1.0)),
            "conflict_multiplier": multipliers.get(_claim_id(preference), 1.0),
        }
        for preference in prior_spec.get("range_preferences", [])
    ]
    return updated
