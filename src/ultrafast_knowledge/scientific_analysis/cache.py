"""SourceScientificAnalysis 缓存（文档第十三、十四节）。

Source Map 结果按 cache key（source_hash + prompt_version + model）持久化，
后续任务直接复用，不重复调用 LLM 精读同一篇文献。
"""

from __future__ import annotations

import json
from typing import Any

from ultrafast_knowledge.scientific_analysis.schemas import SourceScientificAnalysis
from ultrafast_memory.db.session import get_connection


class SQLiteSourceAnalysisCache:
    """基于 ultrafast_memory.db 的 Source 分析缓存。"""

    def __init__(self, connection: Any = None, max_entries: int = 200):
        self.connection = connection or get_connection
        self.max_entries = max_entries

    def _ensure_table(self, conn: Any) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS source_scientific_analysis ("
            "cache_key TEXT PRIMARY KEY,"
            "source_id TEXT NOT NULL,"
            "paper_id TEXT,"
            "analysis_json TEXT NOT NULL,"
            "llm_model TEXT,"
            "created_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ssa_source ON source_scientific_analysis(source_id)"
        )

    def get(self, key: str) -> SourceScientificAnalysis | None:
        try:
            with self.connection() as conn:
                self._ensure_table(conn)
                row = conn.execute(
                    "SELECT analysis_json FROM source_scientific_analysis WHERE cache_key=?",
                    (key,),
                ).fetchone()
            if row is None:
                return None
            return SourceScientificAnalysis.model_validate(json.loads(row[0]))
        except Exception:  # noqa: BLE001 - 缓存损坏按未命中处理
            return None

    def put(self, key: str, analysis: SourceScientificAnalysis) -> None:
        try:
            with self.connection() as conn:
                self._ensure_table(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO source_scientific_analysis "
                    "(cache_key, source_id, paper_id, analysis_json, llm_model) "
                    "VALUES (?,?,?,?,?)",
                    (
                        key,
                        analysis.source_id,
                        analysis.paper_id,
                        json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False),
                        analysis.llm_model,
                    ),
                )
                conn.execute(
                    "DELETE FROM source_scientific_analysis WHERE cache_key NOT IN ("
                    "SELECT cache_key FROM source_scientific_analysis "
                    "ORDER BY created_at DESC LIMIT ?)",
                    (self.max_entries,),
                )
                conn.commit()
        except Exception:  # noqa: BLE001 - 缓存写失败不阻断主流程
            return
