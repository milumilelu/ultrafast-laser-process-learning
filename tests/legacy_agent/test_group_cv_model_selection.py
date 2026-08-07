"""P3 回归：ModelPolicy 候选集必须经过真实 Group-CV 选择，而非固定 GPR gate。"""

from __future__ import annotations

import numpy as np

from ultrafast_bo.application.services import BOSample, _BOCoreEngine

MACHINE_BOUNDS = {
    "pulse_width_fs": [500.0, 8000.0],
    "frequency_kHz": [2.0, 200.0],
    "scan_speed_mm_s": [1.0, 200.0],
}
GATE = {"knowledge_gate_decision": {"status": "allowed"}}


def _samples() -> list[BOSample]:
    rng = np.random.default_rng(7)
    rows = []
    for index in range(24):
        frequency = float(rng.uniform(2, 200))
        pulse = float(rng.uniform(500, 8000))
        speed = float(rng.uniform(1, 200))
        depth = 40.0 - 0.12 * abs(frequency - 10) + 0.01 * (pulse / 1000) + rng.normal(0, 0.3)
        rows.append(
            BOSample(
                sample_id=f"s{index}",
                x_parameters={
                    "pulse_width_fs": pulse,
                    "frequency_kHz": frequency,
                    "scan_speed_mm_s": speed,
                },
                y_metrics={"depth_um": depth},
            )
        )
    return rows


def test_group_cv_selection_runs_and_audits_winner() -> None:
    engine = _BOCoreEngine()
    task = {
        "objective_metric": "depth_um",
        "random_seed": 11,
        "candidate_count": 512,
        **GATE,
        "model_policy": {
            "model_policy_version": "e2p-model-policy-v1",
            "candidate_models": ["RSM", "GPR", "RandomForest", "HistGradientBoosting"],
            "requirements": {"uncertainty_required": True},
        },
    }
    ctx = {"active": True, "machine_bounds": MACHINE_BOUNDS, "revision_id": "rev-1"}
    result = engine.recommend(task, _samples(), ctx, approved_priors=[])
    selection = next(
        (item for item in result["audit_trace"] if item.get("step") == "group_cv_model_selection"),
        None,
    )
    assert selection is not None
    assert selection["selected"] in {"RSM", "GPR", "RandomForest", "HistGradientBoosting"}
    assert selection["rmse_by_model"]
    policy_choice = next(
        item for item in result["audit_trace"] if item.get("step") == "surrogate_model"
    )["policy_choice"]
    assert policy_choice["basis"] == "group_cv_rmse_mae"
    assert policy_choice["model"] == selection["selected"]


def test_uncertainty_required_blocks_non_gpr_candidates() -> None:
    engine = _BOCoreEngine()
    task = {
        "objective_metric": "depth_um",
        "random_seed": 11,
        **GATE,
        "model_policy": {
            "model_policy_version": "e2p-model-policy-v1",
            "candidate_models": ["RSM", "RandomForest"],
            "requirements": {"uncertainty_required": True},
        },
    }
    ctx = {"active": True, "machine_bounds": MACHINE_BOUNDS, "revision_id": "rev-1"}
    result = engine.recommend(task, _samples(), ctx, approved_priors=[])
    assert result["model_status"] == "blocked"
    assert any(item.get("step") == "model_policy_surrogate_gate" for item in result["audit_trace"])


def test_winner_prediction_drives_recommendation_when_not_gpr() -> None:
    engine = _BOCoreEngine()
    task = {
        "objective_metric": "depth_um",
        "random_seed": 11,
        "candidate_count": 512,
        **GATE,
        "model_policy": {
            "model_policy_version": "e2p-model-policy-v1",
            "candidate_models": ["RSM"],
            "requirements": {"uncertainty_required": False},
        },
    }
    ctx = {"active": True, "machine_bounds": MACHINE_BOUNDS, "revision_id": "rev-1"}
    result = engine.recommend(task, _samples(), ctx, approved_priors=[])
    assert result["bo_invoked"] is True
    surrogate = next(
        item for item in result["audit_trace"] if item.get("step") == "surrogate_model"
    )
    assert surrogate["model"] == "GroupCV_winner"
    assert surrogate["policy_choice"]["model"] == "RSM"
    # 推荐参数必须在机器边界内
    for name, (lower, upper) in MACHINE_BOUNDS.items():
        assert lower <= result["recommended_parameters"][name] <= upper
