"""Layer 1 DoD checks on pilot paper 13 (SiC NIR emitters)."""

from __future__ import annotations

from ultrafast_ingestion import PyMuPDFDocumentParser
from tests.conftest import pilot_pdf


def test_paper_id_stable() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("13_arxiv_2411.18868.pdf"))
    assert doc.paper_id == "13_arxiv_2411.18868.pdf"


def test_sections_include_methods_and_references() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("13_arxiv_2411.18868.pdf"))
    kinds = {s.section_type for s in doc.sections}
    assert "methods" in kinds
    assert "references" in kinds


def test_figure_captions_detected() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("13_arxiv_2411.18868.pdf"))
    fig_caps = [c for c in doc.captions if c.text.strip().lower().startswith("fig")]
    assert fig_caps, "figure captions not detected"


def test_writing_parameters_recoverable_from_structure() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("13_arxiv_2411.18868.pdf"))
    methods = [s for s in doc.sections if s.section_type == "methods"]
    text = " ".join(
        b.text for s in methods for b in [doc.block_by_id(i) for i in s.block_ids] if b
    )
    assert "515 nm" in text and "200 kHz" in text and "230 fs" in text


def test_blocks_bbox_within_page() -> None:
    import pymupdf

    doc = PyMuPDFDocumentParser().parse(pilot_pdf("13_arxiv_2411.18868.pdf"))
    pdf = pymupdf.open(str(pilot_pdf("13_arxiv_2411.18868.pdf")))
    for page in doc.pages:
        rect = pdf[page[0].page_index].rect
        for block in page:
            x0, y0, x1, y1 = block.bbox
            assert 0 <= x0 < x1 <= rect.width + 1e-6
            assert 0 <= y0 < y1 <= rect.height + 1e-6
