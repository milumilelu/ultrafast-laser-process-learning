"""E2P Adaptive Modeling 执行器：ModelPolicy 候选集 → Group-CV → winner。

原则：
- Group 按 parameter_combination_id（防同设计重复行泄漏）；
- 最终 winner 永远由真实数据 Group-CV 决定，ModelPolicy 只决定候选与评价要求；
- uncertainty_required 时，无不确定性的模型即使点预测最好也不得入选。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold

from ultrafast_e2p.application.model_registry import build_model_specs, supports_uncertainty


@dataclass
class ModelSelectionResult:
    selected_model: str
    estimator: Any
    metrics_by_model: dict[str, dict[str, float | int | bool]]
    predictions: dict[str, list[float]]
    cv_folds: int
    groups: list[str]


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "MAE": float(mean_absolute_error(y_true, y_pred)),
        "R2": float(r2_score(y_true, y_pred)),
    }


def group_cv_splits(groups: Iterable[str], max_folds: int = 5):
    group_array = np.asarray(list(groups), dtype=str)
    n_unique = len(np.unique(group_array))
    folds = min(max_folds, n_unique)
    if folds < 2:
        raise ValueError(
            "Group-CV requires at least two independent parameter combinations"
        )
    return GroupKFold(n_splits=folds), folds


def assert_no_group_leakage(splits: Iterable[tuple[np.ndarray, np.ndarray]], groups: Iterable[str]) -> None:
    values = np.asarray(list(groups), dtype=str)
    for train_index, test_index in splits:
        overlap = set(values[train_index]).intersection(values[test_index])
        if overlap:
            raise RuntimeError(f"Group-CV leakage detected: {sorted(overlap)}")


def select_model(
    x: pd.DataFrame,
    y: pd.Series,
    groups: Iterable[str],
    candidate_models: list[str] | None = None,
    max_folds: int = 5,
    random_seed: int = 42,
    uncertainty_required: bool = False,
) -> ModelSelectionResult:
    candidates = (
        list(candidate_models)
        if candidate_models
        else ["RSM", "GPR", "RandomForest", "HistGradientBoosting"]
    )
    group_values = np.asarray(list(groups), dtype=str)
    splitter, folds = group_cv_splits(group_values, max_folds)
    splits = list(splitter.split(x, y, group_values))
    assert_no_group_leakage(splits, group_values)
    metrics: dict[str, dict[str, float | int | bool]] = {}
    predictions: dict[str, list[float]] = {}
    estimators = build_model_specs(random_seed, candidates)
    for name, estimator in estimators.items():
        predicted = np.full(len(y), np.nan, dtype=float)
        for train_index, test_index in splits:
            fitted = clone(estimator).fit(x.iloc[train_index], y.iloc[train_index])
            predicted[test_index] = fitted.predict(x.iloc[test_index])
        model_metrics: dict[str, float | int | bool] = regression_metrics(
            y.to_numpy(dtype=float), predicted
        )
        model_metrics.update(
            {
                "n_samples": len(y),
                "n_unique_designs": len(np.unique(group_values)),
                "cv_folds": folds,
                "uncertainty_available": supports_uncertainty(name),
            }
        )
        metrics[name] = model_metrics
        predictions[name] = predicted.tolist()
    eligible = [
        name
        for name in candidates
        if not uncertainty_required or supports_uncertainty(name)
    ]
    if not eligible:
        raise ValueError("no candidate model satisfies the uncertainty requirement")
    selected = min(
        eligible,
        key=lambda name: (
            float(metrics[name]["RMSE"]),
            float(metrics[name]["MAE"]),
            name,
        ),
    )
    final = clone(estimators[selected]).fit(x, y)
    return ModelSelectionResult(
        selected, final, metrics, predictions, folds, group_values.tolist()
    )


def comparison_report(
    result: ModelSelectionResult, baseline_model: str = "RSM"
) -> dict[str, Any]:
    if baseline_model not in result.metrics_by_model:
        raise ValueError(f"baseline model was not evaluated: {baseline_model}")
    return {
        "baseline": {
            "model": baseline_model,
            **result.metrics_by_model[baseline_model],
        },
        "optimized": {
            "model": result.selected_model,
            **result.metrics_by_model[result.selected_model],
        },
        "comparison_basis": "same dataset, same Group-CV splits, RMSE/MAE/R2",
        "improved": float(result.metrics_by_model[result.selected_model]["RMSE"])
        <= float(result.metrics_by_model[baseline_model]["RMSE"]),
    }
