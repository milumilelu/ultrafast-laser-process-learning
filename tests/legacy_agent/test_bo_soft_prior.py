"""E2P soft search prior 回归测试：

- approved prior 只影响候选排序，绝不缩小机器边界（硬约束不变）；
- prior 与机器边界无交集时不再抛错，而是记录 ignored_outside_machine_bounds；
- 加入 prior 后推荐点可以向先验区间偏移。
"""

from __future__ import annotations

import numpy as np

from ultrafast_bo.application.services import (
    BOSample,
    BOStatusService,
    OfflineModelingService,
    _BOCoreEngine,
)
from ultrafast_e2p.application.prior_compiler import compile_from_approved_priors


def _approved_prior(parameter: str, lower: float, upper: float, approval_id: str = "APPR-001") -> dict:
    return {
        "approval_id": approval_id,
        "parameter_name": parameter,
        "lower_bound": lower,
        "upper_bound": upper,
    }


MACHINE_BOUNDS = {
    "pulse_width_fs": [500.0, 8000.0],
    "frequency_kHz": [2.0, 200.0],
    "scan_speed_mm_s": [1.0, 200.0],
}

GATE_ALLOWED = {"knowledge_gate_decision": {"status": "allowed"}}


def _compile(priors: list[dict]) -> tuple[dict, list[str], list[dict]]:
    artifact = compile_from_approved_priors(MACHINE_BOUNDS, priors)
    return artifact.prior_spec, list(artifact.approval_ids), list(artifact.source_trace)


def test_prior_never_narrows_machine_bounds() -> None:
    prior = _approved_prior("frequency_kHz", 5.0, 20.0)
    spec, approval_ids, trace = _compile([prior])
    assert approval_ids == ["APPR-001"]
    assert trace[0]["status"] == "applied_soft"
    # 机器边界本身不变
    assert MACHINE_BOUNDS["frequency_kHz"] == [2.0, 200.0]
    prefs = spec["range_preferences"]
    assert prefs[0]["parameter"] == "frequency_kHz"
    assert prefs[0]["lower"] == 5.0 and prefs[0]["upper"] == 20.0


def test_prior_outside_machine_bounds_is_ignored_not_an_error() -> None:
    prior = _approved_prior("frequency_kHz", 500.0, 1000.0)
    spec, approval_ids, trace = _compile([prior])
    assert approval_ids == []
    assert trace[0]["status"] == "ignored_outside_machine_bounds"
    assert spec["range_preferences"] == []


def test_prior_intersection_is_clipped_to_machine_bounds() -> None:
    prior = _approved_prior("frequency_kHz", 150.0, 500.0)
    spec, _, _ = _compile([prior])
    preference = spec["range_preferences"][0]
    assert preference["lower"] == 150.0
    assert preference["upper"] == 200.0


def _samples() -> list[BOSample]:
    rng = np.random.default_rng(7)
    rows = []
    for index in range(14):
        frequency = float(rng.uniform(2, 200))
        pulse = float(rng.uniform(500, 8000))
        speed = float(rng.uniform(1, 200))
        depth = 40.0 - 0.12 * abs(frequency - 10) + 0.01 * (pulse / 1000) + rng.normal(0, 0.3)
        rows.append(
            BOSample(
                sample_id=f"s{index}",
                x_parameters={
                    "pulse_width_fs": pulse,
                    "frequency_kHz": frequency,
                    "scan_speed_mm_s": speed,
                },
                y_metrics={"depth_um": depth},
            )
        )
    return rows


def test_soft_prior_shifts_recommendation_within_machine_bounds() -> None:
    engine = _BOCoreEngine()
    task = {
        "objective_metric": "depth_um",
        "random_seed": 11,
        "candidate_count": 512,
        **GATE_ALLOWED,
    }
    machine_context = {"active": True, "machine_bounds": MACHINE_BOUNDS, "revision_id": "rev-1"}

    vanilla = engine.recommend(task, _samples(), machine_context, approved_priors=[])

    prior = _approved_prior("frequency_kHz", 5.0, 12.0)
    with_prior = engine.recommend(task, _samples(), machine_context, approved_priors=[prior])

    assert vanilla["model_status"] == "hybrid_rule_bo"
    # 机器边界从未被 prior 收缩：推荐参数必须仍在原机器范围内
    for name, (lower, upper) in MACHINE_BOUNDS.items():
        assert lower <= with_prior["recommended_parameters"][name] <= upper

    trace = with_prior["audit_trace"]
    assert any(item.get("status") == "applied_soft" for item in trace)
    assert any(item.get("status") == "applied_governed_artifact" for item in trace)
    assert with_prior["knowledge_approval_ids"] == ["APPR-001"]
    governed = with_prior["governed_prior"]
    assert governed is not None
    assert governed["approval_ids"] == ["APPR-001"]
    assert governed["content_hash"]
    assert governed["verification"] == "self_attested"


def test_search_prior_reported_in_model_result() -> None:
    service = OfflineModelingService()
    spec, _, _ = _compile([_approved_prior("frequency_kHz", 5.0, 12.0)])
    result = service.fit_and_recommend(
        _samples(),
        MACHINE_BOUNDS,
        {"objective_metric": "depth_um", "random_seed": 11, "candidate_count": 512},
        BOStatusService().status_for_count(14),
        prior_spec=spec,
    )
    assert result["search_prior_applied"] is True
    assert result["prior_spec"]["range_preferences"][0]["parameter"] == "frequency_kHz"


def test_unverified_approval_id_is_ignored_when_verifier_provided() -> None:
    """P0：approval_id 不存在于 approval repository 时，先验必须被拒绝。"""
    engine = _BOCoreEngine()
    task = {"objective_metric": "depth_um", "random_seed": 11, **GATE_ALLOWED}
    machine_context = {"active": True, "machine_bounds": MACHINE_BOUNDS, "revision_id": "rev-1"}
    prior = _approved_prior("frequency_kHz", 5.0, 12.0, approval_id="GHOST-APPROVAL")

    result = engine.recommend(
        task, _samples(), machine_context, approved_priors=[prior],
        approval_verifier=lambda approval_id: approval_id != "GHOST-APPROVAL",
    )
    assert result["governed_prior"]["approval_ids"] == []
    assert result["governed_prior"]["verification"] == "repository_verified"
    assert any(
        item.get("status") == "ignored_unverified" for item in result["audit_trace"]
    )


def test_governed_prior_is_required_for_literature_influence() -> None:
    """P0：带 approval 的 prior 必须过 KnowledgeUseGate，否则 BO 被阻塞。"""
    engine = _BOCoreEngine()
    task = {"objective_metric": "depth_um", "random_seed": 11}
    machine_context = {"active": True, "machine_bounds": MACHINE_BOUNDS, "revision_id": "rev-1"}
    prior = _approved_prior("frequency_kHz", 5.0, 12.0)

    blocked = engine.recommend(task, _samples(), machine_context, approved_priors=[prior])
    assert blocked["model_status"] == "blocked"
    assert any(
        item.get("step") == "knowledge_use_gate" for item in blocked["audit_trace"]
    )
