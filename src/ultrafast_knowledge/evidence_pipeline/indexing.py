"""Offline ingestion: parse each PDF once, persist semantic blocks, build both indexes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ultrafast_ingestion.parsers.pymupdf_parser import PyMuPDFDocumentParser
from ultrafast_knowledge.evidence_pipeline.blocks import SemanticBlockBuilder
from ultrafast_knowledge.evidence_pipeline.hybrid_index import HybridScientificIndex
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore


class ScientificIndexIngestionService:
    def __init__(
        self,
        store: ScientificIndexStore,
        *,
        parser: PyMuPDFDocumentParser | None = None,
        block_builder: SemanticBlockBuilder | None = None,
        index: HybridScientificIndex | None = None,
    ) -> None:
        self.store = store
        self.parser = parser or PyMuPDFDocumentParser()
        self.block_builder = block_builder or SemanticBlockBuilder()
        self.index = index or HybridScientificIndex(store)

    def ingest_pdf(
        self,
        pdf_path: Path,
        *,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        document = self.parser.parse(Path(pdf_path))
        paper = self.block_builder.build(document, title=title, metadata=metadata)
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
