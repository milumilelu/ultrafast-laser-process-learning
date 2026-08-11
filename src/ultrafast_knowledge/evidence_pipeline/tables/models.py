"""Versioned contracts for raw and normalized scientific tables."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TableWarning(StrEnum):
    IRREGULAR_ROW_WIDTH = "IRREGULAR_ROW_WIDTH"
    SUSPECT_PAGE_HEADER = "SUSPECT_PAGE_HEADER"
    SUSPECT_PAGE_FOOTER = "SUSPECT_PAGE_FOOTER"
    CAPTION_NOT_FOUND = "CAPTION_NOT_FOUND"
    LOW_STRUCTURE_CONFIDENCE = "LOW_STRUCTURE_CONFIDENCE"
    POSSIBLE_CONTINUATION = "POSSIBLE_CONTINUATION"
    STACKED_CONTIGUOUS = "STACKED_CONTIGUOUS"
    TABLE_UNRESOLVED = "TABLE_UNRESOLVED"


class TableSourceFragment(BaseModel):
    page: int
    pdf_page_index: int
    bbox: tuple[float, float, float, float] | None = None
    extractor_table_index: int = 0


class RawExtractedTable(BaseModel):
    """Lossless adapter output before project-specific normalization."""

    page: int
    pdf_page_index: int
    table_index: int
    bbox: tuple[float, float, float, float] | None = None
    rows: list[list[str]] = Field(default_factory=list)
    parsing_report: dict[str, object] = Field(default_factory=dict)


class ScientificTable(BaseModel):
    table_id: str
    paper_id: str
    document_version_id: str
    page_start: int
    page_end: int
    bboxes_by_page: dict[int, tuple[float, float, float, float] | None]
    caption: str = ""
    caption_block_id: str | None = None
    rows: list[list[str]] = Field(default_factory=list)
    raw_rows: list[list[str]] = Field(default_factory=list)
    header_row_indices: list[int] = Field(default_factory=list)
    group_header_row_indices: list[int] = Field(default_factory=list)
    source: str = "CAMELOT_ML"
    extractor_version: str = "unknown"
    model_versions: dict[str, str] = Field(default_factory=dict)
    normalization_version: str = "table-normalization-v1"
    warnings: list[TableWarning] = Field(default_factory=list)
    source_fragments: list[TableSourceFragment] = Field(default_factory=list)

    @property
    def column_count(self) -> int:
        return max((len(row) for row in self.rows), default=0)

    @property
    def headers(self) -> list[list[str]]:
        return [self.rows[index] for index in self.header_row_indices if index < len(self.rows)]

    @property
    def group_headers(self) -> list[list[str]]:
        return [
            self.rows[index]
            for index in self.group_header_row_indices
            if index < len(self.rows)
        ]
