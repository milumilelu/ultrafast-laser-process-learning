from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from ultrafast_agent.jobs.models import TERMINAL_JOB_STATUSES, BackgroundJob, JobStatus


class JobRepository(Protocol):
    def create(self, job: BackgroundJob) -> tuple[BackgroundJob, bool]: ...
    def get(self, job_id: str) -> BackgroundJob | None: ...
    def list_events(self, job_id: str) -> list[dict[str, Any]]: ...
    def append_event(self, job_id: str, event_type: str, **values: Any) -> dict[str, Any]: ...
    def claim_next(self) -> BackgroundJob | None: ...
    def update(self, job_id: str, **values: Any) -> BackgroundJob: ...
    def recover_stale(self, stale_before: str) -> int: ...


class BackgroundJobService:
    def __init__(self, repository: JobRepository):
        self.repository = repository

    def create(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        timeout_seconds: float | None = None,
    ) -> tuple[BackgroundJob, bool]:
        if not job_type.strip():
            raise ValueError("job_type is required")
        job = BackgroundJob(
            job_id=f"job_{uuid.uuid4().hex}",
            job_type=job_type,
            status=JobStatus.QUEUED.value,
            input=dict(payload),
            max_attempts=max(1, max_attempts),
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds,
            created_at=_now(),
        )
        stored, created = self.repository.create(job)
        if created:
            self.repository.append_event(stored.job_id, "job_created", message="job queued", progress=0.0)
        return stored, created

    def get(self, job_id: str) -> BackgroundJob:
        job = self.repository.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def cancel(self, job_id: str) -> BackgroundJob:
        job = self.get(job_id)
        if job.status in TERMINAL_JOB_STATUSES:
            return job
        status = JobStatus.CANCELLED.value if job.status in {"queued", "retrying"} else JobStatus.CANCEL_REQUESTED.value
        updated = self.repository.update(job_id, status=status, finished_at=_now() if status == "cancelled" else None)
        self.repository.append_event(job_id, "cancel_requested", message="cancellation requested", progress=updated.progress)
        return updated

    def retry(self, job_id: str) -> BackgroundJob:
        job = self.get(job_id)
        if job.status not in {"failed", "timed_out", "cancelled"}:
            raise ValueError("only failed, timed_out, or cancelled jobs can be retried")
        updated = self.repository.update(
            job_id,
            status=JobStatus.RETRYING.value,
            error_code=None,
            error_message=None,
            finished_at=None,
        )
        self.repository.append_event(job_id, "job_retrying", message="job queued for retry", progress=updated.progress)
        return updated


@dataclass(slots=True)
class JobExecutionContext:
    job_id: str
    repository: JobRepository

    def cancelled(self) -> bool:
        job = self.repository.get(self.job_id)
        return bool(job and job.status == JobStatus.CANCEL_REQUESTED.value)

    def progress(self, value: float, step: str, payload: dict[str, Any] | None = None) -> None:
        bounded = max(0.0, min(1.0, float(value)))
        self.repository.update(self.job_id, progress=bounded, current_step=step, heartbeat_at=_now())
        self.repository.append_event(
            self.job_id,
            "job_progressed",
            message=step,
            progress=bounded,
            payload=payload or {},
        )


JobHandler = Callable[[dict[str, Any], JobExecutionContext], dict[str, Any] | None]


class JobWorker:
    def __init__(self, repository: JobRepository, handlers: dict[str, JobHandler] | None = None):
        self.repository = repository
        self.handlers = dict(handlers or {})

    def register(self, job_type: str, handler: JobHandler) -> None:
        self.handlers[job_type] = handler

    def run_once(self) -> BackgroundJob | None:
        job = self.repository.claim_next()
        if job is None:
            return None
        handler = self.handlers.get(job.job_type)
        if handler is None:
            return self._fail(job, "validation_failed", f"unregistered job type: {job.job_type}", retryable=False)
        context = JobExecutionContext(job.job_id, self.repository)
        self.repository.append_event(job.job_id, "job_started", message="worker claimed job", progress=job.progress)
        output, error, timed_out = self._run_handler(
            job, handler, context, job.timeout_seconds
        )
        if timed_out:
            updated = self.repository.update(
                job.job_id,
                status="timed_out",
                error_code="timeout",
                error_message="job exceeded timeout; handler was detached and cannot be force-killed in-process",
                finished_at=_now(),
            )
            self.repository.append_event(job.job_id, "job_timed_out", message=updated.error_message, progress=updated.progress)
            return updated
        if error is not None:
            retryable = bool(getattr(error, "retryable", False))
            return self._fail(job, str(getattr(error, "code", "job_failed")), str(error), retryable=retryable)
        current = self.repository.get(job.job_id)
        if current and current.status == JobStatus.CANCEL_REQUESTED.value:
            updated = self.repository.update(job.job_id, status="cancelled", finished_at=_now())
            self.repository.append_event(job.job_id, "job_cancelled", message="job cancelled", progress=updated.progress)
            return updated
        updated = self.repository.update(
            job.job_id,
            status="succeeded",
            output=output or {},
            progress=1.0,
            current_step="completed",
            heartbeat_at=_now(),
            finished_at=_now(),
        )
        self.repository.append_event(job.job_id, "job_succeeded", message="job completed", progress=1.0)
        return updated

    def _run_handler(
        self,
        job: BackgroundJob,
        handler: JobHandler,
        context: JobExecutionContext,
        timeout_seconds: float | None,
    ) -> tuple[dict[str, Any] | None, BaseException | None, bool]:
        """在守护线程中执行 handler；超时则标记 timed_out 并继续调度，
        挂死的 handler 不再阻塞 worker（进程内无法强制杀死线程）。"""
        result: dict[str, Any] | None = None
        error: BaseException | None = None

        def _execute() -> None:
            nonlocal result, error
            try:
                result = handler(job.input, context) or {}
            except BaseException as exc:  # noqa: BLE001 - worker boundary
                error = exc

        thread = threading.Thread(target=_execute, name=f"job-{job.job_id}", daemon=True)
        thread.start()
        if timeout_seconds is None:
            thread.join()
            return result, error, False
        thread.join(max(0.0, float(timeout_seconds)))
        if thread.is_alive():
            return result, error, True
        return result, error, False

    def _fail(self, job: BackgroundJob, code: str, message: str, *, retryable: bool) -> BackgroundJob:
        current = self.repository.get(job.job_id) or job
        should_retry = retryable and current.attempt < current.max_attempts
        status = "retrying" if should_retry else "failed"
        updated = self.repository.update(
            job.job_id,
            status=status,
            error_code=code,
            error_message=message,
            heartbeat_at=_now(),
            finished_at=None if should_retry else _now(),
        )
        self.repository.append_event(job.job_id, f"job_{status}", message=message, progress=updated.progress)
        return updated


class BackgroundWorkerRunner:
    """应用生命周期内运行的后台 worker：轮询领取任务、恢复陈旧任务。

    Composition Root（ultrafast_app）负责 start/stop；进程内无法强杀
    挂死 handler，超时任务会被标记 timed_out 并允许重试。
    """

    def __init__(
        self,
        worker: JobWorker,
        poll_interval: float = 1.0,
        stale_after_seconds: float = 300.0,
    ):
        self.worker = worker
        self.poll_interval = max(0.1, poll_interval)
        self.stale_after_seconds = stale_after_seconds
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="background-job-worker", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                stale_before = (
                    datetime.now(timezone.utc) - timedelta(seconds=self.stale_after_seconds)
                ).isoformat()
                self.worker.repository.recover_stale(stale_before)
                self.worker.run_once()
            except Exception:  # noqa: BLE001, S110 - 单次失败不终止 worker
                pass
            self._stop.wait(self.poll_interval)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

