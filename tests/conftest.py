"""Shared fixtures: pilot paper PDFs (env-configured, no absolute paths).

Archive resolution order:
1. env ULTRAFAST_PILOT_ARCHIVE (explicit)
2. sibling directory "ultrafast agent" next to this repository
3. otherwise pilot fixtures skip (never silently pass)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ultrafast_ingestion.mentions.models import (
    AcceptanceStatus,
    ConditionMention,
    ContextClass,
    MentionValueType,
)
from ultrafast_ingestion.models.document import PageBlock, ScientificDocument, Section
from ultrafast_ingestion.models.provenance import stable_hash
from ultrafast_ingestion.tables.models import (
    RowKind,
    TableCell,
    TableRegion,
    TableRow,
    TableSemanticType,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

DOC_BLOCK_TEXT = "The laser was operated at 1030 nm with a repetition rate of 200 kHz and a pulse width of 300 fs."


def make_doc(
    paper_id: str = "p_test",
    version_id: str = "dv_test_0000000000000000",
) -> ScientificDocument:
    block = PageBlock(
        paper_id=paper_id,
        document_version_id=version_id,
        page_index=0,
        bbox=(0.0, 0.0, 500.0, 100.0),
        block_index=0,
        reading_order=0,
        text=DOC_BLOCK_TEXT,
        section_id="s1",
        section_path="Methods",
    )
    section = Section(
        section_id="s1",
        title="Methods",
        section_type="methods",
        level=1,
        page_start=0,
        page_end=0,
        path="Methods",
    )
    return ScientificDocument(
        paper_id=paper_id,
        document_version_id=version_id,
        pdf_path="",
        pdf_sha256="",
        parser_name="test",
        parser_version="0",
        schema_version="test",
        config_hash="test",
        pages=[[block]],
        sections=[section],
        blocks_by_id={block.block_id(): block},
    )


def make_mention(
    doc: ScientificDocument,
    *,
    block: PageBlock,
    parameter: str,
    values: list[float],
    raw_text: str,
    start: int,
    end: int,
    unit: str = "kHz",
    value_type: MentionValueType = MentionValueType.SCALAR,
    status: AcceptanceStatus = AcceptanceStatus.ACCEPTED,
    context: ContextClass = ContextClass.PROCESS_CONTEXT,
    reason: str = "",
) -> ConditionMention:
    return ConditionMention(
        mention_id=stable_hash(block.block_id(), str(start), str(end)),
        parameter=parameter,
        raw_text=raw_text,
        values=list(values),
        value_type=value_type,
        normalized_unit=unit,
        context_class=context,
        acceptance_status=status,
        rejection_reason=reason,
        anchor=doc.anchor_for(block, start, end),
    )


def make_region(
    block: PageBlock,
    *,
    table_id: str = "t1",
    semantic_type: TableSemanticType = TableSemanticType.EXPERIMENT_ROWS,
    row_kind: RowKind = RowKind.THIS_WORK,
) -> TableRegion:
    cells = [
        TableCell(
            value=515.0,
            unit="nm",
            parameter="wavelength",
            raw_text="515 nm",
            source_block_id=block.block_id(),
            source_row=1,
        ),
        TableCell(
            value=230.0,
            unit="fs",
            parameter="pulse_width",
            raw_text="230 fs",
            source_block_id=block.block_id(),
            source_row=1,
        ),
    ]
    rows = [TableRow(index=1, kind=row_kind, raw_text="", cells=cells)]
    return TableRegion(table_id=table_id, semantic_type=semantic_type, rows=rows)


from demo.t2_slice.resources import PILOT_FILES, resolve_literature_archive


def _archive_path() -> Path | None:
    try:
        return resolve_literature_archive()
    except RuntimeError:
        return None


ARCHIVE = _archive_path()


def pilot_pdf(paper_id: str) -> Path:
    if ARCHIVE is None:
        pytest.skip(
            "pilot PDF archive not found "
            "(set ULTRAFAST_PILOT_ARCHIVE or place 'ultrafast agent' as sibling)"
        )
    path = ARCHIVE / PILOT_FILES[paper_id]
    if not path.exists():
        pytest.skip(f"pilot PDF missing: {path}")
    return path


@pytest.fixture()
def pilot_11() -> Path:
    return pilot_pdf("11_arxiv_2404.09906.pdf")


@pytest.fixture()
def pilot_13() -> Path:
    return pilot_pdf("13_arxiv_2411.18868.pdf")
