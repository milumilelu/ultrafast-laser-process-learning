"""RSM-effect and held-out permutation parameter identification."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.base import clone
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from packages.process_contracts.schemas import CORE_PARAMETER_NAMES
from packages.process_modeling.model_registry import build_model
from packages.process_modeling.model_selection import group_cv_splits


def _direction(x: pd.Series, y: pd.Series) -> str:
    coefficient = spearmanr(x, y, nan_policy="omit").statistic
    if not np.isfinite(coefficient) or coefficient == 0:
        return "undetermined"
    return "positive" if coefficient > 0 else "negative"


def _normalize(values: np.ndarray) -> np.ndarray:
    values = np.maximum(values.astype(float), 0)
    total = float(values.sum())
    return values / total if total else np.zeros_like(values)


def identify_parameters(
    frame: pd.DataFrame,
    target: str,
    groups: pd.Series,
    methods: list[str] | None = None,
    random_seed: int = 42,
    max_folds: int = 5,
) -> dict:
    selected_methods = methods or ["rsm_effect", "permutation_importance"]
    features = [
        name
        for name in CORE_PARAMETER_NAMES
        if name in frame and frame[name].notna().any()
    ]
    valid_index = frame.dropna(subset=[target, *features]).index
    clean = frame.loc[valid_index].reset_index(drop=True)
    clean_groups = groups.loc[valid_index].astype(str).reset_index(drop=True)
    if len(clean) < 4 or clean_groups.nunique() < 2:
        raise ValueError(
            "parameter identification requires at least four samples and two independent designs"
        )
    x, y = clean[features], clean[target].astype(float)
    by_method: dict[str, dict[str, float]] = {}
    if "rsm_effect" in selected_methods:
        linear = Pipeline(
            [("scale", StandardScaler()), ("ridge", Ridge(alpha=1.0))]
        ).fit(x, y)
        values = _normalize(np.abs(linear.named_steps["ridge"].coef_))
        by_method["rsm_effect"] = dict(zip(features, values, strict=True))
    if "permutation_importance" in selected_methods:
        splitter, _ = group_cv_splits(clean_groups, max_folds)
        fold_values = []
        base = build_model("RandomForest", random_seed)
        for fold_number, (train_index, test_index) in enumerate(
            splitter.split(x, y, clean_groups)
        ):
            fitted = clone(base).fit(x.iloc[train_index], y.iloc[train_index])
            importance = permutation_importance(
                fitted,
                x.iloc[test_index],
                y.iloc[test_index],
                scoring="neg_root_mean_squared_error",
                n_repeats=8,
                random_state=random_seed + fold_number,
            )
            fold_values.append(np.maximum(importance.importances_mean, 0))
        values = _normalize(np.mean(fold_values, axis=0))
        by_method["permutation_importance"] = dict(zip(features, values, strict=True))
    if not by_method:
        raise ValueError("no supported parameter identification method selected")
    aggregate = _normalize(
        np.asarray(
            [
                np.mean([method[name] for method in by_method.values()])
                for name in features
            ],
            dtype=float,
        )
    )
    ordered = sorted(
        (
            {
                "parameter": name,
                "importance": float(aggregate[index]),
                "effect_direction": _direction(x[name], y),
                "method_importance": {
                    method: float(values[name]) for method, values in by_method.items()
                },
            }
            for index, name in enumerate(features)
        ),
        key=lambda item: (-item["importance"], item["parameter"]),
    )
    for rank, item in enumerate(ordered, start=1):
        item["rank"] = rank
    return {
        "target": target,
        "candidate_parameter_scope": features,
        "claim_boundary": "Identification is limited to the observed candidate parameters and ranges in this dataset.",
        "methods": list(by_method),
        "results": ordered,
    }
