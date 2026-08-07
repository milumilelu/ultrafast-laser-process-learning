"""A1 fixes: paper-level aggregation + table-like block detection."""

from __future__ import annotations

import pytest

from tests.conftest import DOC_BLOCK_TEXT, make_doc, make_mention
from ultrafast_ingestion.mentions.models import ContextClass
from ultrafast_ingestion.tables.detect import _is_table_like_block
from ultrafast_reconstructibility.adapter import paper_level_spec
from ultrafast_reconstructibility.models import FieldStatus

pytestmark = pytest.mark.unit


def _mention(doc, block, parameter, values, unit, context, raw, start, end):
    return make_mention(
        doc,
        block=block,
        parameter=parameter,
        values=values,
        raw_text=raw,
        start=start,
        end=end,
        unit=unit,
        context=context,
    )


def test_paper_level_prefers_process_context() -> None:
    """A1: 100 kHz (PROCESS) must win over 100 Hz (UNCLEAR noise)."""
    doc = make_doc()
    block = doc.pages[0][0]
    base = DOC_BLOCK_TEXT.index("200 kHz")
    process = _mention(doc, block, "frequency", [200.0], "kHz", ContextClass.PROCESS_CONTEXT, "200 kHz", base, base + 7)
    noise = _mention(doc, block, "frequency", [100.0], "Hz", ContextClass.UNCLEAR, "100 Hz", 0, 6)
    spec = paper_level_spec(doc, [process, noise])
    field = next(f for f in spec.fields if f.parameter == "frequency")
    assert field.values == (200.0,)
    assert field.unit == "kHz"
    assert field.field_status == FieldStatus.REPORTED_CLEAR


def test_paper_level_excludes_measurement_context() -> None:
    """40 MHz lifetime-laser frequency must not pollute processing fields."""
    doc = make_doc()
    block = doc.pages[0][0]
    base = DOC_BLOCK_TEXT.index("200 kHz")
    process = _mention(doc, block, "frequency", [200.0], "kHz", ContextClass.PROCESS_CONTEXT, "200 kHz", base, base + 7)
    measurement = _mention(doc, block, "frequency", [40.0], "MHz", ContextClass.MEASUREMENT_OPTICS, "40 MHz", 0, 6)
    spec = paper_level_spec(doc, [process, measurement])
    field = next(f for f in spec.fields if f.parameter == "frequency")
    assert field.values == (200.0,)
    assert field.field_status == FieldStatus.REPORTED_CLEAR


def test_paper_level_conflict_preserved() -> None:
    """Two genuine PROCESS_CONTEXT values -> CONFLICT_PRESERVED."""
    doc = make_doc()
    block = doc.pages[0][0]
    base = DOC_BLOCK_TEXT.index("200 kHz")
    a = _mention(doc, block, "frequency", [200.0], "kHz", ContextClass.PROCESS_CONTEXT, "200 kHz", base, base + 7)
    b = _mention(doc, block, "frequency", [100.0], "kHz", ContextClass.PROCESS_CONTEXT, "100 kHz", base, base + 7)
    spec = paper_level_spec(doc, [a, b])
    field = next(f for f in spec.fields if f.parameter == "frequency")
    assert field.field_status == FieldStatus.CONFLICT_PRESERVED


def test_paper_level_uses_unclear_when_no_process_context() -> None:
    doc = make_doc()
    block = doc.pages[0][0]
    base = DOC_BLOCK_TEXT.index("200 kHz")
    m = _mention(doc, block, "scan_speed", [30.0], "mm/s", ContextClass.UNCLEAR, "30 mm/s", base, base + 7)
    spec = paper_level_spec(doc, [m])
    field = next(f for f in spec.fields if f.parameter == "scan_speed")
    assert field.field_status == FieldStatus.REPORTED_CLEAR
    assert field.values == (30.0,)


def test_table_like_block_detection() -> None:
    """Row-numbered table body blocks (mislabelled heading) are table-like."""
    from tests.conftest import make_doc as md
    from ultrafast_ingestion.models.document import PageBlock

    doc = md()
    block = PageBlock(
        paper_id=doc.paper_id,
        document_version_id=doc.document_version_id,
        page_index=0,
        bbox=(0.0, 0.0, 100.0, 100.0),
        block_index=9,
        reading_order=9,
        text="1 / 1000 / 50 / 950 / 3 / 120 / 10 / v\n"
             "2 / 500 / 25 / 475 / 3 / 120 / 10 / v\n"
             "3 / 50 / 50 / 950 / 3 / 120 / 10 / v",
        block_type="heading",
    )
    assert _is_table_like_block(block)
    prose = PageBlock(
        paper_id=doc.paper_id,
        document_version_id=doc.document_version_id,
        page_index=0,
        bbox=(0.0, 0.0, 100.0, 100.0),
        block_index=10,
        reading_order=10,
        text="Results and discussion section describing the drilled samples and their quality",
        block_type="heading",
    )
    assert not _is_table_like_block(prose)
