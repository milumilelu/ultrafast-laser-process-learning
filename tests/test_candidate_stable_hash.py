"""Candidate identity determinism (CANDIDATE_LEDGER_V0_1.md §1.1, I6)."""

from __future__ import annotations

from tests.conftest import DOC_BLOCK_TEXT, make_doc, make_mention, make_region
from ultrafast_ingestion.candidates.ledger import build_ledger, legacy_cell_key
from ultrafast_ingestion.candidates.models import CandidateSourceType
from ultrafast_ingestion.mentions.models import AcceptanceStatus, ContextClass


def _ids(paper_id: str = "p_test", version_id: str = "dv_test_0000000000000000"):
    doc = make_doc(paper_id, version_id)
    block = doc.pages[0][0]
    mention = make_mention(
        doc,
        block=block,
        parameter="frequency",
        values=[200.0],
        raw_text="200 kHz",
        start=DOC_BLOCK_TEXT.index("200 kHz"),
        end=DOC_BLOCK_TEXT.index("200 kHz") + 7,
    )
    ledger = build_ledger(doc, [mention], [])
    return doc, block, ledger


def test_same_input_same_candidate_id() -> None:
    _, _, first = _ids()
    _, _, second = _ids()
    assert first.candidates[0].candidate_id == second.candidates[0].candidate_id
    assert first.ledger_version_id == second.ledger_version_id


def test_different_raw_content_different_id() -> None:
    doc, block, ledger = _ids()
    start = DOC_BLOCK_TEXT.index("200 kHz")
    other = make_mention(
        doc,
        block=block,
        parameter="frequency",
        values=[1000.0],
        raw_text="1 MHz",
        start=start,
        end=start + 6,
    )
    other_ledger = build_ledger(doc, [other], [])
    assert ledger.candidates[0].candidate_id != other_ledger.candidates[0].candidate_id


def test_different_document_version_different_id() -> None:
    _, _, ledger = _ids()
    _, _, other = _ids(version_id="dv_test_1111111111111111")
    assert ledger.candidates[0].candidate_id != other.candidates[0].candidate_id


def test_source_type_participates_in_identity() -> None:
    """A mention and a table cell with identical raw text never collide."""
    doc, block, ledger = _ids()
    mention_candidate = ledger.candidates[0]
    region = make_region(block)
    cell = region.rows[0].cells[0]
    cell_ledger = build_ledger(doc, [], [region])
    cell_candidate = next(
        c for c in cell_ledger.candidates if c.source_ref == legacy_cell_key(cell)
    )
    assert cell_candidate.candidate_id != mention_candidate.candidate_id
    assert cell_candidate.source_ref == legacy_cell_key(cell)


def test_rejected_and_accepted_mentions_of_same_span_differ_by_source_type() -> None:
    """Same span rejected vs accepted -> different source_type -> different id."""
    doc, block, _ = _ids()
    start = DOC_BLOCK_TEXT.index("200 kHz")
    rejected = make_mention(
        doc,
        block=block,
        parameter="frequency",
        values=[200.0],
        raw_text="200 kHz",
        start=start,
        end=start + 7,
        status=AcceptanceStatus.REJECTED_CONTEXT,
        context=ContextClass.EQUIPMENT_MODEL,
        reason="equipment model",
    )
    ledger = build_ledger(doc, [rejected], [])
    candidate = ledger.candidates[0]
    assert candidate.source_type == CandidateSourceType.REJECTED_CONDITION_MENTION
    _, _, accepted_ledger = _ids()
    assert candidate.candidate_id != accepted_ledger.candidates[0].candidate_id
