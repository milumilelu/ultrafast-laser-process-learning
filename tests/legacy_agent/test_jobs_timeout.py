"""后台作业：超时 handler 必须被标记 timed_out 且不阻塞 worker（P2）。"""

from __future__ import annotations

import time

from ultrafast_agent.jobs import BackgroundJobService, JobWorker
from ultrafast_agent.jobs.service import BackgroundWorkerRunner


class _MemoryJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.events: list[dict] = []

    def create(self, job):
        existing = self.jobs.get(job.job_id)
        if existing:
            return existing, False
        self.jobs[job.job_id] = job
        return job, True

    def get(self, job_id):
        return self.jobs.get(job_id)

    def list_events(self, job_id):
        return [e for e in self.events if e["job_id"] == job_id]

    def append_event(self, job_id, event_type, **values):
        event = {"job_id": job_id, "event_type": event_type, **values}
        self.events.append(event)
        return event

    def claim_next(self):
        for job in self.jobs.values():
            if job.status in {"queued", "retrying"}:
                from ultrafast_agent.jobs.models import JobStatus

                job = job.__class__(
                    **{**job.to_dict(), "status": JobStatus.RUNNING.value}
                )
                self.jobs[job.job_id] = job
                return job
        return None

    def update(self, job_id, **values):
        job = self.jobs[job_id]
        updated = job.__class__(**{**job.to_dict(), **values})
        self.jobs[job_id] = updated
        return updated

    def recover_stale(self, stale_before):
        return 0


def test_hung_handler_is_marked_timed_out() -> None:
    repository = _MemoryJobRepository()
    service = BackgroundJobService(repository)
    worker = JobWorker(repository)

    def hung_handler(payload, context):  # 永不返回
        time.sleep(30)

    worker.register("hang", hung_handler)
    _, _ = service.create("hang", {}, timeout_seconds=0.2)
    started = time.monotonic()
    result = worker.run_once()
    elapsed = time.monotonic() - started
    assert result is not None
    assert result.status == "timed_out"
    assert result.error_code == "timeout"
    assert elapsed < 5.0, "worker 不得被挂死 handler 阻塞"


def test_successful_handler_completes() -> None:
    repository = _MemoryJobRepository()
    service = BackgroundJobService(repository)
    worker = JobWorker(repository)
    worker.register("ok", lambda payload, context: {"value": 42})
    _, _ = service.create("ok", {})
    result = worker.run_once()
    assert result is not None and result.status == "succeeded"
    assert result.output == {"value": 42}


def test_runner_start_stop_is_idempotent() -> None:
    repository = _MemoryJobRepository()
    worker = JobWorker(repository)
    runner = BackgroundWorkerRunner(worker, poll_interval=0.1)
    runner.start()
    runner.start()
    runner.stop()
    runner.stop()
