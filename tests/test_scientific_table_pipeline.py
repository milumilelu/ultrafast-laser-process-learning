from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from ultrafast_ingestion.models.document import PageBlock, ScientificDocument
from ultrafast_knowledge.evidence_pipeline.blocks import SemanticBlockBuilder
from ultrafast_knowledge.evidence_pipeline.retrieval import TwoLevelEvidenceRetriever
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore
from ultrafast_knowledge.evidence_pipeline.tables.models import (
    RawExtractedTable,
    TableWarning,
)
from ultrafast_knowledge.evidence_pipeline.tables.normalizer import TableNormalizer


def _document() -> ScientificDocument:
    caption = PageBlock(
        paper_id="paper-1",
        document_version_id="doc-1",
        page_index=0,
        bbox=(40, 80, 500, 100),
        block_index=0,
        reading_order=0,
        text="Table 1. Ablation threshold measurements.",
        block_type="caption",
    )
    prose = PageBlock(
        paper_id="paper-1",
        document_version_id="doc-1",
        page_index=0,
        bbox=(40, 500, 500, 540),
        block_index=1,
        reading_order=1,
        text="Unrelated body text with 999 J/cm2.",
    )
    return ScientificDocument(
        paper_id="paper-1",
        document_version_id="doc-1",
        pdf_path="paper.pdf",
        pdf_sha256="sha",
        parser_name="test",
        parser_version="1",
        schema_version="1",
        config_hash="cfg",
        pages=[[caption, prose]],
        sections=[],
        captions=[caption],
        blocks_by_id={caption.block_id(): caption, prose.block_id(): prose},
    )


def _tables():
    raw = RawExtractedTable(
        page=1,
        pdf_page_index=0,
        table_index=0,
        bbox=(40, 120, 500, 450),
        rows=[
            ["Material", "Threshold", "Pulse width"],
            ["Diamond", "3.0 J/cm2", "30 fs"],
            ["SiC", "2.2 J/cm2", "100 fs"],
        ],
    )
    return TableNormalizer().normalize(
        [raw],
        paper_id="paper-1",
        document_version_id="doc-1",
        extractor_version="2.0.0",
        model_versions={"detection": "pinned-test-model"},
    )


def _store():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    @contextmanager
    def factory():
        yield connection

    return connection, ScientificIndexStore(factory)


def test_normalization_is_lossless_and_only_marks_continuation() -> None:
    raw = [
        RawExtractedTable(
            page=1,
            pdf_page_index=0,
            table_index=0,
            rows=[["A", "B"], ["1"]],
        ),
        RawExtractedTable(
            page=2,
            pdf_page_index=1,
            table_index=1,
            rows=[["A", "B"], ["2", "3"]],
        ),
    ]
    tables = TableNormalizer().normalize(
        raw,
        paper_id="paper",
        document_version_id="doc",
        extractor_version="2.0.0",
    )
    assert tables[0].raw_rows == [["A", "B"], ["1"]]
    assert tables[0].rows == [["A", "B"], ["1", ""]]
    assert TableWarning.IRREGULAR_ROW_WIDTH in tables[0].warnings
    assert all(TableWarning.POSSIBLE_CONTINUATION in table.warnings for table in tables)
    assert all(TableWarning.STACKED_CONTIGUOUS not in table.warnings for table in tables)


def test_table_projection_persistence_and_window_are_row_scoped() -> None:
    paper = SemanticBlockBuilder().build(
        _document(),
        title="Laser processing",
        metadata={"material": "diamond"},
        tables=_tables(),
    )
    table = paper.tables[0]
    table_blocks = [block for block in paper.blocks if block.table_id == table.table_id]
    rows = [block for block in table_blocks if block.table_role == "row"]
    assert table.caption.startswith("Table 1")
    assert len(rows) == 2
    assert "COLUMN HEADERS: Material | Threshold | Pulse width" in rows[0].text
    assert "Diamond | 3.0 J/cm2 | 30 fs" in rows[0].text

    connection, store = _store()
    try:
        store.upsert_paper(paper)
        restored = store.papers()[0]
        restored_row = next(block for block in restored.blocks if block.table_role == "row")
        assert restored.tables[0].rows == table.rows
        assert restored_row.table_row_index == 1

        members = TwoLevelEvidenceRetriever._table_window(
            restored_row,
            restored.blocks,
            {block.block_id: block for block in restored.blocks},
        )
        assert any(block.table_role == "summary" for block in members)
        assert any(block.block_type.value == "table_caption" for block in members)
        assert all("Unrelated body text" not in block.text for block in members)
        assert len([block for block in members if block.table_role == "row"]) <= 2
    finally:
        connection.close()


def test_unmatched_caption_is_persisted_as_unresolved() -> None:
    paper = SemanticBlockBuilder().build(
        _document(),
        title="Laser processing",
        tables=[],
    )
    assert len(paper.tables) == 1
    assert paper.tables[0].source == "UNRESOLVED"
    assert TableWarning.TABLE_UNRESOLVED in paper.tables[0].warnings
    assert any(block.table_role == "summary" for block in paper.blocks)
