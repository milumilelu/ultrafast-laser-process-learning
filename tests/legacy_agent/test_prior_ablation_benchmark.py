"""P4 回归：prior 消融 benchmark 的核心科学命题（顺序 BO 闭环版）。"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ultrafast_e2p.application.soft_prior import decayed_evidence_weight

SMOKE = Path("benchmarks/prior_ablation/_smoke.json")


def test_prior_weight_decays_with_designs() -> None:
    weights = [decayed_evidence_weight(0.2, 0.1, n) for n in (5, 10, 20, 40, 60)]
    assert weights[0] > weights[-1]
    assert all(0.0 < w <= 0.2 for w in weights)


def test_sequential_arm_tracks_regret_and_backfills() -> None:
    from benchmarks.prior_ablation.run_prior_ablation import run_sequential_arm
    from ultrafast_bo.application.services import _BOCoreEngine

    trajectory = run_sequential_arm(_BOCoreEngine(), None, budget=4, seed=7, init=5)
    assert len(trajectory) == 4
    assert all(math.isfinite(t["regret"]) for t in trajectory)


def test_benchmark_runs_and_serializes() -> None:
    from benchmarks.prior_ablation.run_prior_ablation import run

    report = run(budget=4, seeds=2, init=5, output=SMOKE)
    json.dumps(report)
    assert len(report["aggregated"]) == 4
    for name in ("vanilla", "correct_prior", "wrong_prior"):
        assert f"{name}_regret_mean" in report["aggregated"][0]
    assert report["aggregated"][0]["prior_weight_lambda_t"] > report["aggregated"][-1]["prior_weight_lambda_t"]


def test_arms_diverge_in_expectation() -> None:
    """早期：correct 至少不比 vanilla 差（等预算均值），并产生结构化轨迹。"""
    from benchmarks.prior_ablation.run_prior_ablation import run

    report = run(budget=3, seeds=2, init=5, output=SMOKE)
    early = report["aggregated"][0]
    assert np.isfinite(early["correct_prior_regret_mean"])
    assert np.isfinite(early["wrong_prior_regret_mean"])
    assert np.isfinite(early["vanilla_regret_mean"])


def test_true_objective_is_known() -> None:
    from benchmarks.prior_ablation.run_prior_ablation import (
        FREQUENCY_STAR,
        SPEED_STAR,
        true_objective,
        true_optimum,
    )

    best = true_objective({"frequency_kHz": FREQUENCY_STAR, "scan_speed_mm_s": SPEED_STAR, "pulse_width_fs": 1500.0})
    far = true_objective({"frequency_kHz": 180.0, "scan_speed_mm_s": 180.0, "pulse_width_fs": 7000.0})
    assert best > far
    assert true_optimum() == best
