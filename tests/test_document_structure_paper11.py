"""Layer 1 DoD checks on pilot paper 11 (SiC PL, multi-condition)."""

from __future__ import annotations

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.models.document import PARSER_CONFIG, parser_config_hash
from tests.conftest import pilot_pdf


def test_paper_id_stable_from_filename() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    assert doc.paper_id == "11_arxiv_2404.09906.pdf"


def test_document_version_deterministic_and_config_sensitive() -> None:
    parser = PyMuPDFDocumentParser()
    pdf = pilot_pdf("11_arxiv_2404.09906.pdf")
    v1 = parser.parse(pdf).document_version_id
    v2 = parser.parse(pdf).document_version_id
    assert v1 == v2
    assert v1 == __import__("ultrafast_ingestion.models.document", fromlist=["ScientificDocument"]).ScientificDocument.version_id("11_arxiv_2404.09906.pdf")
    alt = PyMuPDFDocumentParser({**PARSER_CONFIG, "sort_blocks": False}).parse(pdf)
    assert alt.document_version_id != v1


def test_blocks_are_page_bbox_reversible() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    for page_index, page in enumerate(doc.pages):
        assert page_index < len(doc.pages)
        for block in page:
            x0, y0, x1, y1 = block.bbox
            assert x1 > x0 and y1 > y0
            assert block.page_index == page_index
            assert doc.block_by_id(block.block_id()) is block


def test_sections_preserve_reading_order() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    assert len(doc.sections) >= 4
    for section in doc.sections:
        orders = [
            doc.block_by_id(bid).reading_order
            for bid in section.block_ids
            if doc.block_by_id(bid) is not None
        ]
        assert orders == sorted(orders), f"reading order broken in {section.path}"


def test_methods_section_contains_laser_conditions() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    methods = [s for s in doc.sections if s.section_type == "methods"]
    assert methods, "no methods section detected"
    text = " ".join(b.text for s in methods for b in [doc.block_by_id(i) for i in s.block_ids] if b)
    assert "1030 nm" in text and "383 fs" in text


def test_table_caption_detected() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    captions = [c for c in doc.captions if "TABLE" in c.text.upper()]
    assert captions, "Table I caption not detected"
