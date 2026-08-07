"""O3: CandidateGrounder - deterministic grounding (contract §5, hard gate).

Covers EXACT / NORMALIZED_EXACT / CROSS_BLOCK_EXACT / FUZZY_UNIQUE /
AMBIGUOUS / UNRESOLVED plus gate semantics and the no-masquerade invariant.
"""

from __future__ import annotations

import pytest

from tests.test_discovery_windows import make_doc as make_multi_doc
from ultrafast_ingestion.candidates.models import GroundingStatus
from ultrafast_ingestion.discovery.grounder import CandidateGrounder
from ultrafast_ingestion.discovery.models import (
    CandidateKind,
    CandidateSkeleton,
    GroundingConfig,
    GroundingMatchType,
)
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder
from ultrafast_ingestion.models.provenance import stable_hash

pytestmark = pytest.mark.unit


def _skeleton(local_id: str, quote: str) -> CandidateSkeleton:
    return CandidateSkeleton(
        local_id=local_id,
        candidate_kind=CandidateKind.QUANTITY,
        concept_label="test quantity",
        verbatim_quote=quote,
        window_local_ref="w0",
    )


def _window_for_quote(doc, quote: str):
    """Find the discovery window containing the quote (multi-section doc)."""
    windows = DiscoveryWindowBuilder().build(doc)
    for window in windows:
        if quote in window.text or normalize(quote) in normalize(window.text):
            return window
    return windows[0]


def normalize(text: str) -> str:
    from ultrafast_ingestion.models.provenance import normalize_quote

    return normalize_quote(text)


def test_exact_match_with_precise_anchor() -> None:
    doc = make_multi_doc()
    quote = "The laser system delivered pulses at 1030 nm with 230 fs duration."
    window = _window_for_quote(doc, quote)
    result = CandidateGrounder().ground(doc, window, _skeleton("s0", quote))
    assert result.match_type == GroundingMatchType.EXACT
    assert result.status == GroundingStatus.GROUNDED
    assert result.gate() == "PASS"
    assert result.anchor is not None
    # precise char offsets inside the block
    block = doc.blocks_by_id[result.anchor.block_id]
    assert block.text[result.anchor.char_start : result.anchor.char_end] == quote


def test_normalized_exact_case_and_whitespace() -> None:
    doc = make_multi_doc()
    window = _window_for_quote(doc, "The laser system delivered pulses at 1030 nm with 230 fs duration.")
    # case + collapsed-whitespace difference
    altered = "  the  LASER system   delivered pulses at 1030 nm with 230 fs duration  "
    result = CandidateGrounder().ground(doc, window, _skeleton("s1", altered))
    assert result.match_type == GroundingMatchType.NORMALIZED_EXACT
    assert result.status == GroundingStatus.GROUNDED
    assert result.gate() == "PASS"
    assert result.anchor is not None


def test_cross_block_exact() -> None:
    doc = make_multi_doc()
    # a sentence that does NOT exist verbatim anywhere, split across two blocks
    half_a = "The stage was translated at"
    half_b = "a constant velocity of 10 mm/s during writing."
    template = doc.pages[0][0]
    b1 = type(template)(
        paper_id=template.paper_id,
        document_version_id=template.document_version_id,
        page_index=9,
        bbox=template.bbox,
        block_index=500,
        reading_order=500,
        text=half_a,
        section_path="1/methods/1",
        section_id=stable_hash(template.document_version_id, "x"),
    )
    b2 = type(template)(
        paper_id=template.paper_id,
        document_version_id=template.document_version_id,
        page_index=9,
        bbox=template.bbox,
        block_index=501,
        reading_order=501,
        text=half_b,
        section_path="1/methods/1",
        section_id=stable_hash(template.document_version_id, "y"),
    )
    doc.pages[0].extend([b1, b2])
    doc.blocks_by_id[b1.block_id()] = b1
    doc.blocks_by_id[b2.block_id()] = b2
    # methods window contains both new blocks (same section aggregation)
    windows = DiscoveryWindowBuilder().build(doc)
    window = next(w for w in windows if b1.block_id() in w.block_ids)
    result = CandidateGrounder().ground(
        doc, window, _skeleton("s2", f"{half_a} {half_b}")
    )
    assert result.match_type == GroundingMatchType.CROSS_BLOCK_EXACT
    assert result.gate() == "PASS"


def test_fuzzy_unique_and_no_masquerade() -> None:
    doc = make_multi_doc()
    quote = "The laser system delivered pulses at 1030 nm with 230 fs duration."
    window = _window_for_quote(doc, quote)
    # one token altered ("delivered" -> "delivers") -> fuzzy, unique
    altered = "The laser system delivers pulses at 1030 nm with 230 fs duration."
    result = CandidateGrounder().ground(doc, window, _skeleton("s3", altered))
    assert result.match_type == GroundingMatchType.FUZZY_UNIQUE
    assert result.status == GroundingStatus.GROUNDED
    assert result.gate() == "CONDITIONAL"
    # match_type is permanently recorded - never upgraded to an exact kind
    assert result.match_type == GroundingMatchType.FUZZY_UNIQUE


def test_fuzzy_below_threshold_unresolved() -> None:
    doc = make_multi_doc()
    quote = "The laser system delivered pulses at 1030 nm with 230 fs duration."
    window = _window_for_quote(doc, quote)
    degraded = "The laser system pulses 1030 nm 230 fs duration."
    result = CandidateGrounder().ground(doc, window, _skeleton("s4", degraded))
    assert result.match_type == GroundingMatchType.UNRESOLVED
    assert result.status == GroundingStatus.GROUNDING_UNRESOLVED
    assert result.gate() == "FAIL"


def test_hallucination_unresolved_never_promoted() -> None:
    doc = make_multi_doc()
    window = DiscoveryWindowBuilder().build(doc)[0]
    result = CandidateGrounder().ground(
        doc, window, _skeleton("s5", "laser power was 50 W")
    )
    assert result.match_type == GroundingMatchType.UNRESOLVED
    assert result.gate() == "FAIL"
    assert result.anchor is None


def test_ambiguous_multiple_locations() -> None:
    doc = make_multi_doc()
    # append a duplicate of the results sentence -> two exact locations
    template = doc.pages[0][0]
    dup = type(template)(
        paper_id=template.paper_id,
        document_version_id=template.document_version_id,
        page_index=7,
        bbox=template.bbox,
        block_index=600,
        reading_order=600,
        text="Scanning velocity strongly affected the heat-affected zone width.",
        section_path="1/results/1",
        section_id=template.section_id,
    )
    doc.pages[0].append(dup)
    doc.blocks_by_id[dup.block_id()] = dup
    quote = "Scanning velocity strongly affected the heat-affected zone width."
    window = _window_for_quote(doc, quote)
    result = CandidateGrounder().ground(doc, window, _skeleton("s6", quote))
    assert result.match_type == GroundingMatchType.AMBIGUOUS
    assert result.gate() == "FAIL"
    assert result.detail.get("hit_count", 0) >= 2


def test_empty_quote_unresolved() -> None:
    doc = make_multi_doc()
    window = DiscoveryWindowBuilder().build(doc)[0]
    result = CandidateGrounder().ground(doc, window, _skeleton("s7", "   "))
    assert result.match_type == GroundingMatchType.UNRESOLVED
    assert result.gate() == "FAIL"


def test_fuzzy_threshold_is_configurable() -> None:
    doc = make_multi_doc()
    quote = "The laser system delivered pulses at 1030 nm with 230 fs duration."
    window = _window_for_quote(doc, quote)
    altered = "The laser system delivers pulses at 1030 nm with 230 fs duration."
    strict = CandidateGrounder(GroundingConfig(fuzzy_token_coverage=0.99)).ground(
        doc, window, _skeleton("s8", altered)
    )
    assert strict.match_type == GroundingMatchType.UNRESOLVED
    loose = CandidateGrounder(GroundingConfig(fuzzy_token_coverage=0.8)).ground(
        doc, window, _skeleton("s9", altered)
    )
    assert loose.match_type == GroundingMatchType.FUZZY_UNIQUE
