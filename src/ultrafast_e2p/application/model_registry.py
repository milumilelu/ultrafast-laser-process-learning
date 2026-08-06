"""Canonical ModelRegistry：模型名是唯一正式标识，禁止各处手写字符串。

名称与 Topic2 验收核保持一致：RSM / GPR / RandomForest / HistGradientBoosting；
XGBoost 在安装可用时以显式名称注册（不静默别名）。
"""

from __future__ import annotations

from typing import Any

from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

ACCEPTANCE_MODELS = ("RSM", "GPR", "RandomForest", "HistGradientBoosting")

try:  # pragma: no cover - optional dependency
    from xgboost import XGBRegressor  # type: ignore[import-not-found]

    _XGBOOST_AVAILABLE = True
except Exception:  # noqa: BLE001 - optional dependency
    _XGBOOST_AVAILABLE = False


def build_model(name: str, random_seed: int = 42) -> Any:
    if name == "RSM":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("poly", PolynomialFeatures(degree=2, include_bias=False)),
                ("ridge", Ridge(alpha=1.0)),
            ]
        )
    if name == "GPR":
        kernel = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(
            length_scale=1.0, nu=2.5
        ) + WhiteKernel(
            noise_level=1e-3,
            noise_level_bounds=(1e-8, 1e1),
        )
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "gpr",
                    GaussianProcessRegressor(
                        kernel=kernel,
                        normalize_y=True,
                        random_state=random_seed,
                        n_restarts_optimizer=0,
                    ),
                ),
            ]
        )
    if name == "RandomForest":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "rf",
                    RandomForestRegressor(
                        n_estimators=200,
                        min_samples_leaf=2,
                        random_state=random_seed,
                        n_jobs=1,
                    ),
                ),
            ]
        )
    if name == "HistGradientBoosting":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "boosting",
                    HistGradientBoostingRegressor(
                        max_iter=200,
                        learning_rate=0.05,
                        random_state=random_seed,
                    ),
                ),
            ]
        )
    if name == "XGBoost":
        if not _XGBOOST_AVAILABLE:
            raise KeyError("XGBoost is not installed")
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "xgb",
                    XGBRegressor(
                        n_estimators=200,
                        learning_rate=0.05,
                        max_depth=4,
                        random_state=random_seed,
                        n_jobs=1,
                    ),
                ),
            ]
        )
    raise KeyError(f"unknown model: {name}")


def build_model_specs(
    random_seed: int = 42, names: list[str] | tuple[str, ...] | None = None
) -> dict[str, Any]:
    selected = names or ACCEPTANCE_MODELS
    unknown = set(selected).difference(ACCEPTANCE_MODELS + (("XGBoost",) if _XGBOOST_AVAILABLE else ()))
    if unknown:
        raise ValueError(f"unsupported models: {sorted(unknown)}")
    return {name: build_model(name, random_seed) for name in selected}


def supports_uncertainty(name: str) -> bool:
    return name == "GPR"


def available_models() -> tuple[str, ...]:
    return ACCEPTANCE_MODELS + (("XGBoost",) if _XGBOOST_AVAILABLE else ())
