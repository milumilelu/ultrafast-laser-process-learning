"""Scientific Analysis Job 服务（文档第十七节：异步 + 实时进度）。

POST /scientific-analysis/jobs       → 立即返回 {analysis_run_id, status: queued}
GET  /scientific-analysis/jobs/{id}  → 轮询：status + 阶段进度明细
                                     （retrieving → mapping 3/6 → validating →
                                       coverage → reducing → criticizing → completed）

后台线程执行完整链路：RAG 检索（build corpus）→ Source Map → 验证 → 覆盖检查
→ Reduce → Selective Critic。进度事件写入 job 状态，前端实时展示。

Job 状态持久化到 SQLite（scientific_analysis_job 表）：
- 服务重启后旧 job 仍可查询（终态恢复原状；非终态诚实标记 failed 并提示重跑）
- 避免前端轮询 404"服务可能已重启"的断链体验
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ultrafast_app.services.scientific_pipeline import (
    LLMNotConfiguredError,
    ScientificAnalysisService,
)
from ultrafast_knowledge.corpus.builder import ScientificCorpusBuilder

STAGES = (
    "queued",
    "retrieving",
    "mapping",
    "validating",
    "coverage",
    "reducing",
    "criticizing",
    "completed",
    "failed",
)

_INTERRUPTED_ERROR = "服务重启导致分析任务中断，请重新运行工艺任务分析"


@dataclass(slots=True)
class AnalysisJob:
    job_id: str
    status: str = "queued"
    stage: str = "queued"
    progress: dict[str, Any] = field(default_factory=dict)
    detail: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    task_context_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_run_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "detail": self.detail[-50:],
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ScientificAnalysisJobService:
    """Job 执行器（单 worker 串行，避免并发 LLM 风暴）+ SQLite 状态持久化。"""

    def __init__(self, *, max_history: int = 20):
        self._jobs: dict[str, AnalysisJob] = {}
        self._lock = threading.Lock()
        self._max_history = max_history

    # ------------------------------------------------------------ persistence
    def _persist(self, job: AnalysisJob) -> None:
        from ultrafast_memory.db.session import get_connection

        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO scientific_analysis_job
                    (job_id, task_context_id, status, stage, progress_json,
                     detail_json, result_json, error, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        job.job_id,
                        job.task_context_id,
                        job.status,
                        job.stage,
                        json.dumps(job.progress, ensure_ascii=False),
                        json.dumps(job.detail[-50:], ensure_ascii=False),
                        json.dumps(job.result, ensure_ascii=False) if job.result is not None else None,
                        job.error,
                        job.created_at,
                        job.updated_at,
                    ),
                )
                conn.commit()
        except Exception:  # noqa: BLE001 — 持久化失败不阻断分析（内存状态仍可用）
            job.detail.append({"stage": "persist", "error": "job persistence unavailable"})

    def _restore_job(self, job_id: str) -> AnalysisJob | None:
        """从 SQLite 恢复 job（服务重启后）；非终态 job 诚实标记为失败。"""
        from ultrafast_memory.db.session import get_connection

        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM scientific_analysis_job WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        except Exception:  # noqa: BLE001 — DB 不可用时按缺失处理
            return None
        if not row:
            return None
        job = AnalysisJob(
            job_id=row["job_id"],
            status=row["status"],
            stage=row["stage"],
            progress=json.loads(row["progress_json"] or "{}"),
            detail=json.loads(row["detail_json"] or "[]"),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            task_context_id=row["task_context_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        if job.status not in {"completed", "failed"}:
            job.status = "failed"
            job.stage = "failed"
            job.error = _INTERRUPTED_ERROR
            job.touch()
            self._persist(job)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    # ------------------------------------------------------------ public API
    def create_job(
        self,
        task_scope: dict[str, Any],
        retrieval_intents: list[str] | None = None,
        *,
        level: str = "E2P_STRICT",
    ) -> AnalysisJob:
        job = AnalysisJob(
            job_id=f"sa-{uuid.uuid4().hex[:12]}",
            task_context_id=str(task_scope.get("task_context_id") or None),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            if len(self._jobs) > self._max_history:
                oldest = sorted(self._jobs, key=lambda key: self._jobs[key].created_at)[
                    : len(self._jobs) - self._max_history
                ]
                for key in oldest:
                    self._jobs.pop(key, None)
        self._persist(job)
        worker = threading.Thread(
            target=self._run,
            args=(job.job_id, task_scope, retrieval_intents or [], level),
            daemon=True,
        )
        worker.start()
        return job

    def get_job(self, job_id: str) -> AnalysisJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            return job
        return self._restore_job(job_id)

    # ------------------------------------------------------------ internals
    def _run(
        self,
        job_id: str,
        task_scope: dict[str, Any],
        retrieval_intents: list[str],
        level: str,
    ) -> None:
        job = self.get_job(job_id)
        if job is None:
            return

        def set_stage(stage: str, progress: dict[str, Any] | None = None) -> None:
            job.stage = stage
            if progress is not None:
                job.progress = progress
            job.touch()
            self._persist(job)

        def emit(stage: str, detail: dict[str, Any]) -> None:
            set_stage(stage, detail)
            job.detail.append({"stage": stage, **detail})
            job.touch()
            self._persist(job)

        try:
            # Stage 1: RAG 检索 → EvidenceCorpusPack
            set_stage("retrieving", {"detail": "按任务 scope 构建多意图语料包"})
            corpus = ScientificCorpusBuilder().build(
                task_scope,
                task_context_id=str(task_scope.get("task_context_id") or "web-task"),
                intents=None,
            )
            emit(
                "retrieving",
                {
                    "sources": corpus.source_count(),
                    "raw_hits": corpus.retrieval_trace.raw_hit_count,
                    "source_list": [
                        {
                            "paper_id": source.paper_id,
                            "title": (source.title or "")[:120],
                            "sections": len(source.sections),
                        }
                        for source in corpus.sources[:10]
                    ],
                },
            )
            set_stage("mapping", {"current": 0, "total": corpus.source_count()})

            # Stage 2-6: Map → Validate → Coverage → Reduce → Critic
            service = ScientificAnalysisService(level=level)
            result = service.pipeline.analyze(
                corpus,
                level=level,
                progress_callback=emit,
            )
            job.result = result
            job.status = "completed"
            set_stage("completed", {"detail": "科学分析完成"})
            # 候选写入工艺记忆（knowledge_candidate + review task，pending_review）
            try:
                from ultrafast_knowledge.scientific.schemas import (
                    ScientificKnowledgePack,
                )
                from ultrafast_knowledge.scientific.validator import (
                    DeterministicScientificValidator,
                    default_source_checker,
                )
                from ultrafast_memory.db.session import get_connection

                pack = ScientificKnowledgePack.model_validate(result)
                validator = DeterministicScientificValidator(
                    source_checker=default_source_checker(get_connection)
                )
                validation = validator.validate(pack)
                persisted = ScientificAnalysisService.persist_static(
                    get_connection, pack, validation
                )
                job.detail.append(
                    {
                        "stage": "knowledge_memory",
                        "persisted": len(persisted.get("persisted_candidate_ids", [])),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - 记忆写入失败不阻断
                job.detail.append({"stage": "knowledge_memory", "error": str(exc)[:200]})
            self._persist(job)
            # Run Trace（审阅 §9）：贯穿 task→job→corpus→knowledge→pipeline 统计
            try:
                from ultrafast_app.services.scientific_trace import (
                    RecommendationRunTraceService,
                )

                pipeline_stats = (result.get("pipeline_report") or {}).get("mapping", {})
                pipeline_stats["reduce_candidates"] = (
                    (result.get("pipeline_report") or {}).get("reduce", {}).get("candidates", 0)
                )
                pipeline_stats["critic_issues"] = (
                    (result.get("pipeline_report") or {}).get("critic", {}).get("issues_found", 0)
                )
                pipeline_stats["coverage_ratio"] = (
                    (result.get("pipeline_report") or {}).get("coverage", {}).get("coverage_ratio", 0.0)
                )
                RecommendationRunTraceService().record(
                    task_id=str(task_scope.get("task_context_id")),
                    job_id=job_id,
                    corpus_pack_id=corpus.corpus_pack_id,
                    knowledge_pack_id=result.get("knowledge_pack_id"),
                    pipeline_stats=pipeline_stats,
                    status="completed",
                )
            except Exception as exc:  # noqa: BLE001 - trace 失败不阻断
                job.detail.append({"stage": "trace", "error": str(exc)[:200]})
                self._persist(job)
        except LLMNotConfiguredError as exc:
            job.status = "failed"
            job.error = str(exc)
            set_stage("failed", {"detail": str(exc)})
        except Exception as exc:  # noqa: BLE001 - Job 失败记录原因
            job.status = "failed"
            job.error = str(exc)
            set_stage("failed", {"detail": str(exc)})


_job_service: ScientificAnalysisJobService | None = None


def get_job_service() -> ScientificAnalysisJobService:
    global _job_service
    if _job_service is None:
        _job_service = ScientificAnalysisJobService()
    return _job_service
