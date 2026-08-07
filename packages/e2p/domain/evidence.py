"""Compiled evidence bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from packages.process_contracts.schemas import Evidence


@dataclass
class EvidenceBundle:
    candidates: list[Evidence] = field(default_factory=list)
    accepted: list[Evidence] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    applicability_results: list[dict[str, Any]] = field(default_factory=list)
    version: str = "evidence-bundle-v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "candidates": [item.model_dump(mode="json") for item in self.candidates],
            "accepted": [item.model_dump(mode="json") for item in self.accepted],
            "rejected": self.rejected,
            "applicability_results": self.applicability_results,
        }
