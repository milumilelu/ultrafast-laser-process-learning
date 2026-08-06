"""E2P run-id and timestamp helpers (no project imports)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def new_run_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def timestamp() -> str:
    return datetime.now(UTC).isoformat()
