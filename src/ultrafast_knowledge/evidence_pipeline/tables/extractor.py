"""Table-extractor port kept independent from any PDF vendor library."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ultrafast_knowledge.evidence_pipeline.tables.models import RawExtractedTable


class TableExtractionError(RuntimeError):
    pass


class TableExtractor(Protocol):
    name: str
    version: str

    def extract(self, pdf_path: Path) -> list[RawExtractedTable]: ...


class NullTableExtractor:
    """Explicit no-op used when table extraction is disabled."""

    name = "disabled"
    version = "none"

    def extract(self, pdf_path: Path) -> list[RawExtractedTable]:
        del pdf_path
        return []
