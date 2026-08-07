"""Parser protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ultrafast_ingestion.models.document import ScientificDocument


class DocumentParser(Protocol):
    """Any parser producing a canonical ScientificDocument."""

    name: str
    version: str

    def parse(self, pdf_path: Path) -> ScientificDocument: ...
