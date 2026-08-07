from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from ultrafast_bo.application.governance import BOEligibilityService
from ultrafast_integrations.storage.process_recommendation_repository import (
    ProcessRecommendationRepository,
)
from ultrafast_knowledge.governance_review.review_queue import create_review_task
from ultrafast_memory.core.ids import stable_id
from ultrafast_memory.core.time_utils import utc_now_iso
from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection
from ultrafast_memory.equipment.bounds import (
    safety_bounds_from_equipment,
    validate_candidate_within_bounds,
)
from ultrafast_memory.process_workflow.closure import bo_sample_eligibility
from ultrafast_memory.process_workflow.repository import ProcessWorkflowRepository


class ProcessLearningService:
    """Record facts first, then create reviewable learning candidates.

    The service never promotes knowledge or training samples by itself. LLM
    interpretation is stored only as a candidate linked to the canonical result.
    """

    def record(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        init_database()
        working = context.get("working_context") or {}
        task = dict(working.get("task") or context.get("task_spec") or {})
        now = utc_now_iso()
        task_id = str(payload.get("task_id") or task.get("task_id") or context.get("session_id") or "task")
        measurements = dict(payload.get("measurements") or {})
        actual_parameters = dict(
            payload.get("machine_actual_parameters")
            or payload.get("actual_parameters")
            or payload.get("parameters")
            or {}
        )
        equipment = dict(
            payload.get("equipment_context")
            or working.get("equipment_context")
            or context.get("equipment_snapshot")
            or {}
        )
        recommendation_id = payload.get("recommendation_id") or _latest_recommendation_id(working)
        result_id = str(
            payload.get("result_id")
            or stable_id(
                "process-result",
                task_id,
                payload.get("run_id"),
                payload.get("execution_id"),
                actual_parameters,
                measurements,
                now,
            )
        )
        supplied_execution_id = payload.get("execution_id")
        internal_execution_id = str(
            supplied_execution_id or stable_id("unlinked-execution", result_id)
        )
        normalized_parameters = _numeric_values(actual_parameters)
        normalized_measurements = _numeric_values(measurements)
        bounds_report = validate_candidate_within_bounds(
            normalized_parameters, safety_bounds_from_equipment(equipment)
        )
        quality_decision = _quality_decision(payload)
        validation_status = str(payload.get("validation_status") or "pending_review")
        material = _material(task)
        process_type = _process_type(task)
        run_id = payload.get("run_id")
        record = {
            "experiment_id": result_id,
            "result_id": result_id,
            "task_id": task_id,
            "task_revision": task.get("revision") or working.get("task_revision"),
            "recommendation_id": recommendation_id,
            "run_id": run_id,
            "execution_id": internal_execution_id,
            "supplied_execution_id": supplied_execution_id,
            "execution_linkage": "supplied" if supplied_execution_id else "unlinked_external_result",
            "equipment_revision": payload.get("equipment_revision") or equipment.get("revision_id"),
            "material": material,
            "material_grade": _task_value(task, "material_grade", "grade"),
            "material_batch": payload.get("material_batch"),
            "process_type": process_type,
            "machine_actual_parameters": actual_parameters,
            "normalized_parameters": normalized_parameters,
            "measurements": measurements,
            "normalized_measurements": normalized_measurements,
            "measurement_method": payload.get("measurement_method"),
            "instrument_ids": payload.get("instrument_ids") or [],
            "quality_decision": quality_decision,
            "constraint_results": payload.get("constraint_results") or {},
            "fidelity_level": payload.get("fidelity_level"),
            "run_status": payload.get("run_status") or "unknown",
            "alarms": payload.get("alarms") or [],
            "defects": payload.get("defects") or [],
            "operator_note": payload.get("operator_note") or payload.get("note"),
            "attachments": payload.get("attachments") or [],
            "validation_status": validation_status,
            "validated_by": payload.get("validated_by"),
            "bounds_validation": bounds_report,
            "created_at": now,
        }
        candidate = {
            **record,
            "execution_id": supplied_execution_id,
            "raw_machine_actual_parameters": actual_parameters,
            "machine_actual_parameters": normalized_parameters,
            "raw_measurements": measurements,
            "measurements": normalized_measurements,
            "raw_feedback_id": result_id,
            "cam_applied_parameters": payload.get("cam_applied_parameters") or {},
            "out_of_bounds": not bounds_report["valid"],
            "manual_exclusion": bool(payload.get("manual_exclusion")),
            "duplicate": bool(payload.get("duplicate")),
            "replicate_id": payload.get("replicate_id"),
        }
        eligibility = self._assess_bo_candidate(candidate)
        record["bo_eligible"] = eligibility["eligible"]
        ProcessWorkflowRepository().save_experiment(record)

        bo_candidate_id = stable_id("bo-sample-candidate", result_id)
        ProcessRecommendationRepository().save_training_candidate(
            candidate_id=bo_candidate_id,
            candidate=candidate,
            eligibility=eligibility,
            status="eligible_pending_approval" if eligibility["eligible"] else "ineligible",
            created_at=now,
            recommendation_id=str(recommendation_id) if recommendation_id else None,
            raw_feedback_id=result_id,
        )
        knowledge_candidates = self._create_knowledge_candidates(record)
        return {
            "result_record": record,
            "bo_training_candidate": {
                "candidate_id": bo_candidate_id,
                "status": "eligible_pending_approval" if eligibility["eligible"] else "ineligible",
                "eligibility": eligibility,
                "training_sample_created": False,
                "human_approval_required": eligibility["eligible"],
            },
            "knowledge_candidates": knowledge_candidates,
            "automatic_promotions": [],
        }

    @staticmethod
    def _assess_bo_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
        governance = BOEligibilityService().assess(candidate).to_dict()
        closure = bo_sample_eligibility(
            {
                **candidate,
                "parameters": candidate.get("machine_actual_parameters") or {},
                "measurements": candidate.get("measurements") or {},
            }
        )
        reasons = list(dict.fromkeys(
            [*governance["blocking_reasons"], *closure["reasons"]]
        ))
        if candidate.get("validation_status") == "valid" and not candidate.get("validated_by"):
            reasons.append("validated_by_required")
        if not candidate.get("recommendation_id"):
            reasons.append("recommendation_trace_required")
        if not candidate.get("run_id"):
            reasons.append("run_id_required")
        reasons = list(dict.fromkeys(reasons))
        return {
            **governance,
            "eligible": not reasons,
            "blocking_reasons": reasons,
            "closure_report": closure,
            "policy_version": "human-governed-process-learning-v1",
        }

    @staticmethod
    def _create_knowledge_candidates(record: dict[str, Any]) -> list[dict[str, Any]]:
        statements: list[tuple[str, str]] = []
        note = record.get("operator_note")
        if isinstance(note, str) and note.strip():
            statements.append(("operator_observation", note.strip()))
        for defect in record.get("defects") or []:
            if isinstance(defect, str) and defect.strip():
                statements.append(("observed_defect", defect.strip()))
            elif isinstance(defect, dict) and defect:
                statements.append((
                    "observed_defect",
                    json.dumps(defect, ensure_ascii=False, sort_keys=True),
                ))
        created: list[dict[str, Any]] = []
        for evidence_type, statement in statements:
            source_id = stable_id("process-result-source", record["result_id"], evidence_type, statement)
            candidate_id = stable_id("knowledge-candidate", source_id, statement)
            digest = hashlib.sha256(statement.encode("utf-8")).hexdigest()
            with get_connection() as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO external_source_artifact (
                      source_id, source_type, title, url, doi, authors, published_at,
                      accessed_at, provider, raw_snippet, local_snapshot_path,
                      content_hash, credibility_score, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        "process_result",
                        f"加工结果 {record['result_id']}",
                        None,
                        None,
                        None,
                        record["created_at"],
                        record["created_at"],
                        "local_operator_input",
                        statement,
                        None,
                        digest,
                        None,
                        "local_record",
                    ),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO knowledge_candidate (
                      candidate_id, source_id, claim, material, process_type,
                      component_type, parameter_json, condition_json,
                      usable_for_json, not_usable_for_json, evidence_type,
                      confidence, status, review_status, risk_level,
                      suggested_action, conflict_flag, duplicate_of,
                      source_quality_score, created_at, reviewed_by, review_comment,
                      paper_id, evidence_level, extraction_method
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        source_id,
                        statement,
                        record.get("material"),
                        record.get("process_type"),
                        None,
                        json.dumps({}, ensure_ascii=False),
                        json.dumps(
                            {
                                "result_id": record["result_id"],
                                "run_id": record.get("run_id"),
                                "equipment_revision": record.get("equipment_revision"),
                                "material_batch": record.get("material_batch"),
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(["literature_background", "process_planning"], ensure_ascii=False),
                        json.dumps(
                            ["parameter_recommendation", "formal_process", "bo_training"],
                            ensure_ascii=False,
                        ),
                        evidence_type,
                        None,
                        "pending_review",
                        "pending_review",
                        "medium",
                        "accept_to_rag",
                        0,
                        None,
                        None,
                        record["created_at"],
                        None,
                        None,
                        None,
                        "unreviewed_process_experience",
                        "operator_input",
                    ),
                )
                connection.commit()
            review = create_review_task(candidate_id, "medium", "accept_to_rag")
            created.append(
                {
                    "candidate_id": candidate_id,
                    "review_id": review["review_id"],
                    "status": "pending_review",
                    "claim": statement,
                    "allowed_uses_before_review": [],
                }
            )
        return created


def _latest_recommendation_id(working: dict[str, Any]) -> str | None:
    for observation in reversed(list(working.get("observations") or [])):
        if not isinstance(observation, dict):
            continue
        data = observation.get("data") if isinstance(observation.get("data"), dict) else observation
        value = data.get("recommendation_id") if isinstance(data, dict) else None
        if value:
            return str(value)
    return None


def _numeric_values(values: dict[str, Any]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for name, raw in values.items():
        value = raw.get("value") if isinstance(raw, dict) else raw
        if isinstance(value, bool) or value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            normalized[str(name)] = number
    return normalized


def _quality_decision(payload: dict[str, Any]) -> str | None:
    explicit = payload.get("quality_decision")
    if explicit in {"PASS", "FAIL", "NEEDS_REVIEW"}:
        return str(explicit)
    constraints = payload.get("constraint_results")
    if isinstance(constraints, dict) and constraints:
        values = [value for value in constraints.values() if isinstance(value, bool)]
        if values:
            return "PASS" if all(values) else "FAIL"
    return None


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


def _task_value(task: dict[str, Any], direct_key: str, nested_key: str) -> Any:
    if task.get(direct_key) is not None:
        return task[direct_key]
    material = task.get("material")
    return material.get(nested_key) if isinstance(material, dict) else None
