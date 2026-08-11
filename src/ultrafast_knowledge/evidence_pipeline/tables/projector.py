"""Project normalized tables into stable, row-addressable retrieval blocks."""

from __future__ import annotations

import re

from ultrafast_ingestion.models.document import ScientificDocument
from ultrafast_ingestion.models.provenance import stable_hash
from ultrafast_knowledge.evidence_pipeline.schemas import SemanticBlock, SemanticBlockType
from ultrafast_knowledge.evidence_pipeline.tables.models import ScientificTable, TableWarning

_TABLE_CAPTION = re.compile(r"^\s*(?:table|tab\.)\s*[\dSIVX]", re.IGNORECASE)


class TableBlockProjector:
    def project(
        self,
        document: ScientificDocument,
        tables: list[ScientificTable],
        *,
        paper_title: str,
        paper_metadata: dict[str, object],
        existing_blocks: list[SemanticBlock],
    ) -> list[SemanticBlock]:
        caption_blocks = [
            block
            for block in existing_blocks
            if block.block_type == SemanticBlockType.TABLE_CAPTION
        ]
        used_captions: set[str] = set()
        output: list[SemanticBlock] = []
        for table in sorted(tables, key=lambda item: (item.page_start, item.table_id)):
            caption = self._caption_for(table, caption_blocks, used_captions)
            if caption is not None:
                table.caption = caption.text
                table.caption_block_id = caption.block_id
                caption.table_id = table.table_id
                used_captions.add(caption.block_id)
            else:
                table.warnings = list(
                    dict.fromkeys([*table.warnings, TableWarning.CAPTION_NOT_FOUND])
                )
            projected = self._table_blocks(
                table,
                paper_title=paper_title,
                paper_metadata=paper_metadata,
            )
            related_ids = [item.block_id for item in projected]
            for block in projected:
                block.related_block_ids = [
                    item_id for item_id in related_ids if item_id != block.block_id
                ]
                if caption is not None:
                    block.related_block_ids.append(caption.block_id)
            if caption is not None:
                caption.related_block_ids = list(
                    dict.fromkeys([*caption.related_block_ids, *related_ids])
                )
            output.extend(projected)
        for caption in caption_blocks:
            if caption.block_id in used_captions:
                continue
            unresolved = ScientificTable(
                table_id=stable_hash(
                    document.document_version_id,
                    "unresolved-table-caption",
                    caption.block_id,
                ),
                paper_id=document.paper_id,
                document_version_id=document.document_version_id,
                page_start=caption.page,
                page_end=caption.page,
                bboxes_by_page={caption.page: caption.bbox},
                caption=caption.text,
                caption_block_id=caption.block_id,
                source="UNRESOLVED",
                extractor_version="none",
                warnings=[TableWarning.TABLE_UNRESOLVED],
            )
            tables.append(unresolved)
            caption.table_id = unresolved.table_id
            projected = self._table_blocks(
                unresolved,
                paper_title=paper_title,
                paper_metadata=paper_metadata,
            )
            for block in projected:
                block.related_block_ids = [caption.block_id]
            caption.related_block_ids = list(
                dict.fromkeys(
                    [*caption.related_block_ids, *(item.block_id for item in projected)]
                )
            )
            output.extend(projected)
        return output

    @staticmethod
    def _caption_for(
        table: ScientificTable,
        captions: list[SemanticBlock],
        used: set[str],
    ) -> SemanticBlock | None:
        candidates = [
            item
            for item in captions
            if item.block_id not in used
            and table.page_start <= item.page <= table.page_end
            and _TABLE_CAPTION.search(item.text)
        ]
        return candidates[0] if candidates else None

    def _table_blocks(
        self,
        table: ScientificTable,
        *,
        paper_title: str,
        paper_metadata: dict[str, object],
    ) -> list[SemanticBlock]:
        fragment = table.source_fragments[0] if table.source_fragments else None
        bbox = fragment.bbox if fragment is not None else None
        metadata = " ".join(
            f"{key}: {value}"
            for key, value in paper_metadata.items()
            if key in {"material", "material_grade", "laser_type", "wavelength_nm", "process_type"}
            and value not in (None, "")
        )
        caption = table.caption or "[caption unavailable]"
        headers = self._render_matrix(table.headers) or "[header unavailable]"
        group_headers = self._render_matrix(table.group_headers)
        summary_id = stable_hash(table.document_version_id, table.table_id, "summary")
        common = (
            f"Paper: {paper_title}\n"
            f"Context: {metadata}\n" if metadata else f"Paper: {paper_title}\n"
        )
        summary_text = "\n".join(
            item
            for item in (
                f"TABLE CAPTION: {caption}",
                f"GROUP HEADERS: {group_headers}" if group_headers else "",
                f"COLUMN HEADERS: {headers}",
            )
            if item
        )
        blocks = [
            SemanticBlock(
                paper_id=table.paper_id,
                document_version_id=table.document_version_id,
                block_id=summary_id,
                block_type=SemanticBlockType.TABLE,
                page=table.page_start,
                pdf_page_index=table.page_start - 1,
                table_id=table.table_id,
                table_role="summary",
                text=summary_text,
                retrieval_text=f"{common}Block type: table summary\n{summary_text}",
                bbox=bbox,
                source_text_type="camelot_ml",
            )
        ]
        header_indices = set(table.header_row_indices) | set(table.group_header_row_indices)
        for row_index, row in enumerate(table.rows):
            if row_index in header_indices:
                continue
            row_text = " | ".join(cell or "[empty]" for cell in row)
            text = "\n".join(
                item
                for item in (
                    f"TABLE CAPTION: {caption}",
                    f"GROUP HEADERS: {group_headers}" if group_headers else "",
                    f"COLUMN HEADERS: {headers}",
                    f"ROW {row_index}: {row_text}",
                )
                if item
            )
            block_id = stable_hash(
                table.document_version_id, table.table_id, "row", str(row_index)
            )
            blocks.append(
                SemanticBlock(
                    paper_id=table.paper_id,
                    document_version_id=table.document_version_id,
                    block_id=block_id,
                    block_type=SemanticBlockType.TABLE,
                    page=table.page_start,
                    pdf_page_index=table.page_start - 1,
                    table_id=table.table_id,
                    table_role="row",
                    table_row_index=row_index,
                    text=text,
                    retrieval_text=f"{common}Block type: table row\n{text}",
                    bbox=bbox,
                    source_text_type="camelot_ml",
                )
            )
        return blocks

    @staticmethod
    def _render_matrix(rows: list[list[str]]) -> str:
        return " || ".join(" | ".join(cell or "[empty]" for cell in row) for row in rows)
