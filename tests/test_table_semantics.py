"""TableSemanticType tests: synthetic (unit) + pilot PDFs."""

from __future__ import annotations

import pytest

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.models.document import PageBlock
from ultrafast_ingestion.tables.classify import _parse_rows_from_block, classify_table
from ultrafast_ingestion.tables.models import (
    RowKind,
    TableRegion,
    TableSemanticType,
    table_regions,
)
from tests.conftest import pilot_pdf

pytestmark = pytest.mark.unit


def _region(text: str) -> TableRegion:
    block = PageBlock(
        paper_id="t", document_version_id="v", page_index=0,
        bbox=(0, 0, 100, 100), block_index=0, reading_order=0, text=text,
    )
    region = TableRegion(table_id="t1", semantic_type=TableSemanticType.UNKNOWN)
    region.blocks = [block]
    return classify_table(region, None)


def test_key_value_setup() -> None:
    text = "Wavelength(nm)\n355\nFluence range (J/cm2)\n2.3–7.0\nPulse width (ps)\n10"
    region = _region(text)
    assert region.semantic_type == TableSemanticType.KEY_VALUE_SETUP
    cells = [c for row in region.rows for c in row.cells]
    params = {c.parameter for c in cells}
    assert params == {"wavelength", "fluence", "pulse_width"}
    fluence = next(c for c in cells if c.parameter == "fluence")
    assert fluence.value2 == 7.0


def test_comparison_table_with_this_work_rows() -> None:
    text = (
        "Reference λ tp Laser Focusing Objective EP IP Comments\n"
        "19 790 nm 250 fs 1.4 NA 60x oil 10.7 nJ 22.2 TW/cm2 Threshold\n"
        "This work 1030 nm 383 fs 0.4 NA 20x 60 nJ 5 TW/cm2 Onset\n"
        "This work 1030 nm 383 fs 0.4 NA 20x 230 nJ 19.2 TW/cm2 Onset pristine"
    )
    region = _region(text)
    assert region.semantic_type == TableSemanticType.COMPARISON_TABLE
    kinds = {r.kind for r in region.rows if r.cells}
    assert kinds == {RowKind.THIS_WORK, RowKind.REFERENCE}


def test_experiment_rows() -> None:
    text = (
        "Exp P (W) f (kHz) v (mm/s)\n"
        "1 3 50 100\n2 4 100 200\n"
    )
    region = _region(text)
    assert region.semantic_type in (TableSemanticType.EXPERIMENT_ROWS, TableSemanticType.UNKNOWN)


def test_split_rows_merged_comparison_block() -> None:
    text = (
        "19 790 nm 250 fs 1.4 NA 60x 10.7 nJ 22.2 TW/cm2\n"
        "This work 1030 nm 383 fs 0.4 NA 20x 60 nJ 5 TW/cm2"
    )
    rows = _parse_rows_from_block(text, "b1")
    kinds = {r.kind for r in rows}
    assert RowKind.REFERENCE in kinds and RowKind.THIS_WORK in kinds


# ---------------- pilot-level (requires archive) ------------------------
pilot_tests = pytest.mark.pilot


@pilot_tests
def test_paper11_table_i_is_comparison() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    regions = table_regions(doc)
    comp = [r for r in regions if r.semantic_type == TableSemanticType.COMPARISON_TABLE]
    assert comp, "paper 11 Table I must be COMPARISON_TABLE"
    kinds = {row.kind for row in comp[0].rows if row.cells}
    assert RowKind.THIS_WORK in kinds and RowKind.REFERENCE in kinds


@pilot_tests
def test_flat_top_table_is_key_value() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("Flat-top picosecond laser texturing of CFRP.pdf"))
    regions = table_regions(doc)
    kv = [r for r in regions if r.semantic_type == TableSemanticType.KEY_VALUE_SETUP]
    assert kv, "Flat-top Table I must be KEY_VALUE_SETUP"
    cells = [c for row in kv[0].rows for c in row.cells]
    assert {c.parameter for c in cells} == {
        "wavelength", "fluence", "pulse_width", "spot_size", "scan_speed", "frequency",
    }
