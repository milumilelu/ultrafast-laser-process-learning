"""ValidationArtifact：模型验证结果的不可伪造容器（P1）。

校准状态不能由调用方口头声明：uncertainty_calibrated 只有在验证
指标来自带完整 provenance 的 ValidationArtifact（dataset/model/CV 划分
/evaluator 版本绑定）且通过 acceptance 阈值时才成立。

"指标存在" ≠ "已经校准"：
- coverage 必须落在 [CALIBRATION_ACCEPTANCE.coverage_min, coverage_max]；
- |coverage - nominal|（uncertainty_calibration_error）必须 ≤ max_calibration_error；
- 裸 dict（无 dataset_version / evaluator_version / cv_strategy）永远不算已校准。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

EVALUATOR_VERSION = "model-evaluator-1.0"

CALIBRATION_ACCEPTANCE: dict[str, float] = {
    "coverage_min": 0.85,
    "coverage_max": 1.01,
    "max_calibration_error": 0.15,
}

REQUIRED_METRICS = (
    "rmse",
    "mae",
    "negative_log_predictive_density",
    "prediction_interval_coverage",
    "uncertainty_calibration_error",
)

PROVENANCE_FIELDS = ("dataset_version", "model_version", "evaluator_version", "cv_strategy")


@dataclass(frozen=True, slots=True)
class ValidationArtifact:
    dataset_version: str
    model_version: str
    objective_metric: str
    cv_strategy: str
    evaluator_version: str = EVALUATOR_VERSION
    feature_schema_version: str = "1.0"
    n_samples: int = 0
    n_unique_designs: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationArtifact:
        return cls(
            dataset_version=str(data.get("dataset_version") or ""),
            model_version=str(data.get("model_version") or ""),
            objective_metric=str(data.get("objective_metric") or ""),
            cv_strategy=str(data.get("cv_strategy") or ""),
            evaluator_version=str(data.get("evaluator_version") or EVALUATOR_VERSION),
            feature_schema_version=str(data.get("feature_schema_version") or "1.0"),
            n_samples=int(data.get("n_samples") or 0),
            n_unique_designs=int(data.get("n_unique_designs") or 0),
            metrics=dict(data.get("metrics") or {}),
            created_at=data.get("created_at"),
        )


def has_provenance(value: dict[str, Any]) -> bool:
    """指标必须绑定 dataset/model/CV 划分/evaluator 版本才可信。"""
    return all(bool(value.get(name)) for name in PROVENANCE_FIELDS)


def calibration_verdict(value: dict[str, Any]) -> tuple[bool, list[str]]:
    """返回 (calibrated, reasons)。calibrated 要求 provenance + 达标阈值。"""
    reasons: list[str] = []
    if not has_provenance(value):
        reasons.append("validation metrics lack provenance (dataset/model/CV/evaluator)")
        return False, reasons
    metrics = value.get("metrics")
    if not isinstance(metrics, dict):
        reasons.append("validation metrics missing numeric metrics block")
        return False, reasons
    missing = [name for name in REQUIRED_METRICS if name not in metrics]
    if missing:
        reasons.append(f"validation artifact missing metrics: {sorted(missing)}")
        return False, reasons
    coverage = float(metrics["prediction_interval_coverage"])
    error = float(metrics["uncertainty_calibration_error"])
    if not (
        CALIBRATION_ACCEPTANCE["coverage_min"]
        <= coverage
        <= CALIBRATION_ACCEPTANCE["coverage_max"]
    ):
        reasons.append(
            f"coverage {coverage:.3f} outside [{CALIBRATION_ACCEPTANCE['coverage_min']}, "
            f"{CALIBRATION_ACCEPTANCE['coverage_max']}]"
        )
    if error > CALIBRATION_ACCEPTANCE["max_calibration_error"]:
        reasons.append(
            f"calibration error {error:.3f} > {CALIBRATION_ACCEPTANCE['max_calibration_error']}"
        )
    return not reasons, reasons
