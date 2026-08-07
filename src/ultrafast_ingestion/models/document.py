"""ScientificDocument domain model (Layer 1)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ultrafast_ingestion.models.provenance import ProvenanceAnchor, stable_hash

PARSER_NAME = "pymupdf"
PARSER_VERSION = "0.1.0"
SCHEMA_VERSION = "document-v0.1"

# Headings below are handled by section_builder; parser config hash keeps
# determinism across config changes.
PARSER_CONFIG: dict[str, Any] = {
    "sort_blocks": True,
    "caption_prefixes": ["fig.", "fig ", "table", "tab. "],
    "max_heading_chars": 120,
}


def parser_config_hash() -> str:
    return stable_hash(PARSER_CONFIG)


def config_hash(config: dict[str, Any]) -> str:
    return stable_hash(config)


@dataclass(slots=True)
class PageBlock:
    paper_id: str
    document_version_id: str
    page_index: int
    bbox: tuple[float, float, float, float]
    block_index: int
    reading_order: int
    text: str
    text_source: str = "native"
    section_id: str = ""
    section_path: str = ""
    block_type: str = "body"  # body | heading | caption

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bbox"] = [round(x, 2) for x in self.bbox]
        return data

    def block_id(self) -> str:
        return f"{self.paper_id}:p{self.page_index}:b{self.block_index}"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageBlock:
        return cls(**{**data, "bbox": tuple(data.get("bbox") or (0, 0, 0, 0))})


@dataclass(slots=True)
class Paragraph:
    paragraph_id: str
    section_path: str
    block_ids: list[str]
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Section:
    section_id: str
    title: str
    section_type: str
    level: int
    page_start: int
    page_end: int
    path: str
    block_ids: list[str] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "section_type": self.section_type,
            "level": self.level,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "path": self.path,
            "block_ids": list(self.block_ids),
            "paragraphs": [p.to_dict() for p in self.paragraphs],
        }


@dataclass(slots=True)
class ScientificDocument:
    paper_id: str
    document_version_id: str
    pdf_path: str
    pdf_sha256: str
    parser_name: str
    parser_version: str
    schema_version: str
    config_hash: str
    pages: list[list[PageBlock]]
    sections: list[Section]
    captions: list[PageBlock] = field(default_factory=list)
    blocks_by_id: dict[str, PageBlock] = field(default_factory=dict)

    @classmethod
    def version_id(cls, paper_id: str, cfg_hash: str | None = None) -> str:
        return stable_hash(
            paper_id,
            PARSER_NAME,
            PARSER_VERSION,
            cfg_hash or parser_config_hash(),
            SCHEMA_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "document_version_id": self.document_version_id,
            "pdf_path": self.pdf_path,
            "pdf_sha256": self.pdf_sha256,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "schema_version": self.schema_version,
            "config_hash": self.config_hash,
            "pages": [[b.to_dict() for b in page] for page in self.pages],
            "sections": [s.to_dict() for s in self.sections],
            "captions": [c.to_dict() for c in self.captions],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1, sort_keys=True)

    def write_artifact(self, out_dir: Path) -> Path:
        target = out_dir / self.paper_id
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{self.document_version_id}.json"
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    def block_by_id(self, block_id: str) -> PageBlock | None:
        return self.blocks_by_id.get(block_id)

    def anchor_for(self, block: PageBlock, char_start: int = 0, char_end: int = 0) -> ProvenanceAnchor:
        return ProvenanceAnchor.build(
            paper_id=self.paper_id,
            document_version_id=self.document_version_id,
            pdf_page_index=block.page_index,
            printed_page_label="",
            bbox=block.bbox,
            text=block.text,
            section_path=block.section_path,
            block_id=block.block_id(),
            char_start=char_start or None,
            char_end=char_end or None,
        )
