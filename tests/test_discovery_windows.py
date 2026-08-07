"""O1 DoD G1-G4/G7/G8: DiscoveryWindow + CandidateSkeleton (unit, no PDFs)."""

from __future__ import annotations

import pytest

from ultrafast_ingestion.discovery.models import (
    CandidateKind,
    CandidateSkeleton,
    DiscoveryWindow,
    DiscoveryWindowConfig,
)
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder
from ultrafast_ingestion.models.document import PageBlock, ScientificDocument, Section
from ultrafast_ingestion.models.provenance import stable_hash

pytestmark = pytest.mark.unit

METHODS_BLOCKS = [
    "The laser system delivered pulses at 1030 nm with 230 fs duration.",
    "A repetition rate of 200 kHz was used for all writing experiments.",
    "The beam was focused through an objective lens with NA 0.9.",
]
RESULTS_BLOCK = "Scanning velocity strongly affected the heat-affected zone width."
CAPTION_TEXT = "Fig. 1. Ablation depth as a function of accumulated dose."
REFERENCE_BLOCK = "J. Smith et al., Opt. Lett. 45, 1234 (2020)."


def _page_block(doc: ScientificDocument, page: int, text: str, section_path: str, btype: str = "body", idx: int = 0) -> PageBlock:
    return PageBlock(
        paper_id=doc.paper_id,
        document_version_id=doc.document_version_id,
        page_index=page,
        bbox=(0.0, float(idx), 500.0, float(idx) + 20.0),
        block_index=idx,
        reading_order=idx,
        text=text,
        section_id=stable_hash(doc.document_version_id, section_path, text[:8]),
        section_path=section_path,
        block_type=btype,
    )


def make_doc() -> ScientificDocument:
    paper_id = "p_windows"
    version = "dv_windows_00000000000000"
    doc = ScientificDocument(
        paper_id=paper_id,
        document_version_id=version,
        pdf_path="",
        pdf_sha256="",
        parser_name="test",
        parser_version="0",
        schema_version="test",
        config_hash="test",
        pages=[],
        sections=[],
        blocks_by_id={},
    )
    blocks: list[PageBlock] = []
    # preamble (unknown-ish section) must still be covered (G4)
    blocks.append(_page_block(doc, 0, "We report femtosecond laser processing of glass.", "0/preamble/1", idx=0))
    for i, text in enumerate(METHODS_BLOCKS):
        blocks.append(_page_block(doc, 0, text, "1/methods/1", idx=i + 1))
    blocks.append(_page_block(doc, 1, RESULTS_BLOCK, "1/results/1", idx=0))
    blocks.append(_page_block(doc, 1, CAPTION_TEXT, "", btype="caption", idx=1))
    blocks.append(_page_block(doc, 2, REFERENCE_BLOCK, "1/references/1", idx=0))
    # unnumbered heading matched as generic "section" type (G4)
    blocks.append(_page_block(doc, 2, "Depth measurements", "1/section/1", idx=1))
    blocks.append(_page_block(doc, 2, "Depth was measured by confocal microscopy.", "1/section/1", idx=2))

    doc.pages = [[b for b in blocks if b.page_index == p] for p in (0, 1, 2)]
    doc.blocks_by_id = {b.block_id(): b for b in blocks}
    for path, title in (
        ("0/preamble/1", "preamble"),
        ("1/methods/1", "Methods"),
        ("1/results/1", "Results"),
        ("1/references/1", "References"),
        ("1/section/1", "Depth measurements"),
    ):
        page_blocks = [b for b in blocks if b.section_path == path]
        doc.sections.append(
            Section(
                section_id=stable_hash(version, path),
                title=title,
                section_type=path.split("/")[1],
                level=1,
                page_start=min(b.page_index for b in page_blocks),
                page_end=max(b.page_index for b in page_blocks),
                path=path,
                block_ids=[b.block_id() for b in page_blocks],
            )
        )
    return doc


def test_g1_deterministic() -> None:
    doc = make_doc()
    first = DiscoveryWindowBuilder().build(doc)
    second = DiscoveryWindowBuilder().build(doc)
    assert [w.to_canonical_dict() for w in first] == [w.to_canonical_dict() for w in second]
    assert [w.window_id for w in first] == [w.window_id for w in second]


def test_g2_traceable_block_ids_and_page_range() -> None:
    doc = make_doc()
    for window in DiscoveryWindowBuilder().build(doc):
        assert window.block_ids
        for bid in window.block_ids:
            assert bid in doc.blocks_by_id, f"window references unknown block {bid}"
        pages = [doc.blocks_by_id[b].page_index for b in window.block_ids]
        assert window.page_range == (min(pages), max(pages))


def test_g3_never_crosses_paper() -> None:
    doc = make_doc()
    for window in DiscoveryWindowBuilder().build(doc):
        assert window.paper_id == doc.paper_id
        assert window.document_version_id == doc.document_version_id


def test_g4_no_text_loss_for_unknown_sections() -> None:
    """UNKNOWN/generic sections and preamble are processed, never excluded."""
    doc = make_doc()
    windows = DiscoveryWindowBuilder().build(doc)
    covered = {b for w in windows for b in w.block_ids}
    all_eligible = {
        b.block_id()
        for b in doc.blocks_by_id.values()
        if not b.section_path.startswith("1/references")
    }
    assert all_eligible <= covered


def test_section_boundary_preferred_cut() -> None:
    doc = make_doc()
    windows = DiscoveryWindowBuilder().build(doc)
    by_section: dict[str, list[DiscoveryWindow]] = {}
    for w in windows:
        by_section.setdefault(w.section_path, []).append(w)
    # methods blocks merged into one window, results into another
    assert len(by_section["1/methods/1"]) == 1
    assert len(by_section["1/results/1"]) == 1
    assert len(by_section["0/preamble/1"]) == 1
    # never mixes sections
    for w in windows:
        assert all(doc.blocks_by_id[b].section_path == w.section_path for b in w.block_ids)


def test_token_budget_aggregates_and_splits() -> None:
    doc = make_doc()
    config = DiscoveryWindowConfig(target_window_tokens=15, max_window_tokens=100)
    builder = DiscoveryWindowBuilder(config=config)
    methods_windows = [w for w in builder.build(doc) if w.section_path == "1/methods/1"]
    assert len(methods_windows) > 1, "small budget must split long sections"
    for w in methods_windows:
        assert len(w.text.split()) <= config.max_window_tokens


def test_oversized_block_gets_own_window() -> None:
    doc = make_doc()
    big = "word " * 3000
    block = _page_block(doc, 3, big, "1/methods/1", idx=99)
    doc.pages[0].append(block)
    doc.blocks_by_id[block.block_id()] = block
    config = DiscoveryWindowConfig(max_window_tokens=1000)
    windows = DiscoveryWindowBuilder(config=config).build(doc)
    hits = [w for w in windows if block.block_id() in w.block_ids]
    assert len(hits) == 1
    assert hits[0].block_ids == (block.block_id(),)


def test_caption_atomic_standalone_window() -> None:
    doc = make_doc()
    windows = DiscoveryWindowBuilder().build(doc)
    caption_windows = [w for w in windows if CAPTION_TEXT.splitlines()[0] in w.text]
    assert len(caption_windows) == 1
    w = caption_windows[0]
    assert w.routing_hint == "structured"
    assert w.caption_refs
    # caption never merged with body text
    assert len(w.block_ids) == 1


def test_references_excluded_from_windows() -> None:
    doc = make_doc()
    windows = DiscoveryWindowBuilder().build(doc)
    ref_blocks = {b.block_id() for b in doc.blocks_by_id.values() if b.section_path.startswith("1/references")}
    for w in windows:
        assert not (set(w.block_ids) & ref_blocks)


def test_g7_config_change_changes_window_identity() -> None:
    doc = make_doc()
    default = DiscoveryWindowBuilder().build(doc)
    tuned = DiscoveryWindowBuilder(
        config=DiscoveryWindowConfig(target_window_tokens=300)
    ).build(doc)
    assert [w.window_id for w in default] != [w.window_id for w in tuned]
    assert default[0].window_config_version != tuned[0].window_config_version


def test_coverage_is_full_on_unit_doc() -> None:
    doc = make_doc()
    coverage = DiscoveryWindowBuilder().coverage(doc)
    assert coverage["coverage"] == 1.0
    assert coverage["eligible_words"] > 0


def test_g8_skeleton_schema_is_closed() -> None:
    sk = CandidateSkeleton(
        local_id="c1",
        candidate_kind=CandidateKind.QUANTITY,
        concept_label="intra-burst pulse spacing",
        verbatim_quote="Eight pulses separated by 25 ns",
        window_local_ref="w0",
    )
    assert sk.to_canonical_dict() == {
        "local_id": "c1",
        "candidate_kind": "QUANTITY",
        "concept_label": "intra-burst pulse spacing",
        "verbatim_quote": "Eight pulses separated by 25 ns",
        "window_local_ref": "w0",
    }
    with pytest.raises(ValueError):
        CandidateSkeleton(
            local_id="c1",
            candidate_kind=CandidateKind.QUANTITY,
            concept_label="x",
            verbatim_quote="y",
            paper_id="sneaky",  # must be rejected (extra="forbid")
        )
