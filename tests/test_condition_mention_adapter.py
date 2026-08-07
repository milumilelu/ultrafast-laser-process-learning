"""ConditionMention adapter (CANDIDATE_LEDGER_V0_1.md §2.3, I1)."""

from __future__ import annotations

from tests.conftest import DOC_BLOCK_TEXT, make_doc, make_mention
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import (
    DISCOVERY_METHOD_MENTION,
    GroundingStatus,
    MappingStatus,
    PromotionStatus,
    VerificationStatus,
)
from ultrafast_ingestion.mentions.models import AcceptanceStatus


def _accepted_mention():
    doc = make_doc()
    block = doc.pages[0][0]
    start = DOC_BLOCK_TEXT.index("200 kHz")
    mention = make_mention(
        doc,
        block=block,
        parameter="frequency",
        values=[200.0],
        raw_text="200 kHz",
        start=start,
        end=start + 7,
    )
    return build_ledger(doc, [mention], []), mention


def test_accepted_mention_exactly_one_candidate() -> None:
    ledger, mention = _accepted_mention()
    hits = [c for c in ledger.candidates if c.source_ref == mention.mention_id]
    assert len(hits) == 1
    candidate = hits[0]
    assert candidate.source_type.value == "CONDITION_MENTION"
    assert candidate.candidate_kind.value == "QUANTITY"
    assert candidate.concept_label == "frequency"
    assert candidate.raw_statement == "200 kHz"
    assert candidate.raw_value is None
    assert candidate.raw_unit is None


def test_accepted_mention_mapping_mapped() -> None:
    ledger, mention = _accepted_mention()
    candidate = next(c for c in ledger.candidates if c.source_ref == mention.mention_id)
    mapping = [m for m in ledger.mappings if m.candidate_id == candidate.candidate_id]
    assert len(mapping) == 1
    assert mapping[0].status == MappingStatus.MAPPED
    assert mapping[0].target_namespace == "experimental_condition"
    assert mapping[0].target_field == "frequency"


def test_accepted_mention_provenance_and_lifecycle() -> None:
    ledger, mention = _accepted_mention()
    candidate = next(c for c in ledger.candidates if c.source_ref == mention.mention_id)
    assert len(candidate.provenance_anchors) == 1
    anchor = candidate.provenance_anchors[0]
    assert anchor.block_id == mention.anchor.block_id
    assert anchor.quote_fingerprint == mention.anchor.quote_fingerprint
    assert anchor.char_start == mention.anchor.char_start
    assert candidate.grounding_status == GroundingStatus.GROUNDED
    assert candidate.verification_status == VerificationStatus.NOT_RUN
    # no compile_result -> no_compilation
    assert candidate.promotion_status == PromotionStatus.NOT_PROMOTED
    assert candidate.promotion_reason == "no_compilation"
    assert candidate.discovery_method == DISCOVERY_METHOD_MENTION
    assert candidate.source_detail["mention_id"] == mention.mention_id
    assert candidate.source_detail["values"] == [200.0]
    assert candidate.source_detail["normalized_unit"] == "kHz"


def test_ambiguous_context_mention_kept_with_ambiguous_mapping() -> None:
    doc = make_doc()
    block = doc.pages[0][0]
    start = DOC_BLOCK_TEXT.index("200 kHz")
    from tests.conftest import make_mention as mm

    mention = mm(
        doc,
        block=block,
        parameter="frequency",
        values=[1.0],
        raw_text="1 MHz",
        start=start,
        end=start + 6,
        unit="MHz",
        status=AcceptanceStatus.AMBIGUOUS_CONTEXT,
    )
    ledger = build_ledger(doc, [mention], [])
    candidate = ledger.candidates[0]
    assert candidate.source_type.value == "CONDITION_MENTION"
    mapping = ledger.mappings[0]
    assert mapping.status == MappingStatus.AMBIGUOUS
    assert candidate.promotion_reason == "ambiguous_context"
