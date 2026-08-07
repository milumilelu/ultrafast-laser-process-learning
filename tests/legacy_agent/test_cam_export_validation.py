"""CAM 导出的服务端最终校验：推荐值不得越出搜索空间边界（P1-3）。"""

from __future__ import annotations

import pytest

from ultrafast_agent.process_recommendations.service import (
    ProcessRecommendationService,
    _validate_against_search_space,
    _validate_recommendation_against_metadata,
)


def _base_payload(**overrides) -> dict:
    payload = {
        "task_id": "task-cam-1",
        "workflow_id": "workflow-cam-1",
        "task_spec": {
            "process_type": "surface_texturing",
            "material": "SiC",
            "objective_metric": "Sa_um",
        },
        "search_space": {
            "search_space_version": "v1",
            "feasibility_status": "ready",
            "variables": {
                "laser_power_W": {
                    "mode": "tunable",
                    "lower": 0.0,
                    "upper": 10.0,
                },
                "frequency_kHz": {
                    "mode": "tunable",
                    "lower": 2.0,
                    "upper": 200.0,
                },
            },
            "fixed_parameters": {"wavelength_nm": 1030.0},
        },
        "bo_result": {
            "status": "success",
            "model_status": "data_driven_bo",
            "recommended_parameters": {"laser_power_W": 5.0},
        },
        "parameter_units": {
            "laser_power_W": "W",
            "frequency_kHz": "kHz",
            "wavelength_nm": "nm",
        },
        "stage": "trial_cut",
    }
    payload.update(overrides)
    return payload


def test_validate_against_search_space_rejects_out_of_bounds() -> None:
    space = _base_payload()["search_space"]
    violations = _validate_against_search_space(
        {"laser_power_W": 999999.0, "wavelength_nm": 1030.0}, space
    )
    assert violations == ["laser_power_W=999999.0 outside [0.0, 10.0]"]


def test_validate_against_search_space_accepts_within_bounds() -> None:
    space = _base_payload()["search_space"]
    assert _validate_against_search_space({"laser_power_W": 5.0}, space) == []


def test_create_rejects_out_of_bounds_bo_result(memory_root) -> None:
    service = ProcessRecommendationService()
    with pytest.raises(ValueError, match="violate search space bounds"):
        service.create(
            **_base_payload(
                bo_result={
                    "status": "success",
                    "recommended_parameters": {"laser_power_W": 999999.0},
                }
            )
        )


def test_create_accepts_in_bounds_and_cam_export_passes(memory_root) -> None:
    service = ProcessRecommendationService()
    recommendation = service.create(**_base_payload())
    assert recommendation.status == "ready_for_cam"
    mapped = service.cam_parameters(recommendation.recommendation_id)
    assert mapped  # 合法值允许导出


def test_cam_export_revalidates_stored_metadata(memory_root, monkeypatch) -> None:
    """持久化后若记录被篡改为越界值，导出必须被阻止。"""
    service = ProcessRecommendationService()
    recommendation = service.create(**_base_payload())
    record = service.repository.get(recommendation.recommendation_id)
    record["complete_recipe"]["laser_power_W"] = 999999.0
    violations = _validate_recommendation_against_metadata(record)
    assert violations == ["laser_power_W=999999.0 outside [0.0, 10.0]"]
    monkeypatch.setattr(
        service.repository, "get", lambda recommendation_id: record
    )
    with pytest.raises(ValueError, match="CAM export blocked"):
        service.cam_parameters(recommendation.recommendation_id)
