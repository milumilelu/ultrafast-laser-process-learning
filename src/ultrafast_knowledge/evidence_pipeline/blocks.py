"""Build provenance-preserving semantic blocks from a ScientificDocument."""

from __future__ import annotations

import re
from typing import Any

from ultrafast_ingestion.models.document import PageBlock, ScientificDocument
from ultrafast_ingestion.models.provenance import stable_hash
from ultrafast_knowledge.evidence_pipeline.schemas import (
    SemanticBlock,
    SemanticBlockType,
    StructuredScientificPaper,
)

_TABLE_CAPTION = re.compile(r"^\s*(?:table|tab\.)\s*[\dSIVX]", re.IGNORECASE)
_EQUATION = re.compile(
    r"(?:[A-Za-zΑ-Ωα-ω][A-Za-zΑ-Ωα-ω\d_]*\s*=\s*[^=]{2,}|∝|≈|≤|≥|\bexp\s*\(|\bln\s*\()"
)


class SemanticBlockBuilder:
    """Structural conversion only; it never truncates scientific text."""

    def build(
        self,
        document: ScientificDocument,
        *,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> StructuredScientificPaper:
        section_by_block: dict[str, Any] = {}
        for section in document.sections:
            for block_id in section.block_ids:
                section_by_block[block_id] = section

        ordered = sorted(
            (block for page in document.pages for block in page),
            key=lambda item: item.reading_order,
        )
        semantic: list[SemanticBlock] = []
        for block in ordered:
            section = section_by_block.get(block.block_id())
            block_type = self._type_for(block, getattr(section, "section_type", None))
            semantic.append(
                SemanticBlock(
                    paper_id=document.paper_id,
                    document_version_id=document.document_version_id,
                    block_id=block.block_id(),
                    block_type=block_type,
                    page=block.page_index + 1,
                    pdf_page_index=block.page_index,
                    section_id=getattr(section, "section_id", None),
                    section_path=getattr(section, "path", None) or block.section_path or None,
                    section_type=getattr(section, "section_type", None),
                    section_title=getattr(section, "title", None),
                    text=block.text,
                    bbox=block.bbox,
                    source_text_type=block.text_source,
                )
            )
        self._link_tables(document, semantic)
        self._link_context(semantic)
        inferred_title = title.strip() or self._infer_title(semantic)
        abstract = "\n".join(
            block.text for block in semantic if block.section_type == "abstract"
        )
        return StructuredScientificPaper(
            paper_id=document.paper_id,
            document_version_id=document.document_version_id,
            title=inferred_title,
            abstract=abstract,
            metadata=dict(metadata or {}),
            blocks=semantic,
            pdf_path=document.pdf_path,
        )

    @staticmethod
    def _type_for(block: PageBlock, section_type: str | None) -> SemanticBlockType:
        if block.block_type == "caption":
            if _TABLE_CAPTION.search(block.text):
                return SemanticBlockType.TABLE_CAPTION
            return SemanticBlockType.FIGURE_CAPTION
        if _EQUATION.search(block.text) and len(block.text) <= 600:
            return SemanticBlockType.EQUATION
        if section_type == "methods":
            return SemanticBlockType.EXPERIMENTAL_SETUP
        if section_type in {"results", "discussion", "conclusion"}:
            return SemanticBlockType.RESULT_STATEMENT
        return SemanticBlockType.PARAGRAPH

    @staticmethod
    def _link_tables(document: ScientificDocument, blocks: list[SemanticBlock]) -> None:
        del document
        # Link by native page/read order only.  Numeric mention regexes and
        # unit parsers deliberately do not participate before retrieval.
        for index, caption in enumerate(blocks):
            if caption.block_type != SemanticBlockType.TABLE_CAPTION:
                continue
            caption.table_id = stable_hash(
                caption.document_version_id, "semantic-table", caption.block_id
            )
            same_page_nearby = [
                item
                for item in blocks[max(0, index - 3) : index + 4]
                if item.block_id != caption.block_id
                and item.pdf_page_index == caption.pdf_page_index
            ]
            caption.related_block_ids = [item.block_id for item in same_page_nearby]
            for nearby in same_page_nearby:
                nearby.related_block_ids = list(
                    dict.fromkeys([*nearby.related_block_ids, caption.block_id])
                )

    @staticmethod
    def _link_context(blocks: list[SemanticBlock]) -> None:
        for index, block in enumerate(blocks):
            if index:
                block.previous_block_id = blocks[index - 1].block_id
            if index + 1 < len(blocks):
                block.next_block_id = blocks[index + 1].block_id
            if block.block_type in {
                SemanticBlockType.TABLE_CAPTION,
                SemanticBlockType.FIGURE_CAPTION,
                SemanticBlockType.EQUATION,
            }:
                related: list[str] = []
                for nearby in blocks[max(0, index - 1) : index + 2]:
                    if nearby.block_id != block.block_id and nearby.pdf_page_index == block.pdf_page_index:
                        related.append(nearby.block_id)
                        if (
                            block.block_type == SemanticBlockType.EQUATION
                            and nearby.block_type == SemanticBlockType.PARAGRAPH
                        ):
                            nearby.block_type = SemanticBlockType.EQUATION_CONTEXT
                        if block.block_id not in nearby.related_block_ids:
                            nearby.related_block_ids.append(block.block_id)
                block.related_block_ids = list(
                    dict.fromkeys([*block.related_block_ids, *related])
                )

    @staticmethod
    def _infer_title(blocks: list[SemanticBlock]) -> str:
        first_page = [item.text.strip() for item in blocks if item.pdf_page_index == 0]
        candidates = [
            text.replace("\n", " ")
            for text in first_page[:8]
            if 20 <= len(text) <= 300 and "abstract" not in text.lower()
        ]
        return candidates[0] if candidates else ""
