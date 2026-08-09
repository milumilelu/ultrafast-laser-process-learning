from __future__ import annotations

import threading
import time

from ultrafast_app.services.scientific_jobs import ScientificAnalysisJobService


class _ProbeJobService(ScientificAnalysisJobService):
    def __init__(self) -> None:
        self.active = 0
        self.maximum_active = 0
        self.probe_lock = threading.Lock()
        super().__init__(max_queue_size=8)

    def _persist(self, _job) -> None:
        return

    def _run(self, _job_id, _task_spec, _available_quantities) -> None:
        with self.probe_lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        time.sleep(0.03)
        with self.probe_lock:
            self.active -= 1


def test_scientific_analysis_jobs_use_one_bounded_worker() -> None:
    service = _ProbeJobService()
    for index in range(5):
        service.create_job({"task_context_id": f"task-{index}"})
    service._queue.join()

    assert service.maximum_active == 1
    assert service._queue.maxsize == 8
