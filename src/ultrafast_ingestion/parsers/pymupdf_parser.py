"""PyMuPDF native-text structured parser (Layer 1, no OCR).

- page blocks with bbox from the PDF text layer (text_source=native)
- reading_order: per-page sort by (y0, x0); global monotonic index
- sections/captions assigned by section_builder
- paper_id derived from archive filename (<sha256>_<paper_id>.pdf)
- deterministic; never writes to legacy DB/RAG
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pymupdf

from ultrafast_ingestion.models.document import (
    PARSER_CONFIG,
    PARSER_NAME,
    PARSER_VERSION,
    SCHEMA_VERSION,
    PageBlock,
    ScientificDocument,
    config_hash,
)
from ultrafast_ingestion.structure.section_builder import build_sections


def paper_id_from_filename(path: Path) -> str:
    name = path.name
    stem = Path(name).stem
    if "_" in stem:
        head, _, rest = stem.partition("_")
        if len(head) == 16 and all(c in "0123456789abcdef" for c in head.lower()):
            return rest + ".pdf"
    return name


def pdf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PyMuPDFDocumentParser:
    name = PARSER_NAME
    version = PARSER_VERSION

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**PARSER_CONFIG, **(config or {})}

    def parse(self, pdf_path: Path) -> ScientificDocument:
        pdf_path = Path(pdf_path)
        paper_id = paper_id_from_filename(pdf_path)
        version_id = ScientificDocument.version_id(paper_id, config_hash(self.config))

        doc = pymupdf.open(str(pdf_path))
        pages: list[list[PageBlock]] = []
        all_blocks: list[PageBlock] = []
        global_order = 0
        for page_index in range(doc.page_count):
            page = doc[page_index]
            raw = page.get_text("dict")
            page_blocks: list[PageBlock] = []
            for block_index, block in enumerate(raw.get("blocks") or []):
                if block.get("type") != 0:
                    continue
                text = _block_text(block)
                if not text.strip():
                    continue
                bbox = tuple(float(v) for v in block["bbox"])
                pb = PageBlock(
                    paper_id=paper_id,
                    document_version_id=version_id,
                    page_index=page_index,
                    bbox=bbox,
                    block_index=block_index,
                    reading_order=0,
                    text=text,
                )
                page_blocks.append(pb)
            if self.config.get("sort_blocks", True):
                page_blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
            # reading order assigned AFTER layout sort (stable, deterministic)
            for pb in page_blocks:
                pb.reading_order = global_order
                global_order += 1
            pages.append(page_blocks)
            all_blocks.extend(page_blocks)

        all_blocks_by_id: dict[str, PageBlock] = {}
        for b in all_blocks:
            all_blocks_by_id[b.block_id()] = b

        sections, captions = build_sections(
            all_blocks,
            paper_id=paper_id,
            document_version_id=version_id,
            config=self.config,
        )

        return ScientificDocument(
            paper_id=paper_id,
            document_version_id=version_id,
            pdf_path=str(pdf_path),
            pdf_sha256=pdf_sha256(pdf_path),
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            schema_version=SCHEMA_VERSION,
            config_hash=config_hash(self.config),
            pages=pages,
            sections=sections,
            captions=captions,
            blocks_by_id=all_blocks_by_id,
        )


def _block_text(block: dict[str, Any]) -> str:
    lines = []
    for line in block.get("lines") or []:
        parts = []
        for span in line.get("spans") or []:
            parts.append(span.get("text") or "")
        lines.append("".join(parts))
    return "\n".join(lines).strip()
