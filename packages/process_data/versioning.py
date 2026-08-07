"""Deterministic dataset identity utilities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dataset_identity(
    records: Iterable[Mapping[str, Any]], requested_version: str | None = None
) -> tuple[str, str]:
    normalized = sorted(
        (dict(record) for record in records),
        key=lambda row: str(row.get("experiment_id", "")),
    )
    digest = canonical_hash(normalized)
    return requested_version or f"ds-{digest[:12]}", digest
