"""③A: EvidenceMetadata - literature metadata as CFA Material/Task input.

The Material/Task facets must never be guessed from M6 physics conditions:
they consume evidence metadata (material / laser regime / process type /
geometry). Source: benchmarks/literature_metadata gold (human) or its
extractor; missing metadata -> UNKNOWN (never inferred).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceMetadata:
    material_id: str | None = None
    material_grade: str | None = None
    laser_type: str | None = None
    process_type: str | None = None
    geometry_type: str | None = None
    wavelength_nm: float | None = None
    pulse_width: str | None = None
    notes: str = ""

    def to_scope(self) -> dict[str, Any]:
        """Canonical E2P/CFA evidence scope keys (None values stay absent)."""
        return {
            key: value
            for key, value in {
                "material_id": self.material_id,
                "material_grade": self.material_grade,
                "laser_type": self.laser_type,
                "process_type": self.process_type,
                "geometry_type": self.geometry_type,
            }.items()
            if value is not None
        }


_GOLD_FIELD_MAP = {
    "primary_material": "material_id",
    "material_grade": "material_grade",
    "laser_type": "laser_type",
    "primary_process": "process_type",
    "geometry": "geometry_type",
    "wavelength_nm": "wavelength_nm",
    "pulse_width": "pulse_width",
}


def _norm_id(value: str) -> str:
    return value.strip().lower()


def _matches(gold_id: str, paper_id: str) -> bool:
    g, b = _norm_id(gold_id), _norm_id(paper_id)
    if g == b:
        return True
    if b.endswith(g) or g.endswith(b):
        return True
    if "_" in b:
        head, _, rest = b.partition("_")
        if len(head) == 16 and _norm_id(rest) == g:
            return True
    return False


def _clean_value(value: Any) -> Any:
    """Metadata gold fields are lists of mentions or single strings.
    Empty list / empty string / None all mean MISSING."""
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            cleaned = _clean_value(item)
            if cleaned is not None:
                return cleaned
        return None
    text = str(value).strip()
    return text if text else None


def load_evidence_metadata(
    gold_path: Path, paper_ids: list[str]
) -> tuple[dict[str, EvidenceMetadata], list[str]]:
    """Load metadata gold, matching paper ids (sha-prefix tolerant).

    Returns (metadata_by_paper_id, unmatched_paper_ids). Missing metadata
    stays None - the CFA then reports UNKNOWN, never a guess.
    """
    rows = [
        json.loads(line)
        for line in gold_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matched: dict[str, EvidenceMetadata] = {}
    unmatched: list[str] = []
    for paper_id in paper_ids:
        hit = None
        for row in rows:
            if _matches(row.get("paper_id", ""), paper_id):
                hit = row
                break
        if hit is None:
            unmatched.append(paper_id)
            continue
        fields: dict[str, Any] = {}
        for gold_key, meta_key in _GOLD_FIELD_MAP.items():
            value = _clean_value(hit.get(gold_key))
            if value is not None:
                fields[meta_key] = value
        matched[paper_id] = EvidenceMetadata(**fields)
    return matched, unmatched
