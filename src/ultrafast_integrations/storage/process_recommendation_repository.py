from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ultrafast_domain.process.recommendation import ProcessRecommendation
from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection


class ProcessRecommendationRepository:
    """SQLite persistence adapter; application policy stays outside integrations."""

    def __init__(self) -> None:
        init_database()

    def next_iteration(self, task_id: str) -> int:
        # BEGIN IMMEDIATE 立即获取写锁：并发事务串行化，MAX+1 不再竞态。
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT COALESCE(MAX(iteration_number),0)+1 FROM process_recommendation WHERE task_id=?",
                (task_id,),
            ).fetchone()
            next_value = int(row[0])
            conn.commit()
        return next_value

    def save(self, value: ProcessRecommendation) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO process_recommendation VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    value.recommendation_id, value.task_id, value.workflow_id,
                    value.iteration_number, value.parent_recommendation_id, value.status,
                    json.dumps(value.to_dict(), ensure_ascii=False), value.created_at, value.expires_at,
                ),
            )
            conn.commit()

    def get(self, recommendation_id: str) -> dict[str, Any]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT recommendation_json FROM process_recommendation WHERE recommendation_id=?",
                (recommendation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(recommendation_id)
        return json.loads(row[0])

    def save_cam_export(self, export_id: str, recommendation_id: str, payload: dict[str, Any], created_at: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO cam_export VALUES (?,?,?,?,?,?)",
                (export_id, recommendation_id, "generic_json", "1.0", json.dumps(payload, ensure_ascii=False), created_at),
            )
            conn.commit()

    def save_feedback_candidate(
        self,
        feedback_id: str,
        recommendation_id: str,
        feedback: dict[str, Any],
        candidate_id: str,
        candidate: dict[str, Any],
        eligibility: dict[str, Any],
        status: str,
        created_at: str,
    ) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO process_feedback VALUES (?,?,?,?,?)",
                (feedback_id, recommendation_id, json.dumps(feedback, ensure_ascii=False), "received", created_at),
            )
            conn.execute(
                "INSERT INTO bo_training_sample_candidate VALUES (?,?,?,?,?,?,?)",
                (
                    candidate_id, recommendation_id, feedback_id,
                    json.dumps(candidate, ensure_ascii=False), json.dumps(eligibility, ensure_ascii=False),
                    status, created_at,
                ),
            )
            conn.commit()

    def save_training_candidate(
        self,
        *,
        candidate_id: str,
        candidate: dict[str, Any],
        eligibility: dict[str, Any],
        status: str,
        created_at: str,
        recommendation_id: str | None = None,
        raw_feedback_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a review candidate without pretending it is a training sample."""
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO bo_training_sample_candidate (
                  candidate_id, recommendation_id, raw_feedback_id, candidate_json,
                  eligibility_report_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    recommendation_id,
                    raw_feedback_id,
                    json.dumps(candidate, ensure_ascii=False, sort_keys=True),
                    json.dumps(eligibility, ensure_ascii=False, sort_keys=True),
                    status,
                    created_at,
                ),
            )
            conn.commit()
        return self.get_training_candidate(candidate_id)

    def list_training_candidates(self, status: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with get_connection() as conn:
            if status == "all":
                rows = conn.execute(
                    "SELECT * FROM bo_training_sample_candidate ORDER BY created_at DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM bo_training_sample_candidate
                    WHERE status = ? ORDER BY created_at DESC LIMIT ?
                    """,
                    (status, safe_limit),
                ).fetchall()
        return [
            {
                **dict(row),
                "candidate": json.loads(row["candidate_json"]),
                "eligibility_report": json.loads(row["eligibility_report_json"]),
            }
            for row in rows
        ]

    def get_training_candidate(self, candidate_id: str) -> dict[str, Any]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM bo_training_sample_candidate WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return {
            **dict(row), "candidate": json.loads(row["candidate_json"]),
            "eligibility_report": json.loads(row["eligibility_report_json"]),
        }

    def approve_training_candidate(self, candidate_id: str, approved_by: str) -> dict[str, str]:
        approved_by = approved_by.strip()
        if not approved_by:
            raise ValueError("approved_by is required")
        approval_id, sample_id = f"bo_approval_{uuid.uuid4().hex}", f"bo_sample_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM bo_training_sample_candidate WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            existing = conn.execute(
                "SELECT approval_id, sample_id, approved_by, approved_at FROM approved_bo_training_sample WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if existing:
                candidate = json.loads(row["candidate_json"])
                eligibility = json.loads(row["eligibility_report_json"])
                materialized_id = self._materialize_training_sample(
                    conn,
                    str(existing["sample_id"]),
                    candidate,
                    eligibility,
                    str(existing["approved_at"]),
                )
                if materialized_id != str(existing["sample_id"]):
                    conn.execute(
                        "UPDATE approved_bo_training_sample SET sample_id=? WHERE candidate_id=?",
                        (materialized_id, candidate_id),
                    )
                conn.commit()
                return {**dict(existing), "sample_id": materialized_id}
            if row["status"] != "eligible_pending_approval":
                raise ValueError("only eligible_pending_approval candidates can be approved")
            candidate = json.loads(row["candidate_json"])
            eligibility = json.loads(row["eligibility_report_json"])
            sample_id = self._materialize_training_sample(
                conn, sample_id, candidate, eligibility, now
            )
            conn.execute(
                "INSERT INTO approved_bo_training_sample VALUES (?,?,?,?,?)",
                (approval_id, candidate_id, sample_id, approved_by, now),
            )
            conn.execute(
                "UPDATE bo_training_sample_candidate SET status='approved' WHERE candidate_id=?", (candidate_id,)
            )
            conn.commit()
        return {"approval_id": approval_id, "sample_id": sample_id, "approved_by": approved_by, "approved_at": now}

    def require_training_samples(self, sample_ids: list[str]) -> list[str]:
        """Validate caller-supplied dataset members against canonical approved samples."""
        unique = list(dict.fromkeys(str(value) for value in sample_ids if str(value)))
        if not unique:
            return []
        placeholders = ",".join("?" for _ in unique)
        with get_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT sample_id FROM bo_training_sample
                WHERE valid_for_training = 1 AND sample_id IN ({placeholders})
                """,
                unique,
            ).fetchall()
        found = {str(row["sample_id"]) for row in rows}
        missing = [sample_id for sample_id in unique if sample_id not in found]
        if missing:
            raise ValueError(f"unknown or unapproved prior sample ids: {missing}")
        return unique

    @staticmethod
    def _materialize_training_sample(
        connection,
        sample_id: str,
        candidate: dict[str, Any],
        eligibility: dict[str, Any],
        added_at: str,
    ) -> str:
        run_id = candidate.get("run_id")
        if not run_id:
            raise ValueError("approved candidate must have a traceable run_id")
        existing = connection.execute(
            "SELECT sample_id FROM bo_training_sample WHERE run_id=?", (run_id,)
        ).fetchone()
        if existing:
            return str(existing["sample_id"])
        parameters = eligibility.get("normalized_parameters") or {}
        measurements = eligibility.get("normalized_measurements") or {}
        if not parameters or not measurements:
            raise ValueError("approved candidate has no normalized parameters or measurements")
        connection.execute(
            """
            INSERT INTO bo_training_sample (
              sample_id, run_id, material, process_type, x_parameters_json,
              y_metrics_json, constraints_json, valid_for_training,
              invalid_reason, added_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                run_id,
                candidate.get("material"),
                candidate.get("process_type"),
                json.dumps(parameters, ensure_ascii=False, sort_keys=True),
                json.dumps(measurements, ensure_ascii=False, sort_keys=True),
                json.dumps(
                    candidate.get("constraint_results") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                1,
                None,
                added_at,
            ),
        )
        return sample_id

    def save_dataset_version(self, value: dict[str, Any]) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO bo_dataset_version VALUES (?,?,?,?,?,?)",
                (
                    value["dataset_version_id"], value["content_hash"],
                    json.dumps(value["sample_ids"], ensure_ascii=False),
                    json.dumps(value["slice_scope"], ensure_ascii=False, sort_keys=True),
                    value["feature_schema_version"], value["created_at"],
                ),
            )
            conn.commit()
