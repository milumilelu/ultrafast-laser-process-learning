"""Offline ingestion: parse each PDF once, persist semantic blocks, build both indexes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ultrafast_ingestion.parsers.pymupdf_parser import PyMuPDFDocumentParser
from ultrafast_knowledge.evidence_pipeline.blocks import SemanticBlockBuilder
from ultrafast_knowledge.evidence_pipeline.hybrid_index import HybridScientificIndex
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore
from ultrafast_knowledge.evidence_pipeline.tables.camelot_adapter import (
    CamelotMLTableExtractor,
    CamelotWorkerTableExtractor,
)
from ultrafast_knowledge.evidence_pipeline.tables.extractor import (
    TableExtractionError,
    TableExtractor,
)
from ultrafast_knowledge.evidence_pipeline.tables.normalizer import TableNormalizer


class ScientificIndexIngestionService:
    def __init__(
        self,
        store: ScientificIndexStore,
        *,
        parser: PyMuPDFDocumentParser | None = None,
        block_builder: SemanticBlockBuilder | None = None,
        index: HybridScientificIndex | None = None,
        table_extractor: TableExtractor | None = None,
        table_normalizer: TableNormalizer | None = None,
    ) -> None:
        self.store = store
        self.parser = parser or PyMuPDFDocumentParser()
        self.block_builder = block_builder or SemanticBlockBuilder()
        self.index = index or HybridScientificIndex(store)
        self.table_extractor = table_extractor or self._default_table_extractor()
        self.table_normalizer = table_normalizer or TableNormalizer()

    @staticmethod
    def _default_table_extractor() -> TableExtractor:
        worker_python = os.environ.get("TABLE_EXTRACTOR_PYTHON")
        if worker_python:
            return CamelotWorkerTableExtractor(Path(worker_python))
        return CamelotMLTableExtractor()

    def ingest_pdf(
        self,
        pdf_path: Path,
        *,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        path = Path(pdf_path)
        document = self.parser.parse(path)
        paper_metadata = dict(metadata or {})
        tables = []
        try:
            raw_tables = self.table_extractor.extract(path)
            tables = self.table_normalizer.normalize(
                raw_tables,
                paper_id=document.paper_id,
                document_version_id=document.document_version_id,
                extractor_version=self.table_extractor.version,
                model_versions=dict(getattr(self.table_extractor, "model_versions", {})),
            )
        except TableExtractionError as exc:
            paper_metadata.setdefault("ingestion_warnings", []).append(
                f"TABLE_EXTRACTION_FAILED:{exc}"
            )
        paper = self.block_builder.build(
            document,
            title=title,
            metadata=paper_metadata,
            tables=tables,
        )
        self.store.upsert_paper(paper)
        return paper.document_version_id

    def ingest_many(
        self,
        papers: list[dict[str, Any]],
        *,
        rebuild: bool = True,
    ) -> dict[str, Any]:
        versions = [
            self.ingest_pdf(
                Path(item["pdf_path"]),
                title=str(item.get("title") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in papers
        ]
        revisions: dict[str, str] = {}
        if rebuild and versions:
            revisions = {
                "paper": self.index.rebuild("paper"),
                "block": self.index.rebuild("block"),
            }
        return {"document_versions": versions, "index_revisions": revisions}
