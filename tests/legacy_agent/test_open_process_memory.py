from __future__ import annotations

import json

from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection
from ultrafast_memory.process_memory import ProcessMemorySearchService
from ultrafast_memory.process_learning import ProcessLearningService


def test_structured_memory_keeps_sources_and_authority_separate(memory_root):
    init_database()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO process_task (
              task_id, component_type, material, material_grade, geometry_json,
              target_json, priority_mode, created_by, created_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-1", "coupon", "SiC", "4H", "{}", "{}",
                "quality", "test", "2026-01-01T00:00:00Z", "completed",
            ),
        )
        connection.execute(
            """
            INSERT INTO process_recipe (
              recipe_id, task_id, process_type, laser_power_W, frequency_kHz,
              scan_speed_mm_s, parameters_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "recipe-1", "task-1", "surface_texturing", 2.0, 100.0,
                200.0, json.dumps({"passes": 2}), "2026-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO process_run (
              run_id, task_id, recipe_id, start_time, end_time, run_status,
              alarm_count, abnormal_flag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run-1", "task-1", "recipe-1", "2026-01-01T00:00:00Z",
                "2026-01-01T00:10:00Z", "completed", 0, 0,
            ),
        )
        connection.execute(
            """
            INSERT INTO measurement_record (
              measurement_id, run_id, metric_name, metric_value, metric_unit,
              measurement_method, measured_at, valid_flag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("measurement-1", "run-1", "Sa_um", 0.4, "um", "confocal", "2026-01-01T01:00:00Z", 1),
        )
        connection.execute(
            """
            INSERT INTO bo_training_sample (
              sample_id, run_id, material, process_type, x_parameters_json,
              y_metrics_json, constraints_json, valid_for_training, invalid_reason,
              added_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sample-1", "run-1", "SiC", "surface_texturing",
                json.dumps({"laser_power_W": 2.0}), json.dumps({"Sa_um": 0.4}),
                "{}", 1, None, "2026-01-01T02:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO validated_rule (
              rule_id, material, process_type, condition_json, rule_text,
              recommended_action_json, supporting_case_ids, counter_case_ids,
              confidence, status, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rule-1", "SiC", "surface_texturing", "{}", "避免过度热积累",
                "{}", json.dumps(["run-1"]), "[]", 0.8, "active", 1,
                "2026-01-01T03:00:00Z", "2026-01-01T03:00:00Z",
            ),
        )
        connection.commit()

    result = ProcessMemorySearchService().search(
        {"material": {"name": "SiC"}, "process_type": "surface_texturing"}
    )

    assert result["status"] == "success"
    assert result["source_counts"]["experiments"] == 1
    assert result["source_counts"]["bo_samples"] == 1
    assert result["source_counts"]["validated_rules"] == 1
    assert result["results"]["experiments"][0]["source_refs"] == [
        "run-1",
        "measurement-1",
    ]
    assert result["results"]["validated_rules"][0]["rule_id"] == "rule-1"


def test_empty_source_selection_does_not_silently_search_everything(memory_root):
    init_database()
    result = ProcessMemorySearchService().search({}, sources=[])
    assert result["source_counts"] == {}
    assert result["results"] == {}
    assert result["status"] == "insufficient_data"


def test_recorded_result_is_retrievable_as_structured_memory(memory_root):
    outcome = ProcessLearningService().record(
        {
            "measurements": {"Sa_um": 0.5},
            "machine_actual_parameters": {"laser_power_W": 2.0},
            "operator_note": "边缘有轻微崩裂。",
        },
        {
            "session_id": "session-2",
            "working_context": {
                "task": {
                    "task_id": "task-2",
                    "material": {"name": "SiC"},
                    "process_type": "surface_texturing",
                },
                "equipment_context": {},
            },
        },
    )

    result = ProcessMemorySearchService().search(
        {"material": "SiC", "process_type": "surface_texturing"},
        sources=["experiments"],
    )

    assert result["status"] == "success"
    recorded = next(
        item
        for item in result["results"]["experiments"]
        if item["record_type"] == "experiment_record"
    )
    assert recorded["experiment_id"] == outcome["result_record"]["experiment_id"]
    assert recorded["measurements"] == {"Sa_um": 0.5}
