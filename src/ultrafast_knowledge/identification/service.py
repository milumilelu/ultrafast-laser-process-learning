"""Parameter Identification V2（文档 §32-37）。

三模式对照：
    raw     —— 只使用可控参数（回答：该调哪个工艺旋钮）
    physics —— 只使用机理特征（回答：通过什么物理过程影响结果）
    hybrid  —— 精选 raw + 精选 physics（避免无约束混合全部变量）

双排名输出（文档 §33）：Controllable Importance 与 Mechanism Importance 分开。
OOF Permutation Importance（文档 §36-37）：Group-CV → fold train fit →
fold test permutation → 聚合。Grouped Importance 按机理组（Energy/Overlap/Thermal）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ultrafast_e2p.application.model_selection import assert_no_group_leakage, group_cv_splits
from ultrafast_physics.feature_builder import FEATURE_GROUPS

CONTROLLABLE_PARAMETERS = (
    "laser_power_W",
    "frequency_kHz",
    "pulse_width_fs",
    "scan_speed_mm_s",
    "hatch_spacing_um",
    "passes",
)

MECHANISM_GROUPS = ("energy_delivery", "overlap", "thermal")


def _normalize(values: np.ndarray) -> np.ndarray:
    values = np.maximum(np.asarray(values, dtype=float), 0.0)
    total = float(values.sum())
    return values / total if total else np.zeros_like(values)


def _direction(x: pd.Series, y: pd.Series) -> str:
    from scipy.stats import spearmanr

    coefficient = spearmanr(x, y, nan_policy="omit").statistic
    if not np.isfinite(coefficient) or coefficient == 0:
        return "undetermined"
    return "positive" if coefficient > 0 else "negative"


def _oof_permutation_importance(
    x: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    random_seed: int,
    max_folds: int = 5,
) -> dict[str, float]:
    """Group-CV OOF permutation importance（文档 §37）。"""
    splitter, _folds = group_cv_splits(groups.astype(str), max_folds)
    splits = list(splitter.split(x, y, groups.astype(str)))
    assert_no_group_leakage(splits, groups.astype(str))
    estimator = Pipeline(
        [
            ("scale", StandardScaler()),
            ("rf", RandomForestRegressor(n_estimators=200, min_samples_leaf=2, random_state=random_seed, n_jobs=1)),
        ]
    )
    fold_values = []
    for fold_number, (train_index, test_index) in enumerate(splits):
        fitted = clone(estimator).fit(x.iloc[train_index], y.iloc[train_index])
        importance = permutation_importance(
            fitted,
            x.iloc[test_index],
            y.iloc[test_index],
            scoring="neg_root_mean_squared_error",
            n_repeats=8,
            random_state=random_seed + fold_number,
        )
        fold_values.append(np.maximum(importance.importances_mean, 0))
    return dict(zip(x.columns, _normalize(np.mean(fold_values, axis=0)), strict=True))


def identify_v2(
    frame: pd.DataFrame,
    target: str,
    groups: pd.Series,
    *,
    mode: str = "raw",
    feature_columns: dict[str, list[str]] | None = None,
    max_folds: int = 5,
    random_seed: int = 42,
) -> dict[str, Any]:
    """三模式参数辨识（文档 §32-33）。frame 含目标列与特征列；groups 为组合 id。"""
    if mode not in {"raw", "physics", "hybrid"}:
        raise ValueError(f"unsupported identification mode: {mode}")
    columns = feature_columns or {
        "controllable": [name for name in CONTROLLABLE_PARAMETERS if name in frame],
        "mechanism": [name for name in frame.columns if name in FEATURE_GROUPS],
    }
    if mode == "raw":
        features = list(columns.get("controllable", []))
    elif mode == "physics":
        features = list(columns.get("mechanism", []))
    else:  # hybrid：精选 raw + 精选 physics（不无约束混合全部变量）
        features = list(columns.get("controllable", [])) + list(columns.get("mechanism", []))
    features = [name for name in features if name in frame and frame[name].notna().any()]
    if not features:
        raise ValueError(f"no usable features for mode {mode}")
    valid_index = frame.dropna(subset=[target, *features]).index
    clean = frame.loc[valid_index].reset_index(drop=True)
    clean_groups = groups.loc[valid_index].astype(str).reset_index(drop=True)
    if len(clean) < 4 or clean_groups.nunique() < 2:
        raise ValueError(
            "identification requires at least four samples and two independent designs"
        )
    x = clean[features]
    y = clean[target].astype(float)
    linear = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=1.0))]).fit(x, y)
    rsm_effect = _normalize(np.abs(linear.named_steps["ridge"].coef_))
    permutation = _oof_permutation_importance(x, y, clean_groups, random_seed, max_folds)
    controllable_ranking = []
    mechanism_ranking = []
    aggregated = _normalize(
        np.asarray(
            [
                np.mean([rsm_effect[index], permutation[name]])
                for index, name in enumerate(features)
            ],
            dtype=float,
        )
    )
    for rank, (name, importance) in enumerate(
        sorted(zip(features, aggregated, strict=True), key=lambda item: (-item[1], item[0])),
        start=1,
    ):
        entry = {
            "feature": name,
            "importance": float(importance),
            "effect_direction": _direction(x[name], y),
            "rsm_effect": float(rsm_effect[features.index(name)]),
            "oof_permutation_importance": float(permutation[name]),
            "rank": rank,
        }
        if name in FEATURE_GROUPS:
            mechanism_ranking.append(entry)
        else:
            controllable_ranking.append(entry)
    groups_aggregate: dict[str, float] = {}
    for group in MECHANISM_GROUPS:
        members = [name for name, g in FEATURE_GROUPS.items() if g == group and name in features]
        if members:
            groups_aggregate[group] = float(
                sum(aggregated[features.index(name)] for name in members)
            )
    return {
        "mode": mode,
        "target": target,
        "feature_count": len(features),
        "n_samples": len(clean),
        "n_unique_designs": int(clean_groups.nunique()),
        "cv_strategy": "GroupKFold",
        "controllable_ranking": controllable_ranking,
        "mechanism_ranking": mechanism_ranking,
        "mechanism_group_importance": groups_aggregate,
        "claim_boundary": (
            "identification is limited to observed feature ranges; "
            "physics features require governed device/material properties"
        ),
    }
