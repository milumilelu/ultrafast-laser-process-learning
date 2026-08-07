"""O1 pilot gates G5/G6 + Discovery Text Coverage (contract §13).

Runs over the 5 pilot PDFs; requires the archive (pytest.mark.pilot).
"""

from __future__ import annotations

import pytest

from tests.conftest import pilot_pdf
from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.discovery.discoverer import DiscoveryBatchBuilder
from ultrafast_ingestion.discovery.models import DiscoveryWindowConfig
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder
from ultrafast_ingestion.tables.models import table_regions

pytestmark = pytest.mark.pilot

PILOT_PAPERS = [
    "04_arxiv_2502.16530.pdf",
    "10_arxiv_2411.18093.pdf",
    "11_arxiv_2404.09906.pdf",
    "13_arxiv_2411.18868.pdf",
    "Flat-top picosecond laser texturing of CFRP.pdf",
]


@pytest.mark.parametrize("paper_id", PILOT_PAPERS)
def test_g5_table_atomicity(paper_id: str) -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    regions = table_regions(doc)
    windows = DiscoveryWindowBuilder(regions=regions).build(doc)
    window_blocks = [set(w.block_ids) for w in windows]
    for region in regions:
        if not region.blocks:
            continue
        ids = {b.block_id() for b in region.blocks}
        assert any(ids <= wb for wb in window_blocks), (
            f"table {region.table_id} split across windows"
        )


@pytest.mark.parametrize("paper_id", PILOT_PAPERS)
def test_g6_full_block_coverage(paper_id: str) -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    windows = DiscoveryWindowBuilder(regions=table_regions(doc)).build(doc)
    covered = {b for w in windows for b in w.block_ids}
    all_blocks = {b.block_id(): b for page in doc.pages for b in page}
    uncovered = {bid: b for bid, b in all_blocks.items() if bid not in covered}
    # discovery scope = non-references sections (contract §3: REFERENCES is
    # citation routing, never a scientific candidate source)
    scope_violations = {
        bid
        for bid, block in uncovered.items()
        if not block.section_path.startswith("1/references")
    }
    assert not scope_violations, f"eligible blocks never covered by any window: {scope_violations}"


@pytest.mark.parametrize("paper_id", PILOT_PAPERS)
def test_discovery_text_coverage_100_percent(paper_id: str) -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    coverage = DiscoveryWindowBuilder(regions=table_regions(doc)).coverage(doc)
    assert coverage["eligible_words"] > 0
    assert coverage["coverage"] >= 1.0, (
        f"Discovery Text Coverage {coverage['coverage']:.4f} "
        f"({coverage['covered_words']}/{coverage['eligible_words']} words) - "
        "windows must not silently exclude eligible text"
    )


@pytest.mark.parametrize("paper_id", PILOT_PAPERS)
def test_batch_coverage_of_all_windows(paper_id: str) -> None:
    """O2: every window lands in exactly one batch (batch-level coverage)."""
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    config = DiscoveryWindowConfig()
    windows = DiscoveryWindowBuilder(config=config, regions=table_regions(doc)).build(doc)
    batches = DiscoveryBatchBuilder(config=config, regions=table_regions(doc)).build(doc)
    assert windows, "no windows built"
    seen: dict[str, int] = {}
    for batch in batches:
        assert batch.paper_id == doc.paper_id
        for wid in batch.window_ids:
            seen[wid] = seen.get(wid, 0) + 1
    assert len(seen) == len(windows), "windows missing from batches"
    assert all(v == 1 for v in seen.values()), "window duplicated across batches"
