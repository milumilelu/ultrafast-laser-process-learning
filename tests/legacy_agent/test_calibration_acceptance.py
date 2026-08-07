"""P1 回归：calibration 必须是"验证产物 + 达标"，不是"指标存在"。"""

from __future__ import annotations

from ultrafast_bo.application.governance import BOReadinessAssessmentService
from ultrafast_bo.application.validation import (
    CALIBRATION_ACCEPTANCE,
    ValidationArtifact,
    calibration_verdict,
)

GOOD_ARTIFACT = {
    "dataset_version": "ds-abc123",
    "model_version": "gpr-v3",
    "objective_metric": "depth_um",
    "cv_strategy": "GroupKFold(n=5)",
    "evaluator_version": "model-evaluator-1.0",
    "feature_schema_version": "1.0",
    "n_samples": 60,
    "n_unique_designs": 55,
    "metrics": {
        "rmse": 2.1,
        "mae": 1.5,
        "negative_log_predictive_density": 1.2,
        "prediction_interval_coverage": 0.93,
        "uncertainty_calibration_error": 0.02,
    },
}


def test_metrics_exist_is_not_enough_without_provenance() -> None:
    """裸 dict（评审示例：coverage=0.30, error=0.65）永远不算已校准。"""
    bare = {
        "prediction_interval_coverage": 0.30,
        "uncertainty_calibration_error": 0.65,
    }
    calibrated, reasons = calibration_verdict(bare)
    assert calibrated is False
    assert any("provenance" in reason for reason in reasons)


def test_poor_coverage_fails_acceptance_even_with_provenance() -> None:
    artifact = {
        **GOOD_ARTIFACT,
        "metrics": {
            **GOOD_ARTIFACT["metrics"],
            "prediction_interval_coverage": 0.30,
            "uncertainty_calibration_error": 0.65,
        },
    }
    calibrated, reasons = calibration_verdict(artifact)
    assert calibrated is False
    assert any("coverage" in reason for reason in reasons)


def test_good_artifact_passes_acceptance() -> None:
    calibrated, reasons = calibration_verdict(GOOD_ARTIFACT)
    assert calibrated is True, reasons


def test_artifact_round_trip() -> None:
    artifact = ValidationArtifact.from_dict(GOOD_ARTIFACT)
    assert artifact.dataset_version == "ds-abc123"
    assert artifact.cv_strategy == "GroupKFold(n=5)"
    assert artifact.to_dict()["metrics"]["prediction_interval_coverage"] == 0.93


def test_readiness_requires_calibration_for_data_driven_status() -> None:
    from ultrafast_bo.domain.models import BOSample

    rng = __import__("numpy").random.default_rng(3)
    samples = []
    for index in range(60):
        samples.append(
            BOSample(
                sample_id=f"s{index}",
                x_parameters={"frequency_kHz": float(rng.uniform(2, 200))},
                y_metrics={"depth_um": float(rng.uniform(10, 50))},
            )
        )
    bounds = {"frequency_kHz": [2.0, 200.0]}
    service = BOReadinessAssessmentService()
    report = service.assess(
        samples,
        target_metric="depth_um",
        parameter_bounds=bounds,
        validation_metrics=GOOD_ARTIFACT,
    )
    assert report.uncertainty_calibrated is True
    assert report.model_status == "data_driven_bo"
    assert report.calibration_reasons == []


def test_readiness_bare_metrics_never_upgrade_status() -> None:
    from ultrafast_bo.domain.models import BOSample

    rng = __import__("numpy").random.default_rng(3)
    samples = []
    for index in range(60):
        samples.append(
            BOSample(
                sample_id=f"s{index}",
                x_parameters={"frequency_kHz": float(rng.uniform(2, 200))},
                y_metrics={"depth_um": float(rng.uniform(10, 50))},
            )
        )
    bounds = {"frequency_kHz": [2.0, 200.0]}
    service = BOReadinessAssessmentService()
    report = service.assess(
        samples,
        target_metric="depth_um",
        parameter_bounds=bounds,
        validation_metrics={
            "prediction_interval_coverage": 0.95,
            "uncertainty_calibration_error": 0.0,
        },
    )
    assert report.uncertainty_calibrated is False
    assert report.model_status == "hybrid_rule_bo"
    assert any("provenance" in warning for warning in report.warnings)


def test_acceptance_constants_are_sane() -> None:
    assert CALIBRATION_ACCEPTANCE["coverage_min"] <= 0.90
    assert CALIBRATION_ACCEPTANCE["max_calibration_error"] <= 0.15
