"""Rule-based E2P model policy; Group-CV on real data remains the final authority.

E2P 只决定"哪些模型应该参加这次比较，以及评价时的特殊要求"，
最终 winner 必须由真实数据决定。
"""

from __future__ import annotations

from typing import Any

from ultrafast_e2p.domain.evidence import EvidenceBundle

MODEL_POLICY_VERSION = "e2p-model-policy-v1"

DEFAULT_CANDIDATE_MODELS = ("RSM", "GPR", "RandomForest", "HistGradientBoosting")

_SMALL_SAMPLE_THRESHOLD = 30


def decide_model_policy(
    task: dict[str, Any],
    profile: dict[str, Any],
    bundle: EvidenceBundle,
    configured_candidates: list[str] | None = None,
) -> dict[str, Any]:
    candidates = list(configured_candidates or DEFAULT_CANDIDATE_MODELS)
    n_unique_designs = int(profile.get("n_unique_designs", 0))
    preferred = (
        ["GPR", "RSM"]
        if n_unique_designs < _SMALL_SAMPLE_THRESHOLD
        else ["RandomForest", "HistGradientBoosting", "GPR"]
    )
    reasons = ["low_dimensional_continuous_input", "bo_downstream"]
    if n_unique_designs < _SMALL_SAMPLE_THRESHOLD:
        reasons.append("small_sample")
    else:
        reasons.append("moderate_or_large_sample")
    claim_types = {item.claim_type for item in bundle.accepted}
    interpretability = bool(
        claim_types.intersection({"parameter_direction", "relative_importance"})
    )
    if interpretability:
        preferred = ["RSM", *[name for name in preferred if name != "RSM"]]
        reasons.append("interpretable_evidence_alignment")
    historical_preferences = [
        item.value.get("model")
        for item in bundle.accepted
        if item.claim_type == "historical_model" and item.value.get("model") in candidates
    ]
    if historical_preferences:
        preferred = list(dict.fromkeys([*historical_preferences, *preferred]))
        reasons.append("approved_historical_model_evidence")
    return {
        "model_policy_version": MODEL_POLICY_VERSION,
        "candidate_models": candidates,
        "preferred_models": preferred,
        "requirements": {
            "uncertainty_required": True,
            "interpretability_preferred": interpretability,
        },
        "reason_codes": reasons,
        "final_selection_rule": "Group-CV by RMSE, then MAE; policy does not select the final model",
        "scope": dict(task),
    }
