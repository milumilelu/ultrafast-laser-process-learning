"""B1 CFA facet confusion audit (contract B1_CHECKPOINT_V0_1 §3).

Semantic classification, not raw accuracy:
  Human UNKNOWN & System UNKNOWN   -> consistent
  Human UNKNOWN & System MISMATCH  -> SEVERE (negative judgment on insufficient evidence)
  Human MISMATCH & System UNKNOWN  -> conservative miss
  Human MATCH   & System UNKNOWN   -> information/reconstruction gap
  equal statuses                   -> consistent
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

FACETS = ("Material", "Task", "InteractionState", "Reconstructibility", "Reachability")


@dataclass(slots=True)
class FacetConfusion:
    facet: str
    matrix: dict[tuple[str, str], int] = field(default_factory=Counter)
    severe: int = 0
    conservative_miss: int = 0
    information_gap: int = 0
    consistent: int = 0

    def classify(self, human: str, system: str) -> str:
        if human == system:
            self.consistent += 1
            return "consistent"
        if human == "UNKNOWN" and system == "MISMATCH":
            self.severe += 1
            return "severe"
        if human == "MISMATCH" and system == "UNKNOWN":
            self.conservative_miss += 1
            return "conservative_miss"
        if human == "MATCH" and system == "UNKNOWN":
            self.information_gap += 1
            return "information_gap"
        return "other"

    def to_dict(self) -> dict[str, Any]:
        return {
            "facet": self.facet,
            "matrix": {f"{h}/{s}": n for (h, s), n in sorted(self.matrix.items())},
            "severe": self.severe,
            "conservative_miss": self.conservative_miss,
            "information_gap": self.information_gap,
            "consistent": self.consistent,
        }


def audit_facets(human_records: list[dict], system_records: list[dict]) -> list[FacetConfusion]:
    """Level 3: per-facet confusion over paired paper records.

    human_records[i] / system_records[i] are aligned by paper_id (caller
    responsibility). Each record maps facet name -> status string.
    """
    human_by_paper = {r["paper_id"]: r for r in human_records}
    results: dict[str, FacetConfusion] = {
        f: FacetConfusion(facet=f) for f in FACETS
    }
    for system in system_records:
        human = human_by_paper.get(system["paper_id"])
        if human is None:
            continue
        human_facets = human.get("level3_facets", {})
        system_facets = system.get("level3_cfa", {}).get("facet_summary", {})
        for facet in FACETS:
            h = _normalize(human_facets.get(facet))
            s = _normalize(system_facets.get(facet))
            if h is None or s is None:
                continue
            results[facet].matrix[(h, s)] += 1
            results[facet].classify(h, s)
    return [results[f] for f in FACETS]


def _normalize(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).upper().replace("_", "")


def audit_coordinates(human_records: list[dict], system_records: list[dict]) -> dict[str, Any]:
    """Level 2: coordinate-availability confusion (availability vocabulary)."""
    human_by_paper = {r["paper_id"]: r for r in human_records}
    matrix: Counter = Counter()
    for system in system_records:
        human = human_by_paper.get(system["paper_id"])
        if human is None:
            continue
        human_coords = human.get("level2_coordinates", {})
        system_coords = system.get("level2_coordinates", {})
        for name, h in human_coords.items():
            s_entry = system_coords.get(name)
            s = _normalize(s_entry.get("availability")) if s_entry else None
            if s is None:
                continue
            matrix[(str(h).upper(), s)] += 1
    return {
        "matrix": {f"{h}/{s}": n for (h, s), n in sorted(matrix.items())},
        "total": sum(matrix.values()),
    }


def audit_report(
    human_records: list[dict], system_records: list[dict]
) -> dict[str, Any]:
    """Full three-level audit report (no probability fields anywhere)."""
    facets = audit_facets(human_records, system_records)
    coordinates = audit_coordinates(human_records, system_records)
    severe_total = sum(f.severe for f in facets)
    return {
        "level3_facets": [f.to_dict() for f in facets],
        "level2_coordinates": coordinates,
        "severity_summary": {
            "severe": severe_total,
            "conservative_miss": sum(f.conservative_miss for f in facets),
            "information_gap": sum(f.information_gap for f in facets),
            "consistent": sum(f.consistent for f in facets),
        },
    }
