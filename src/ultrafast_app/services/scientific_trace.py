"""Recommendation Run Trace（审阅 §9）。

一次科学分析完整记录：task_id → job_id → corpus_pack_id → knowledge_pack_id
→ pipeline 统计（mapping/reduce/critic/coverage）→ 时间。供前端 RunsPage
展示与"为什么推荐"追溯。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ultrafast_memory.db.session import get_connection


class RecommendationRunTraceService:
    def __init__(self, connection: Any = None):
        self.connection = connection or get_connection

    def _ensure_table(self, conn: Any) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS recommendation_run_trace ("
            "run_id TEXT PRIMARY KEY,"
            "task_id TEXT,"
            "job_id TEXT,"
            "corpus_pack_id TEXT,"
            "knowledge_pack_id TEXT,"
            "pipeline_stats_json TEXT,"
            "status TEXT,"
            "error TEXT,"
            "created_at TEXT DEFAULT (datetime('now'))"
            ")"
        )

    def record(
        self,
        *,
        task_id: str | None,
        job_id: str,
        corpus_pack_id: str | None,
        knowledge_pack_id: str | None,
        pipeline_stats: dict[str, Any] | None = None,
        status: str = "completed",
        error: str | None = None,
    ) -> str:
        run_id = f"rt-{uuid.uuid4().hex[:12]}"
        try:
            with self.connection() as conn:
                self._ensure_table(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO recommendation_run_trace "
                    "(run_id, task_id, job_id, corpus_pack_id, knowledge_pack_id, "
                    "pipeline_stats_json, status, error) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        task_id,
                        job_id,
                        corpus_pack_id,
                        knowledge_pack_id,
                        json.dumps(pipeline_stats or {}, ensure_ascii=False),
                        status,
                        error,
                    ),
                )
                conn.commit()
        except Exception:  # noqa: BLE001 - trace 写失败不阻断主流程
            return run_id
        return run_id

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with self.connection() as conn:
                self._ensure_table(conn)
                rows = conn.execute(
                    "SELECT run_id, task_id, job_id, corpus_pack_id, knowledge_pack_id, "
                    "pipeline_stats_json, status, error, created_at "
                    "FROM recommendation_run_trace ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except Exception:  # noqa: BLE001
            return []
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["pipeline_stats"] = json.loads(item.pop("pipeline_stats_json") or "{}")
            except (TypeError, ValueError):
                item["pipeline_stats"] = {}
            result.append(item)
        return result
