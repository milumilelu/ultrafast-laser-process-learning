from __future__ import annotations

from ultrafast_memory.agent_runtime.tool_registry import _recommend_bo, _record_result


class RecordingGateway:
    def __init__(self):
        self.observations = []

    def save_observation(self, observation):
        self.observations.append(observation)
        return observation


def test_agent_bo_fails_closed_without_topic2_contract(memory_root):
    result = _recommend_bo(
        {"approved_priors": [{"prior_spec": {"range_preferences": []}}]},
        {"session_id": "session-boundary"},
    )

    assert result["status"] == "insufficient_data"
    assert result["allowed_for_trial"] is False
    assert result["data_support"]["model_mode"] == "topic2_contract_required"


def test_process_result_is_written_through_topic2_gateway(memory_root):
    gateway = RecordingGateway()
    result = _record_result(
        {"measurements": {"depth_um": 10.2}},
        {"session_id": "session-boundary", "_topic2_gateway": gateway},
    )

    assert result["status"] in {"success", "partial"}
    assert gateway.observations[0]["facts"]["measurements"] == {"depth_um": 10.2}
    assert gateway.observations[0]["review_status"] == "pending"
    assert result["automatic_promotions"] == []
