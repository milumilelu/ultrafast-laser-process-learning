"""Discovery backends (O2): Protocol + recorded replay.

Contract: OPEN_SCIENTIFIC_DISCOVERY_V0_1 §11.

O2 implements discover(); fill/glean/verify are added at O4/O5/O6.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ultrafast_ingestion.candidates.models import VerificationStatus
from ultrafast_ingestion.discovery.models import (
    CandidateDetail,
    CandidateSkeleton,
    DiscoveryBatch,
)


class DiscoveryBackend(Protocol):
    """External discovery client. O2: discover; O4: fill; O5: glean; O6: verify."""

    def discover(self, batch: DiscoveryBatch) -> list[CandidateSkeleton]: ...

    def fill(self, skeleton: CandidateSkeleton, context: str) -> CandidateDetail: ...

    def glean(
        self, batch: DiscoveryBatch, existing: list[CandidateSkeleton]
    ) -> list[CandidateSkeleton]: ...

    def verify(
        self, candidate, context: str
    ) -> tuple[VerificationStatus, str]: ...


class RecordedDiscoveryBackend:
    """Deterministic CI backend: replays recorded JSONL responses.

    One JSONL row per call, consumed in order:

        {"type": "discovery", "skeletons": [<CandidateSkeleton>, ...]}

    Exhaustion or a wrong row type raises (recorded fixtures must exactly
    match the call sequence - same convention as run_recorded in linking).
    """

    def __init__(self, record_path: Path) -> None:
        self.record_path = Path(record_path)
        self._rows = [
            json.loads(line)
            for line in self.record_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self._pos = 0

    def discover(self, batch: DiscoveryBatch) -> list[CandidateSkeleton]:
        row = self._next_row("discovery")
        skeletons = row.get("skeletons") or []
        return [CandidateSkeleton.model_validate(s) for s in skeletons]

    def fill(self, skeleton: CandidateSkeleton, context: str) -> CandidateDetail:
        row = self._next_row("fill")
        return CandidateDetail.model_validate(row.get("detail") or {})

    def glean(
        self, batch: DiscoveryBatch, existing: list[CandidateSkeleton]
    ) -> list[CandidateSkeleton]:
        row = self._next_row("glean")
        skeletons = row.get("skeletons") or []
        return [CandidateSkeleton.model_validate(s) for s in skeletons]

    def verify(
        self, candidate, context: str
    ) -> tuple[VerificationStatus, str]:
        row = self._next_row("verify")
        status = VerificationStatus(row["verification_status"])
        return status, str(row.get("basis") or "")

    def _next_row(self, expected_type: str) -> dict:
        if self._pos >= len(self._rows):
            raise ValueError(
                f"recorded discovery exhausted at row {self._pos} "
                f"(expected {expected_type!r}); fixture mismatch: {self.record_path}"
            )
        row = self._rows[self._pos]
        if row.get("type") != expected_type:
            raise ValueError(
                f"recorded row {self._pos} is {row.get('type')!r}, expected {expected_type!r}"
            )
        self._pos += 1
        return row
