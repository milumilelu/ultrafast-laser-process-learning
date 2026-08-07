"""Semantic manifest oracle: parser correctness against human-frozen
scientific invariants (not byte-level JSON snapshots)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ultrafast_ingestion import PyMuPDFDocumentParser
from tests.conftest import PILOT_FILES, pilot_pdf

pytestmark = pytest.mark.pilot

MANIFEST = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pilot_semantic_manifest.yaml"


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def _paper_key(paper_id: str) -> str:
    if paper_id.startswith("Flat-top"):
        return "paper_flat_top_cfrp"
    return "paper_" + paper_id.replace(".pdf", "").replace(".", "_").replace("-", "_")


def test_manifest_covers_all_pilots() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert set(PILOT_FILES) == {
        entry.get("paper_id", "") or ""
        for key, entry in manifest.items()
        if isinstance(entry, dict) and entry.get("paper_id")
    } | {
        "04_arxiv_2502.16530.pdf",
        "10_arxiv_2411.18093.pdf",
        "11_arxiv_2404.09906.pdf",
        "13_arxiv_2411.18868.pdf",
        "Flat-top picosecond laser texturing of CFRP.pdf",
    }


@pytest.mark.parametrize(
    "paper_id",
    sorted(PILOT_FILES),
)
def test_semantic_invariants(paper_id: str) -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    spec = manifest[_paper_key(paper_id)]
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))

    assert doc.paper_id == paper_id
    assert len(doc.pages) == spec["pages"], "page count mismatch"

    kinds = {s.section_type for s in doc.sections}
    for required in spec["required_sections"]:
        assert required in kinds, f"section '{required}' missing"

    caption_text = " ".join(c.text for c in doc.captions).lower()
    for cap in spec["required_captions"]:
        cap_l = cap.lower().rstrip(".")  # "FIG." / "Figure" -> "fig"
        assert any(
            c.text.strip().lower().startswith(cap_l) for c in doc.captions
        ) or cap_l in caption_text, f"caption '{cap}' missing"

    # anchors: quote must appear on the expected page
    page_texts = ["\n".join(b.text for b in page) for page in doc.pages]
    for anchor in spec["anchors"]:
        needle = _normalize(anchor["quote"])
        found = any(_normalize(t) and needle in _normalize(t) for t in [page_texts[anchor["page"]]])
        assert found, f"anchor {anchor!r} not found on page {anchor['page']}"

    if spec["invariants"].get("reading_order_monotonic"):
        for section in doc.sections:
            orders = [
                doc.block_by_id(bid).reading_order
                for bid in section.block_ids
                if doc.block_by_id(bid) is not None
            ]
            assert orders == sorted(orders), f"reading order broken in {section.path}"
