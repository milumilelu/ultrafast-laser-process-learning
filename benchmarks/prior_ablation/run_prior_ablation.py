"""等预算 prior 消融 benchmark：vanilla vs correct-prior vs wrong-prior。

核心科研命题验证（顺序 BO 闭环）：
1. 正确 prior 在数据稀疏阶段显著提高 sample efficiency；
2. 错误 prior 在数据增长后自动衰减（decayed_evidence_weight），
   且推荐点被真实实验观测后纠正模型 —— regret 后期收敛回 vanilla。

协议：三臂等预算、独立闭环。每臂各自维护训练集：
初始 5 个随机种子点 → 每轮 BO 推荐一个点 → 真函数+观测噪声评估 →
推荐点回填训练集。多 seed 重复取均值。

用法：
    PYTHONPATH=src python benchmarks/prior_ablation/run_prior_ablation.py
    [--budget 25] [--seeds 3] [--init 5] [--output .../results.json]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from ultrafast_bo.application.services import BOSample, _BOCoreEngine
from ultrafast_e2p.application.soft_prior import decayed_evidence_weight

MACHINE_BOUNDS = {
    "frequency_kHz": [2.0, 200.0],
    "scan_speed_mm_s": [1.0, 200.0],
    "pulse_width_fs": [500.0, 8000.0],
}

# 真函数：深度在 frequency=20, scan_speed=50 附近取最大
FREQUENCY_STAR = 20.0
SPEED_STAR = 50.0


def true_objective(x: dict[str, float]) -> float:
    freq, speed, pulse = x["frequency_kHz"], x["scan_speed_mm_s"], x["pulse_width_fs"]
    peak = 45.0
    falloff = (
        0.12 * abs(freq - FREQUENCY_STAR)
        + 0.06 * abs(speed - SPEED_STAR)
        + 0.003 * (pulse - 1500.0) / 1000.0
    )
    return peak - falloff


def true_optimum() -> float:
    return true_objective(
        {"frequency_kHz": FREQUENCY_STAR, "scan_speed_mm_s": SPEED_STAR, "pulse_width_fs": 1500.0}
    )


def prior_for(parameter: str, center: float, span: float) -> dict[str, Any]:
    return {
        "approval_id": f"ABLATION-{parameter}-{center}",
        "parameter_name": parameter,
        "lower_bound": float(center - span),
        "upper_bound": float(center + span),
    }


def correct_prior() -> list[dict[str, Any]]:
    return [
        prior_for("frequency_kHz", FREQUENCY_STAR, 5.0),
        prior_for("scan_speed_mm_s", SPEED_STAR, 10.0),
    ]


def wrong_prior() -> list[dict[str, Any]]:
    return [
        prior_for("frequency_kHz", 160.0, 5.0),
        prior_for("scan_speed_mm_s", 160.0, 10.0),
    ]


def _recommend(
    engine: _BOCoreEngine,
    samples: list[BOSample],
    priors: list[dict[str, Any]] | None,
    lambda_0: float,
) -> dict[str, Any]:
    task = {
        "objective_metric": "depth_um",
        "random_seed": 11,
        # 高候选密度：正确 prior 区间（联合 ~0.5%）需要有候选可提升；
        # 稀疏候选下 prior 引导无点可选，无法验证机制。
        "candidate_count": 2048,
        "prior_lambda_0": lambda_0,
        "knowledge_gate_decision": {"status": "allowed"},
    }
    context = {"active": True, "machine_bounds": MACHINE_BOUNDS, "revision_id": "ablation"}
    return engine.recommend(task, samples, context, approved_priors=priors or [])


def _initial_samples(seed: int, init: int) -> list[BOSample]:
    rng = np.random.default_rng(seed)
    samples: list[BOSample] = []
    for index in range(init):
        freq = float(rng.uniform(*MACHINE_BOUNDS["frequency_kHz"]))
        speed = float(rng.uniform(*MACHINE_BOUNDS["scan_speed_mm_s"]))
        pulse = float(rng.uniform(*MACHINE_BOUNDS["pulse_width_fs"]))
        x = {"frequency_kHz": freq, "scan_speed_mm_s": speed, "pulse_width_fs": pulse}
        samples.append(
            BOSample(
                sample_id=f"init-{index}",
                x_parameters=x,
                y_metrics={"depth_um": true_objective(x) + float(rng.normal(0, 0.3))},
            )
        )
    return samples


def run_sequential_arm(
    engine: _BOCoreEngine,
    priors: list[dict[str, Any]] | None,
    budget: int,
    seed: int,
    init: int,
    lambda_0: float = 0.2,
) -> list[dict[str, Any]]:
    """单臂顺序 BO 闭环：推荐 → 真函数观测 → 回填。返回每轮 regret 轨迹。

    三臂共享同一初始样本集与观测噪声序列（seed 相同），保证等预算公平比较。
    """
    rng = np.random.default_rng(seed)
    samples: list[BOSample] = _initial_samples(seed, init)
    trajectory: list[dict[str, Any]] = []
    for step in range(budget):
        result = _recommend(engine, samples, priors, lambda_0)
        parameters = result.get("recommended_parameters") or {}
        applied = (result.get("governed_prior") or {}).get("applied_preferences", 0)
        if not parameters:
            trajectory.append({"step": step, "regret": float("nan"), "applied_preferences": applied})
            continue
        regret = abs(true_optimum() - true_objective(parameters))
        trajectory.append(
            {
                "step": step,
                "regret": float(regret),
                "applied_preferences": applied,
                "recommended_frequency_kHz": parameters["frequency_kHz"],
                "recommended_scan_speed_mm_s": parameters["scan_speed_mm_s"],
            }
        )
        # 真实实验：真函数 + 观测噪声（同一噪声流），回填训练集
        observed = true_objective(parameters) + float(rng.normal(0, 0.3))
        samples.append(
            BOSample(
                sample_id=f"step-{step}",
                x_parameters=parameters,
                y_metrics={"depth_um": observed},
            )
        )
    return trajectory


def run(budget: int, seeds: int, init: int, output: Path, lambda_0: float = 0.2) -> dict[str, Any]:
    engine = _BOCoreEngine()
    arms = {"vanilla": None, "correct_prior": correct_prior(), "wrong_prior": wrong_prior()}
    trajectories: dict[str, list[dict[str, Any]]] = {name: [] for name in arms}
    for seed in range(seeds):
        base_seed = 1000 * seed + 7
        for name, priors in arms.items():
            trajectories[name].extend(
                run_sequential_arm(engine, priors, budget, seed=base_seed, init=init, lambda_0=lambda_0)
            )
    aggregated: list[dict[str, Any]] = []
    for step in range(budget):
        row: dict[str, Any] = {"step": step}
        for name in arms:
            step_rows = [t for t in trajectories[name] if t["step"] == step and math.isfinite(t["regret"])]
            row[f"{name}_regret_mean"] = float(np.mean([t["regret"] for t in step_rows])) if step_rows else float("nan")
            row[f"{name}_applied_preferences_mean"] = (
                float(np.mean([t["applied_preferences"] for t in step_rows])) if step_rows else 0.0
            )
        row["prior_weight_lambda_t"] = decayed_evidence_weight(0.2, 0.1, init + step)
        aggregated.append(row)
    # 逐 seed 的 best-so-far（累计最小 regret）与累计 regret：sample efficiency 标准度量
    best_so_far: dict[str, list[float]] = {name: [] for name in arms}
    cumulative: dict[str, list[float]] = {name: [] for name in arms}
    for seed_index in range(seeds):
        offset = seed_index * budget
        for name in arms:
            arm = [t for t in trajectories[name][offset : offset + budget] if math.isfinite(t["regret"])]
            if not arm:
                best_so_far[name].append(float("nan"))
                cumulative[name].append(float("nan"))
                continue
            best = float("inf")
            total = 0.0
            best_values = []
            total_values = []
            for t in arm:
                best = min(best, t["regret"])
                total += t["regret"]
                best_values.append(best)
                total_values.append(total)
            best_so_far[name].append(best_values[-1])
            cumulative[name].append(total_values[-1])
    report = {
        "config": {
            "budget": budget,
            "seeds": seeds,
            "init_samples": init,
            "objective": "depth_um(synthetic)",
            "prior_lambda_0": lambda_0,
        },
        "true_optimum": true_optimum(),
        "correct_prior": correct_prior(),
        "wrong_prior": wrong_prior(),
        "aggregated": aggregated,
        "trajectories": trajectories,
        "best_so_far_mean": {name: float(np.nanmean(values)) for name, values in best_so_far.items()},
        "cumulative_regret_mean": {name: float(np.nanmean(values)) for name, values in cumulative.items()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def summarize(report: dict[str, Any]) -> str:
    rows = report["aggregated"]
    early = rows[: max(5, len(rows) // 3)]
    late = rows[-max(5, len(rows) // 3):]
    def mean(rows_: list[dict[str, Any]], key: str) -> float:
        values = [float(r[key]) for r in rows_ if math.isfinite(r[key])]
        return float(np.mean(values)) if values else float("nan")

    bsf = report["best_so_far_mean"]
    cum = report["cumulative_regret_mean"]
    return "\n".join(
        [
            f"budget={report['config']['budget']} seeds={report['config']['seeds']} init={report['config']['init_samples']} lambda0={report['config']['prior_lambda_0']}",
            (
                f"early: vanilla={mean(early,'vanilla_regret_mean'):.3f} correct={mean(early,'correct_prior_regret_mean'):.3f} "
                f"wrong={mean(early,'wrong_prior_regret_mean'):.3f}"
            ),
            (
                f"late : vanilla={mean(late,'vanilla_regret_mean'):.3f} correct={mean(late,'correct_prior_regret_mean'):.3f} "
                f"wrong={mean(late,'wrong_prior_regret_mean'):.3f}"
            ),
            f"best-so-far: vanilla={bsf['vanilla']:.3f} correct={bsf['correct_prior']:.3f} wrong={bsf['wrong_prior']:.3f}",
            f"cumulative : vanilla={cum['vanilla']:.1f} correct={cum['correct_prior']:.1f} wrong={cum['wrong_prior']:.1f}",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="prior ablation benchmark (sequential BO loop)")
    parser.add_argument("--budget", type=int, default=25)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--init", type=int, default=5)
    parser.add_argument("--lambda-0", type=float, default=0.2, help="prior 初始权重（机制敏感性）")
    parser.add_argument("--output", type=Path, default=Path("benchmarks/prior_ablation/results.json"))
    args = parser.parse_args()
    report = run(args.budget, args.seeds, args.init, args.output, lambda_0=args.lambda_0)
    print(summarize(report))
    print(f"written: {args.output}")


if __name__ == "__main__":
    main()
