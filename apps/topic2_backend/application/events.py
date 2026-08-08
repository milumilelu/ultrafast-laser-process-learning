"""Application WorkflowEvent emission (BE-3).

Only formal scientific events are persisted: RUN_STARTED / RUN_COMPLETED /
STAGE_* / TOOL_* / ENTITY_CREATED / ARTIFACT_CREATED / VALIDATION / WARNING /
ERROR. Transport-only events (delta / heartbeat / thinking_status) never enter
the activity timeline.
"""

from __future__ import annotations

import json
from typing import Any

from packages.e2p.application.traceability import timestamp

# event types (TOPIC2_FRONTEND_V2_DEVELOPMENT_TASK.md §21)
RUN_STARTED = "RUN_STARTED"
RUN_COMPLETED = "RUN_COMPLETED"
RUN_FAILED = "RUN_FAILED"
STAGE_STARTED = "STAGE_STARTED"
STAGE_PROGRESS = "STAGE_PROGRESS"
STAGE_COMPLETED = "STAGE_COMPLETED"
TOOL_STARTED = "TOOL_STARTED"
TOOL_COMPLETED = "TOOL_COMPLETED"
ENTITY_CREATED = "ENTITY_CREATED"
ARTIFACT_CREATED = "ARTIFACT_CREATED"
VALIDATION = "VALIDATION"
WARNING = "WARNING"
ERROR = "ERROR"

FORMAL_EVENT_TYPES = frozenset(
    {
        RUN_STARTED,
        RUN_COMPLETED,
        RUN_FAILED,
        STAGE_STARTED,
        STAGE_PROGRESS,
        STAGE_COMPLETED,
        TOOL_STARTED,
        TOOL_COMPLETED,
        ENTITY_CREATED,
        ARTIFACT_CREATED,
        VALIDATION,
        WARNING,
        ERROR,
    }
)


class WorkflowEventBus:
    """Sequence-ordered, persisted workflow event bus for one application run.

    Sequences are monotonic across run continuation (checkpoint resume):
    the bus starts from the last persisted sequence so resumed stages never
    collide with the UNIQUE(application_run_id, sequence) constraint.
    """

    def __init__(self, run_id: str, repository: Any, task_context_ref: str):
        self.run_id = run_id
        self.repository = repository
        self.task_context_ref = task_context_ref
        self._pending: list[dict[str, Any]] = []
        self._sequence = self.repository.last_workflow_event_sequence(run_id)

    def emit(
        self,
        type_: str,
        summary: str,
        *,
        stage: str | None = None,
        progress: dict[str, int] | None = None,
        entity_refs: list[dict[str, str]] | None = None,
        artifact_refs: list[dict[str, str]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if type_ not in FORMAL_EVENT_TYPES:
            raise ValueError(f"not a formal workflow event type: {type_}")
        self._sequence += 1
        event = {
            "event_id": f"{self.run_id}-e{self._sequence}",
            "run_id": self.run_id,
            "sequence": self._sequence,
            "timestamp": timestamp(),
            "type": type_,
            "stage": stage,
            "summary": summary,
            "progress": progress,
            "entityRefs": entity_refs or [],
            "artifactRefs": artifact_refs or [],
            "details": details or {},
        }
        self.repository.save_workflow_event(event)
        self._pending.append(event)
        return event

    def drain(self) -> list[dict[str, Any]]:
        pending, self._pending = self._pending, []
        return pending


def stable_event_id(run_id: str, sequence: int) -> str:
    return f"{run_id}-e{sequence}"


def serialize_event(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False, sort_keys=True)
