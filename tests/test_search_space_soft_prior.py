"""SearchSpaceBuilder 不得把 approved prior 编译为硬约束（P0 回归测试）。

机器边界是唯一硬约束；approved process prior 只能作为 E2P 软偏好
（prior_spec），绝不能通过 max/min 区间求交缩小可行域。
"""

from __future__ import annotations

from ultrafast_bo.application.search_space import SearchSpaceBuilder
from ultrafast_bo.domain.search_space import ParameterMode


def _policy(parameter: str, lower: float, upper: float) -> dict:
    return {
        parameter: {
            "mode": ParameterMode.BOUNDED.value,
            "lower": lower,
            "upper": upper,
            "step": None,
            "condition": {},
            "unit": None,
        }
    }


EQUIPMENT = {
    "machine_bounds": {"frequency_kHz": [2.0, 200.0]},
    "revision_id": "rev-1",
}


def test_prior_does_not_narrow_equipment_bounds() -> None:
    builder = SearchSpaceBuilder()
    # prior 区间 [5, 20] 远小于设备 [2, 200]：旧实现会把它硬缩为 [5, 20]
    prior = {
        "prior_id": "P-1",
        "approval_id": "APPR-1",
        "parameter_name": "frequency_kHz",
        "lower_bound": 5.0,
        "upper_bound": 20.0,
        "status": "approved",
    }
    space = builder.compile(
        task_spec={},
        equipment_snapshot=EQUIPMENT,
        parameter_policy=_policy("frequency_kHz", 2.0, 200.0),
        approved_priors=[prior],
        current_recipe={},
        trial_mode="trial_cut",
    )
    variable = space.variables["frequency_kHz"]
    # 硬边界保持不变
    assert variable["lower"] == 2.0
    assert variable["upper"] == 200.0
    # 先验作为软偏好随搜索空间一起返回；approval ≠ strength：
    # 未提供 transfer_strength 时使用中性 medium（0.5），不默认 strong。
    preferences = space.prior_spec["range_preferences"]
    assert preferences[0]["parameter"] == "frequency_kHz"
    assert preferences[0]["lower"] == 5.0
    assert preferences[0]["upper"] == 20.0
    assert preferences[0]["fixed_weight"] == 0.5
    assert preferences[0]["strength"] == "medium"
    # trace 记录为 soft，而非边界来源
    assert any(entry.get("status") == "applied_soft" for entry in space.source_trace)
    assert not any(
        entry.get("active_lower_source") == "approved_process_prior"
        for entry in space.source_trace
    )


def test_prior_outside_machine_bounds_is_ignored_not_blocking() -> None:
    builder = SearchSpaceBuilder()
    prior = {
        "prior_id": "P-2",
        "approval_id": "APPR-2",
        "parameter_name": "frequency_kHz",
        "lower_bound": 500.0,
        "upper_bound": 1000.0,
        "status": "approved",
    }
    space = builder.compile(
        task_spec={},
        equipment_snapshot=EQUIPMENT,
        parameter_policy=_policy("frequency_kHz", 2.0, 200.0),
        approved_priors=[prior],
        current_recipe={},
        trial_mode="trial_cut",
    )
    assert space.feasibility_status == "ready"
    assert space.variables["frequency_kHz"]["lower"] == 2.0
    assert space.variables["frequency_kHz"]["upper"] == 200.0
    assert space.prior_spec["range_preferences"] == []
    assert any(entry.get("status") == "ignored_outside_machine_bounds" for entry in space.source_trace)


def test_explicit_transfer_strength_is_honored() -> None:
    """transfer_strength 显式提供时按该强度定权（approval 仍是权限门）。"""
    builder = SearchSpaceBuilder()
    prior = {
        "prior_id": "P-5",
        "approval_id": "APPR-5",
        "parameter_name": "frequency_kHz",
        "lower_bound": 5.0,
        "upper_bound": 20.0,
        "status": "approved",
        "transfer_strength": "strong",
    }
    space = builder.compile(
        task_spec={},
        equipment_snapshot=EQUIPMENT,
        parameter_policy=_policy("frequency_kHz", 2.0, 200.0),
        approved_priors=[prior],
        current_recipe={},
        trial_mode="trial_cut",
    )
    preference = space.prior_spec["range_preferences"][0]
    assert preference["strength"] == "strong"
    assert preference["fixed_weight"] == 1.0
    assert space.variables["frequency_kHz"]["lower"] == 2.0


def test_unapproved_prior_is_warned_and_ignored() -> None:
    builder = SearchSpaceBuilder()
    prior = {
        "prior_id": "P-3",
        "parameter_name": "frequency_kHz",
        "lower_bound": 5.0,
        "upper_bound": 20.0,
        "status": "draft",
    }
    space = builder.compile(
        task_spec={},
        equipment_snapshot=EQUIPMENT,
        parameter_policy=_policy("frequency_kHz", 2.0, 200.0),
        approved_priors=[prior],
        current_recipe={},
        trial_mode="trial_cut",
    )
    assert space.prior_spec["range_preferences"] == []
    assert any("unapproved_prior_ignored" in warning for warning in space.warnings)
    assert space.variables["frequency_kHz"]["lower"] == 2.0


def test_prior_flows_into_constrained_bo_as_governed_artifact() -> None:
    """ConstrainedBO 必须消费治理容器（artifact），而不是裸 dict 或硬边界。"""
    from ultrafast_bo.application.constrained_service import (
        ConstrainedBORecommendationService,
    )

    class _SpyBO:
        def __init__(self):
            self.last_governed = None
            self.last_approved = None

        def recommend(self, *args, **kwargs):
            self.last_governed = kwargs.get("governed_prior")
            self.last_approved = kwargs.get("approved_priors")
            return {"status": "ready", "recommended_parameters": {}, "prediction": {}, "acquisition": {}, "warnings": [], "blocking_reasons": []}

    spy = _SpyBO()
    builder = SearchSpaceBuilder()
    prior = {
        "prior_id": "P-4",
        "approval_id": "APPR-4",
        "parameter_name": "frequency_kHz",
        "lower_bound": 5.0,
        "upper_bound": 20.0,
        "status": "approved",
    }
    service = ConstrainedBORecommendationService(builder=builder, bo=spy)
    service.recommend(
        task_spec={"material": "SiC", "process_type": "milling", "objective_metric": "depth_um"},
        samples=[],
        equipment_snapshot=EQUIPMENT,
        parameter_policy=_policy("frequency_kHz", 2.0, 200.0),
        approved_priors=[prior],
        trial_mode="trial_cut",
    )
    assert spy.last_governed is not None
    assert spy.last_governed.prior_spec["range_preferences"][0]["parameter"] == "frequency_kHz"
    assert spy.last_governed.approval_ids == ("APPR-4",)
    assert spy.last_governed.content_hash
    assert spy.last_approved == [prior], "approved priors 仍需透传（BO 侧验证）"
