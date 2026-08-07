"""科学分析 Job 持久化：重启后可查询；非终态 job 诚实标记中断。"""

from __future__ import annotations

from ultrafast_app.services.scientific_jobs import (
    AnalysisJob,
    ScientificAnalysisJobService,
)
from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection


def _make_job(service: ScientificAnalysisJobService, **overrides) -> AnalysisJob:
    """直接构造 job（不启动 worker 线程），写入内存与 DB。"""
    job = AnalysisJob(job_id=overrides.pop("job_id", "sa-test-000000000001"), **overrides)
    service._jobs[job.job_id] = job
    service._persist(job)
    return job


def test_job_persisted_to_db(memory_root) -> None:
    init_database()
    service = ScientificAnalysisJobService()
    job = _make_job(service, status="completed", stage="completed", result={"knowledge_pack_id": "kp-1"}, task_context_id="TASK-0001")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT status, result_json, task_context_id FROM scientific_analysis_job WHERE job_id=?",
            (job.job_id,),
        ).fetchone()
    assert row is not None
    assert row["status"] == "completed"
    assert row["task_context_id"] == "TASK-0001"
    assert '"kp-1"' in row["result_json"]


def test_job_restored_after_restart(memory_root) -> None:
    """模拟服务重启：新 service 实例从 DB 恢复 job。"""
    init_database()
    service = ScientificAnalysisJobService()
    _make_job(service, status="failed", stage="failed", error="some error")

    restarted = ScientificAnalysisJobService()  # 内存清空，模拟重启
    restored = restarted.get_job("sa-test-000000000001")
    assert restored is not None
    assert restored.status == "failed"
    assert restored.error == "some error"


def test_interrupted_job_marked_failed_on_restart(memory_root) -> None:
    """非终态 job（服务重启时仍在 running）恢复后诚实标记中断。"""
    init_database()
    service = ScientificAnalysisJobService()
    _make_job(service, stage="mapping")  # 状态停在 mapping，模拟重启中断

    restarted = ScientificAnalysisJobService()
    restored = restarted.get_job("sa-test-000000000001")
    assert restored is not None
    assert restored.status == "failed"
    assert restored.stage == "failed"
    assert "服务重启" in (restored.error or "")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM scientific_analysis_job WHERE job_id=?",
            ("sa-test-000000000001",),
        ).fetchone()
    assert row["status"] == "failed"


def test_unknown_job_returns_none(memory_root) -> None:
    init_database()
    service = ScientificAnalysisJobService()
    assert service.get_job("sa-does-not-exist") is None


def test_completed_job_keeps_status_on_restart(memory_root) -> None:
    init_database()
    service = ScientificAnalysisJobService()
    _make_job(service, status="completed", stage="completed")

    restarted = ScientificAnalysisJobService()
    restored = restarted.get_job("sa-test-000000000001")
    assert restored is not None
    assert restored.status == "completed"
    assert restored.error is None
