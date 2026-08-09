"""Table semantics verified only against original pilot PDFs."""

from __future__ import annotations

import pytest

from tests.conftest import pilot_pdf
from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.tables.models import RowKind, TableSemanticType, table_regions

pytestmark = pytest.mark.pilot


def test_paper11_table_i_is_comparison() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    regions = table_regions(doc)
    comparison = [
        region
        for region in regions
        if region.semantic_type == TableSemanticType.COMPARISON_TABLE
    ]
    assert comparison, "paper 11 Table I must be COMPARISON_TABLE"
    kinds = {row.kind for row in comparison[0].rows if row.cells}
    assert RowKind.THIS_WORK in kinds and RowKind.REFERENCE in kinds


def test_flat_top_table_is_key_value() -> None:
    doc = PyMuPDFDocumentParser().parse(
        pilot_pdf("Flat-top picosecond laser texturing of CFRP.pdf")
    )
    regions = table_regions(doc)
    key_value = [
        region
        for region in regions
        if region.semantic_type == TableSemanticType.KEY_VALUE_SETUP
    ]
    assert key_value, "Flat-top Table I must be KEY_VALUE_SETUP"
    cells = [cell for row in key_value[0].rows for cell in row.cells]
    assert {cell.parameter for cell in cells} == {
        "wavelength",
        "fluence",
        "pulse_width",
        "spot_size",
        "scan_speed",
        "frequency",
    }
