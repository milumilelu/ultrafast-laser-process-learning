from __future__ import annotations

from ultrafast_memory.agent_runtime.tool_registry import (
    FOREGROUND_SAFE_TOOL_NAMES,
    _persist_parameter_recommendation,
    _recommend_process_parameters,
    _retrieve_process_memory,
    build_main_agent_tool_registry,
)


def test_open_agent_exposes_memory_without_skill_permission_gates(memory_root):
    names = {item.name for item in build_main_agent_tool_registry().list_contracts()}
    assert "retrieve_process_memory" in names
    assert "record_process_result" in names
    assert "retrieve_process_memory" in FOREGROUND_SAFE_TOOL_NAMES


def test_explicit_empty_memory_source_selection_stays_empty(memory_root):
    result = _retrieve_process_memory(
        {"sources": [], "task_context": {}}, {"session_id": "session-1"}
    )
    assert result["requested_sources"] == []
    assert result["structured_memory"]["results"] == {}
    assert result["literature_memory"] is None


def test_sidecar_rag_candidate_stays_observation_only(memory_root):
    result = _persist_parameter_recommendation(
        {
            "status": "success",
            "selected_source": "reviewed_rag",
            "process_parameters": {
                "laser_power_W": {
                    "value": 2.0,
                    "unit": "W",
                    "role": "process_setpoint",
                    "source_type": "reviewed_rag",
                    "source_refs": ["chunk-1"],
                    "authority_level": "literature_prior",
                    "validated": False,
                    "allowed_for_trial": True,
                    "allowed_for_formal_process": False,
                }
            },
            "strategy_parameters": {},
            "data_support": {"support_status": "sufficient"},
            "uncertainty": {},
            "provenance": [
                {"source_type": "reviewed_rag", "source_refs": ["chunk-1"]}
            ],
        },
        {
            "task_context": {
                "task_id": "task-1",
                "material": "SiC",
                "process_type": "surface_texturing",
            },
            "process_plan": {
                "objective": "reduce roughness",
                "controllable_variables": [
                    {"name": "laser_power_W", "role": "process_setpoint"}
                ],
            },
            "equipment_context": {
                "revision_id": "equipment-revision-1",
                "fixed_conditions": {"wavelength_nm": 1030.0},
                "tunable_capabilities": {
                    "laser_power_W": {"min": 0.5, "max": 5.0, "unit": "W"}
                },
            },
        },
        {"session_id": "session-1"},
    )

    assert result["persistence_status"] == "observation_only"
    assert "recommendation_id" not in result
    assert (
        result["process_parameters"]["laser_power_W"]
        ["allowed_for_formal_process"]
        is False
    )


def test_agent_selected_rag_strategy_does_not_force_bo(
    memory_root, monkeypatch,
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("BO should not run for rag_only")

    monkeypatch.setattr(
        "ultrafast_memory.agent_runtime.tool_registry._recommend_bo",
        fail_if_called,
    )
    monkeypatch.setattr(
        "ultrafast_memory.agent_runtime.tool_registry._recommend_rag",
        lambda payload, context: {
            "status": "success",
            "process_parameters": {
                "laser_power_W": {
                    "value": 2.0,
                    "unit": "W",
                    "source_refs": ["chunk-1"],
                    "allowed_for_trial": True,
                    "allowed_for_formal_process": False,
                }
            },
            "strategy_parameters": {},
            "provenance": [
                {"source_type": "reviewed_rag", "source_refs": ["chunk-1"]}
            ],
            "data_support": {"support_status": "sufficient"},
        },
    )
    result = _recommend_process_parameters(
        {
            "source_strategy": "rag_only",
            "task_context": {
                "task_id": "task-rag",
                "material": "SiC",
                "process_type": "surface_texturing",
            },
            "process_plan": {
                "controllable_variables": [
                    {"name": "laser_power_W", "role": "process_setpoint"}
                ]
            },
            "variables": ["laser_power_W"],
            "equipment_context": {
                "revision_id": "equipment-rag",
                "fixed_conditions": {"wavelength_nm": 1030.0},
                "tunable_capabilities": {
                    "laser_power_W": {"min": 0.5, "max": 5.0, "unit": "W"}
                },
            },
        },
        {"session_id": "session-rag"},
    )
    assert result["status"] == "success"
    assert result["source_strategy"] == "rag_only"
    assert result["selected_source"] == "reviewed_rag"
