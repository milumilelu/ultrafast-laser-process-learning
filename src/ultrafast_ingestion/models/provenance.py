"""ProvenanceAnchor per DOCUMENT_IDENTITY_AND_PROVENANCE_V0.1."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

_WS_RE = re.compile(r"\s+")


def normalize_quote(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def quote_fingerprint(text: str) -> str:
    normalized = normalize_quote(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class ProvenanceAnchor:
    """Primary locator: PDF page + bbox + quote fingerprint.

    char_start/char_end are representation-local conveniences only
    (never valid across document versions).
    """

    paper_id: str
    document_version_id: str
    pdf_page_index: int
    printed_page_label: str = ""
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    normalized_quote: str = ""
    quote_fingerprint: str = ""
    section_path: str = ""
    block_id: str = ""
    char_start: int | None = None
    char_end: int | None = None

    @classmethod
    def build(
        cls,
        *,
        paper_id: str,
        document_version_id: str,
        pdf_page_index: int,
        printed_page_label: str,
        bbox: tuple[float, float, float, float],
        text: str,
        section_path: str,
        block_id: str,
        char_start: int | None = None,
        char_end: int | None = None,
    ) -> ProvenanceAnchor:
        return cls(
            paper_id=paper_id,
            document_version_id=document_version_id,
            pdf_page_index=pdf_page_index,
            printed_page_label=printed_page_label,
            bbox=bbox,
            normalized_quote=normalize_quote(text),
            quote_fingerprint=quote_fingerprint(text),
            section_path=section_path,
            block_id=block_id,
            char_start=char_start,
            char_end=char_end,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bbox"] = list(self.bbox)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceAnchor:
        return cls(**{**data, "bbox": tuple(data.get("bbox") or (0, 0, 0, 0))})


def stable_hash(*parts: Any) -> str:
    payload = json.dumps(
        [str(p) for p in parts], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
