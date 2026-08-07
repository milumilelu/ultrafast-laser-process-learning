from __future__ import annotations

import json
from typing import Any

from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection


DEFAULT_MEMORY_SOURCES = (
    "experiments",
    "bo_samples",
    "validated_rules",
    "reviewed_experience",
)


class ProcessMemorySearchService:
    """Read structured process memory without forcing one task ontology."""

    def search(
        self,
        task_context: dict[str, Any] | None,
        *,
        sources: list[str] | tuple[str, ...] | None = None,
        query: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        init_database()
        task = dict(task_context or {})
        material = _material(task)
        process_type = _process_type(task)
        selected = tuple(
            dict.fromkeys(DEFAULT_MEMORY_SOURCES if sources is None else sources)
        )
        unsupported = sorted(set(selected) - set(DEFAULT_MEMORY_SOURCES))
        if unsupported:
            return {
                "status": "validation_error",
                "summary": "包含不支持的结构化记忆来源。",
                "unsupported_sources": unsupported,
                "supported_sources": list(DEFAULT_MEMORY_SOURCES),
            }
        safe_limit = max(1, min(int(limit), 20))
        with get_connection(read_only=True) as connection:
            results: dict[str, list[dict[str, Any]]] = {}
            if "experiments" in selected:
                results["experiments"] = self._experiments(
                    connection, material, process_type, safe_limit
                )
            if "bo_samples" in selected:
                results["bo_samples"] = self._bo_samples(
                    connection, material, process_type, safe_limit
                )
            if "validated_rules" in selected:
                results["validated_rules"] = self._validated_rules(
                    connection, material, process_type, query, safe_limit
                )
            if "reviewed_experience" in selected:
                results["reviewed_experience"] = self._reviewed_experience(
                    connection,
                    material,
                    process_type,
                    query,
                    safe_limit,
                )
        counts = {name: len(items) for name, items in results.items()}
        total = sum(counts.values())
        return {
            "status": "success" if total else "insufficient_data",
            "summary": (
                f"找到 {total} 条可追溯的结构化历史记忆。"
                if total
                else "未找到匹配的结构化历史记忆；这不阻止继续形成带假设的方案。"
            ),
            "filters": {"material": material, "process_type": process_type},
            "source_counts": counts,
            "results": results,
            "provenance": [
                {
                    "source_type": "structured_process_memory",
                    "tables": [
                        "process_task/process_run/process_recipe/measurement_record",
                        "experiment_record",
                        "bo_training_sample",
                        "validated_rule",
                        "experience_candidate/knowledge_candidate",
                    ],
                }
            ],
        }

    @staticmethod
    def _experiments(
        connection,
        material: str | None,
        process_type: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT r.run_id, r.task_id, r.machine_id, r.operator_id,
                   r.start_time, r.end_time, r.run_status, r.alarm_count,
                   r.abnormal_flag, r.abnormal_summary,
                   t.material, t.material_grade, t.component_type,
                   t.geometry_json, t.target_json,
                   p.recipe_id, p.process_type, p.parameters_json,
                   p.laser_wavelength_nm, p.pulse_width_fs, p.laser_power_W,
                   p.frequency_kHz, p.scan_speed_mm_s, p.passes,
                   p.hatch_spacing_um, p.layer_step_um, p.focus_offset_um,
                   p.fill_pattern, p.path_strategy
            FROM process_run r
            LEFT JOIN process_task t ON t.task_id = r.task_id
            LEFT JOIN process_recipe p ON p.recipe_id = r.recipe_id
            WHERE (? IS NULL OR lower(t.material) = lower(?))
              AND (? IS NULL OR lower(p.process_type) = lower(?))
            ORDER BY COALESCE(r.end_time, r.start_time) DESC
            LIMIT ?
            """,
            (material, material, process_type, process_type, limit),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for raw in rows:
            item = dict(raw)
            run_id = item["run_id"]
            measurements = connection.execute(
                """
                SELECT measurement_id, metric_name, metric_value, metric_unit,
                       measurement_method, instrument_id, measured_at, valid_flag
                FROM measurement_record
                WHERE run_id = ?
                ORDER BY measured_at, measurement_id
                """,
                (run_id,),
            ).fetchall()
            for field in ("geometry_json", "target_json", "parameters_json"):
                item[field.removesuffix("_json")] = _load_json(item.pop(field, None), {})
            item["measurements"] = [dict(row) for row in measurements]
            item["source_refs"] = [run_id, *[str(row["measurement_id"]) for row in measurements]]
            item["record_type"] = "process_run"
            result.append(item)

        recorded = connection.execute(
            """
            SELECT experiment_id, task_id, execution_id, record_json,
                   validation_status, bo_eligible, created_at
            FROM experiment_record
            WHERE (? IS NULL OR lower(json_extract(record_json, '$.material')) = lower(?))
              AND (? IS NULL OR lower(json_extract(record_json, '$.process_type')) = lower(?))
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (material, material, process_type, process_type, limit),
        ).fetchall()
        for raw in recorded:
            row = dict(raw)
            record = _load_json(row.pop("record_json", None), {})
            item = {
                **record,
                **row,
                "bo_eligible": bool(row["bo_eligible"]),
                "record_type": "experiment_record",
            }
            item["source_refs"] = list(
                dict.fromkeys(
                    str(value)
                    for value in (
                        item.get("experiment_id"),
                        item.get("run_id"),
                        item.get("recommendation_id"),
                    )
                    if value
                )
            )
            result.append(item)
        result.sort(
            key=lambda item: str(
                item.get("created_at")
                or item.get("end_time")
                or item.get("start_time")
                or ""
            ),
            reverse=True,
        )
        return result[:limit]

    @staticmethod
    def _bo_samples(connection, material: str | None, process_type: str | None,
                    limit: int) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT * FROM bo_training_sample
            WHERE valid_for_training = 1
              AND (? IS NULL OR lower(material) = lower(?))
              AND (? IS NULL OR lower(process_type) = lower(?))
            ORDER BY added_at DESC
            LIMIT ?
            """,
            (material, material, process_type, process_type, limit),
        ).fetchall()
        result = []
        for raw in rows:
            item = dict(raw)
            item["x_parameters"] = _load_json(item.pop("x_parameters_json", None), {})
            item["y_metrics"] = _load_json(item.pop("y_metrics_json", None), {})
            item["constraints"] = _load_json(item.pop("constraints_json", None), {})
            item["source_refs"] = [item["sample_id"], item["run_id"]]
            result.append(item)
        return result

    @staticmethod
    def _validated_rules(connection, material: str | None, process_type: str | None,
                         query: str | None, limit: int) -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%" if query and query.strip() else None
        rows = connection.execute(
            """
            SELECT * FROM validated_rule
            WHERE COALESCE(status, 'active') NOT IN ('rejected', 'revoked', 'inactive')
              AND (? IS NULL OR material IS NULL OR lower(material) = lower(?))
              AND (? IS NULL OR process_type IS NULL OR lower(process_type) = lower(?))
              AND (? IS NULL OR rule_text LIKE ?)
            ORDER BY COALESCE(updated_at, created_at) DESC
            LIMIT ?
            """,
            (material, material, process_type, process_type, pattern, pattern, limit),
        ).fetchall()
        result = []
        for raw in rows:
            item = dict(raw)
            for field, default in (
                ("condition_json", {}),
                ("recommended_action_json", {}),
                ("supporting_case_ids", []),
                ("counter_case_ids", []),
            ):
                item[field.removesuffix("_json")] = _load_json(item.pop(field, None), default)
            item["source_refs"] = [item["rule_id"]]
            result.append(item)
        return result

    @staticmethod
    def _reviewed_experience(
        connection,
        material: str | None,
        process_type: str | None,
        query: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%" if query and query.strip() else None
        rows = connection.execute(
            """
            SELECT * FROM experience_candidate
            WHERE status = 'accepted'
              AND (? IS NULL OR extracted_claim LIKE ?)
            ORDER BY extracted_at DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        ).fetchall()
        result = []
        for raw in rows:
            item = dict(raw)
            item["evidence"] = _load_json(item.pop("evidence_json", None), {})
            item["source_artifact_ids"] = _load_json(
                item.get("source_artifact_ids"), []
            )
            item["source_refs"] = [item["candidate_id"]]
            item["record_type"] = "experience_candidate"
            result.append(item)

        reviewed = connection.execute(
            """
            SELECT * FROM knowledge_candidate
            WHERE status = 'accepted'
              AND review_status IN ('accepted_to_rag', 'accepted_as_literature_evidence')
              AND (? IS NULL OR material IS NULL OR lower(material) = lower(?))
              AND (? IS NULL OR process_type IS NULL OR lower(process_type) = lower(?))
              AND (? IS NULL OR claim LIKE ?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (material, material, process_type, process_type, pattern, pattern, limit),
        ).fetchall()
        for raw in reviewed:
            item = dict(raw)
            for field, default in (
                ("parameter_json", {}),
                ("condition_json", {}),
                ("usable_for_json", []),
                ("not_usable_for_json", []),
            ):
                item[field.removesuffix("_json")] = _load_json(
                    item.pop(field, None), default
                )
            item["source_refs"] = [
                str(value)
                for value in (item.get("candidate_id"), item.get("source_id"))
                if value
            ]
            item["record_type"] = "knowledge_candidate"
            result.append(item)
        result.sort(
            key=lambda item: str(
                item.get("created_at") or item.get("extracted_at") or ""
            ),
            reverse=True,
        )
        return result[:limit]


def _material(task: dict[str, Any]) -> str | None:
    value = task.get("material")
    if isinstance(value, dict):
        value = value.get("name")
    return str(value).strip() if value not in (None, "") else None


def _process_type(task: dict[str, Any]) -> str | None:
    geometry = task.get("geometry") if isinstance(task.get("geometry"), dict) else {}
    value = (
        task.get("process_type")
        or task.get("process_intent")
        or task.get("task_type")
        or geometry.get("feature_type")
    )
    return str(value).strip() if value not in (None, "") else None


def _load_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
