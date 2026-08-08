"""ScientificTrace: 统一科学执行观测封装（P1 Observability）。

每个科学操作以一条 operation 记录：started（TOOL_STARTED / STAGE_STARTED）与
completed（TOOL_COMPLETED / STAGE_COMPLETED）事件，携带结构化 trace 元数据：

    details = {
        "operation_id": "...",
        "parent_operation_id": "...",
        "input_refs": [{"type": "...", "id": "..."}],
        "output_refs": [{"type": "...", "id": "..."}],
        "counts": {"input": n, "output": n, "accepted": n, "rejected": n},
        "reason_codes": [...],
        "duration_ms": ...,
    }

Event 不保存巨大 scientific payload（内容进 Artifact）；这些 details 足以在
前端重建 execution tree。禁止各 service 自行拼装 event schema。
"""

from __future__ import annotations

import time
from typing import Any

from apps.topic2_backend.application.events import (
    ARTIFACT_CREATED,
    ENTITY_CREATED,
    STAGE_COMPLETED,
    STAGE_STARTED,
    TOOL_COMPLETED,
    TOOL_STARTED,
    VALIDATION,
    WARNING,
    WorkflowEventBus,
)


class ScientificTrace:
    """对一个 application run 的 trace 封装（单例 per run，复用 event bus）。"""

    def __init__(self, bus: WorkflowEventBus, stage: str):
        self.bus = bus
        self.stage = stage
        self._timers: dict[str, float] = {}

    # ------------------------------------------------------------ operations

    def operation_started(
        self,
        operation_id: str,
        name: str,
        *,
        parent_operation_id: str | None = None,
        input_refs: list[dict[str, str]] | None = None,
        progress: dict[str, int] | None = None,
    ) -> None:
        self._timers[operation_id] = time.perf_counter()
        details: dict[str, Any] = {
            "operation_id": operation_id,
            "parent_operation_id": parent_operation_id,
            "input_refs": input_refs or [],
        }
        self.bus.emit(
            TOOL_STARTED,
            name,
            stage=self.stage,
            progress=progress,
            details=details,
        )

    def operation_completed(
        self,
        operation_id: str,
        name: str,
        *,
        output_refs: list[dict[str, str]] | None = None,
        counts: dict[str, int] | None = None,
        reason_codes: list[str] | None = None,
    ) -> None:
        started = self._timers.pop(operation_id, None)
        duration_ms = (
            int((time.perf_counter() - started) * 1000) if started is not None else None
        )
        details: dict[str, Any] = {
            "operation_id": operation_id,
            "output_refs": output_refs or [],
            "counts": counts or {},
            "reason_codes": reason_codes or [],
        }
        if duration_ms is not None:
            details["duration_ms"] = duration_ms
        self.bus.emit(
            TOOL_COMPLETED,
            name,
            stage=self.stage,
            details=details,
        )

    def stage_started(self, label: str) -> None:
        self.bus.emit(STAGE_STARTED, label, stage=self.stage)

    def stage_completed(self, label: str, details: dict[str, Any] | None = None) -> None:
        self.bus.emit(STAGE_COMPLETED, label, stage=self.stage, details=details)

    # ------------------------------------------------------------ artifacts

    def artifact_created(
        self,
        artifact_type: str,
        artifact_id: str,
        *,
        name: str | None = None,
        input_refs: list[dict[str, str]] | None = None,
        output_refs: list[dict[str, str]] | None = None,
        counts: dict[str, int] | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "input_refs": input_refs or [],
            "output_refs": output_refs or [],
            "counts": counts or {},
        }
        self.bus.emit(
            ARTIFACT_CREATED,
            name or f"{artifact_type} 生成",
            stage=self.stage,
            artifact_refs=[{"type": artifact_type, "id": artifact_id}],
            details=details,
        )

    def entity_created(
        self, entity_type: str, entity_id: str, summary: str | None = None
    ) -> None:
        self.bus.emit(
            ENTITY_CREATED,
            summary or f"{entity_type} {entity_id}",
            stage=self.stage,
            entity_refs=[{"type": entity_type, "id": entity_id}],
        )

    def validation(
        self,
        summary: str,
        *,
        counts: dict[str, int] | None = None,
        reason_codes: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "counts": counts or {},
            "reason_codes": reason_codes or [],
            **(details or {}),
        }
        self.bus.emit(VALIDATION, summary, stage=self.stage, details=payload)

    def warning(self, summary: str, **details: Any) -> None:
        self.bus.emit(WARNING, summary, stage=self.stage, details=details)
