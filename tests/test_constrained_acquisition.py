"""P2 回归：constrained acquisition（第一层）+ 确定性投影（第二层）分层。

- acquisition 层：候选评分乘 P(feasible|x)（同目标指标约束）；
- 投影层：参数耦合约束的确定性投影与合法 fallback（已有，本测试确认保留）。
"""

from __future__ import annotations

import numpy as np

from ultrafast_bo.application.services import BOSample, BOStatusService, OfflineModelingService

MACHINE_BOUNDS = {
    "pulse_width_fs": [500.0, 8000.0],
    "frequency_kHz": [2.0, 200.0],
    "scan_speed_mm_s": [1.0, 200.0],
}


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


def test_outcome_constraint_enters_acquisition() -> None:
    service = OfflineModelingService()
    task = {"objective_metric": "depth_um", "random_seed": 11, "candidate_count": 512}
    constrained = service.fit_and_recommend(
        _samples(),
        MACHINE_BOUNDS,
        {**task, "outcome_constraints": [{"metric": "depth_um", "operator": "min", "threshold": 45.0}]},
        BOStatusService().status_for_count(24),
    )
    info = constrained["acquisition_info"]
    assert info["feasibility_aware"]["mode"] == "multiplicative_acquisition"
    assert info["feasibility_aware"]["constraints"][0]["metric"] == "depth_um"
    assert 0.0 < info["feasibility_aware"]["candidate_feasibility_mean"] <= 1.0


def test_infeasible_candidates_are_degraded_not_selected() -> None:
    service = OfflineModelingService()
    task = {"objective_metric": "depth_um", "random_seed": 11, "candidate_count": 512}
    # 阈值设为远高于数据范围 → 所有候选 P(feasible)≈0 → 仍返回候选但标注可行性
    result = service.fit_and_recommend(
        _samples(),
        MACHINE_BOUNDS,
        {**task, "outcome_constraints": [{"metric": "depth_um", "operator": "min", "threshold": 200.0}]},
        BOStatusService().status_for_count(24),
    )
    info = result["acquisition_info"]
    assert info["feasibility_aware"]["candidate_feasibility_mean"] < 0.1
    assert result["parameters"]


def test_cross_metric_constraint_is_excluded_from_acquisition() -> None:
    """跨指标约束无联合模型：不进 acquisition（保守），留给第二层过滤。"""
    service = OfflineModelingService()
    task = {"objective_metric": "depth_um", "random_seed": 11, "candidate_count": 512}
    result = service.fit_and_recommend(
        _samples(),
        MACHINE_BOUNDS,
        {**task, "outcome_constraints": [{"metric": "roughness_um", "operator": "max", "threshold": 5.0}]},
        BOStatusService().status_for_count(24),
    )
    assert "feasibility_aware" not in result["acquisition_info"]


def test_deterministic_projection_layer_still_present() -> None:
    """第二层（确定性投影）仍由 constrained service 负责。"""
    from ultrafast_bo.application.constrained_service import (
        ConstrainedBORecommendationService,
    )
    from ultrafast_bo.application.search_space import ConstraintEvaluator, project_candidate

    space = __import__("ultrafast_bo.application.search_space", fromlist=["SearchSpaceBuilder"]).SearchSpaceBuilder().compile(
        {"material": "SiC", "process_type": "milling", "objective_metric": "depth_um"},
        {"machine_bounds": MACHINE_BOUNDS, "revision_id": "rev-1"},
        {
            "pulse_width_fs": {"mode": "bounded", "lower": 500.0, "upper": 8000.0, "condition": {}, "unit": "fs"},
            "frequency_kHz": {"mode": "bounded", "lower": 2.0, "upper": 200.0, "condition": {}, "unit": "kHz"},
            "scan_speed_mm_s": {"mode": "bounded", "lower": 1.0, "upper": 200.0, "condition": {}, "unit": "mm/s"},
        },
        [],
        {},
        "trial_cut",
    )
    service = ConstrainedBORecommendationService()
    assert service.constraints is not None
    assert ConstraintEvaluator.FORMULA_VERSION
    projected = project_candidate({"frequency_kHz": 10.0}, space)
    assert projected["frequency_kHz"] == 10.0
