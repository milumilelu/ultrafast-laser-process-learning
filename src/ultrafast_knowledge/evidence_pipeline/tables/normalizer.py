"""Conservative, deterministic table normalization; never uses an LLM."""

from __future__ import annotations

import json
import re
from collections import Counter
from itertools import pairwise

from ultrafast_ingestion.models.provenance import stable_hash
from ultrafast_knowledge.evidence_pipeline.tables.models import (
    RawExtractedTable,
    ScientificTable,
    TableSourceFragment,
    TableWarning,
)

NORMALIZATION_VERSION = "table-normalization-v1"
_FOOTER = re.compile(
    r"(?:copyright|all rights reserved|doi\s*:|https?://|^\s*\d+\s*$)",
    re.IGNORECASE,
)


class TableNormalizer:
    """Normalize shape while retaining the unmodified matrix for audit."""

    def normalize(
        self,
        raw_tables: list[RawExtractedTable],
        *,
        paper_id: str,
        document_version_id: str,
        extractor_version: str,
        model_versions: dict[str, str] | None = None,
    ) -> list[ScientificTable]:
        tables = [
            self._one(
                raw,
                paper_id=paper_id,
                document_version_id=document_version_id,
                extractor_version=extractor_version,
                model_versions=model_versions or {},
            )
            for raw in raw_tables
        ]
        self._mark_continuation_candidates(tables)
        return tables

    def _one(
        self,
        raw: RawExtractedTable,
        *,
        paper_id: str,
        document_version_id: str,
        extractor_version: str,
        model_versions: dict[str, str],
    ) -> ScientificTable:
        raw_rows = [[str(cell) for cell in row] for row in raw.rows]
        rows = [[self._clean_cell(cell) for cell in row] for row in raw_rows]
        rows = [row for row in rows if any(row)]
        warnings: list[TableWarning] = []
        widths = {len(row) for row in rows}
        if len(widths) > 1:
            warnings.append(TableWarning.IRREGULAR_ROW_WIDTH)
        width = max(widths, default=0)
        rows = [row + [""] * (width - len(row)) for row in rows]
        nonempty_columns = [
            index for index in range(width) if any(row[index] for row in rows)
        ]
        rows = [[row[index] for index in nonempty_columns] for row in rows]
        if rows and any(_FOOTER.search(" ".join(row)) for row in rows):
            warnings.append(TableWarning.SUSPECT_PAGE_FOOTER)
        if not rows or len(rows) < 2 or not nonempty_columns:
            warnings.append(TableWarning.LOW_STRUCTURE_CONFIDENCE)

        header_indices, group_indices = self._infer_headers(rows)
        table_id = stable_hash(
            document_version_id,
            "camelot-ml-table",
            extractor_version,
            NORMALIZATION_VERSION,
            json.dumps(model_versions, sort_keys=True),
            str(raw.page),
            str(raw.table_index),
            repr(raw.bbox),
        )
        return ScientificTable(
            table_id=table_id,
            paper_id=paper_id,
            document_version_id=document_version_id,
            page_start=raw.page,
            page_end=raw.page,
            bboxes_by_page={raw.page: raw.bbox},
            rows=rows,
            raw_rows=raw_rows,
            header_row_indices=header_indices,
            group_header_row_indices=group_indices,
            extractor_version=extractor_version,
            model_versions=model_versions,
            normalization_version=NORMALIZATION_VERSION,
            warnings=list(dict.fromkeys(warnings)),
            source_fragments=[
                TableSourceFragment(
                    page=raw.page,
                    pdf_page_index=raw.pdf_page_index,
                    bbox=raw.bbox,
                    extractor_table_index=raw.table_index,
                )
            ],
        )

    @staticmethod
    def _clean_cell(value: str) -> str:
        return " ".join(value.replace("\x00", "").split())

    @staticmethod
    def _infer_headers(rows: list[list[str]]) -> tuple[list[int], list[int]]:
        if not rows:
            return [], []
        # Conservative: Camelot first row is the only universally auditable
        # header candidate. A sparse first row followed by a denser row is a
        # group header, and the second row becomes the column header.
        first_nonempty = sum(bool(cell) for cell in rows[0])
        if len(rows) > 1:
            second_nonempty = sum(bool(cell) for cell in rows[1])
            repeated = Counter(cell for cell in rows[0] if cell)
            group_like = first_nonempty < second_nonempty or any(
                count > 1 for count in repeated.values()
            )
            if group_like:
                return [1], [0]
        return [0], []

    @staticmethod
    def _mark_continuation_candidates(tables: list[ScientificTable]) -> None:
        ordered = sorted(tables, key=lambda item: (item.page_start, item.table_id))
        for previous, current in pairwise(ordered):
            if current.page_start != previous.page_end + 1:
                continue
            if not previous.rows or not current.rows:
                continue
            if previous.column_count != current.column_count:
                continue
            if previous.rows[0] != current.rows[0]:
                continue
            previous.warnings = list(
                dict.fromkeys([*previous.warnings, TableWarning.POSSIBLE_CONTINUATION])
            )
            current.warnings = list(
                dict.fromkeys([*current.warnings, TableWarning.POSSIBLE_CONTINUATION])
            )
