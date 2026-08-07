"""REJECTED_CONTEXT preservation (CANDIDATE_LEDGER_V0_1.md §1.4/§2.3, I2)."""

from __future__ import annotations

from tests.conftest import DOC_BLOCK_TEXT, make_doc, make_mention
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import MappingStatus, PromotionStatus
from ultrafast_ingestion.mentions.models import AcceptanceStatus, ContextClass


def _rejected_mention(context: ContextClass, reason: str, raw: str):
    doc = make_doc()
    block = doc.pages[0][0]
    start = DOC_BLOCK_TEXT.index("200 kHz")
    mention = make_mention(
        doc,
        block=block,
        parameter="wavelength",
        values=[1132.0],
        raw_text=raw,
        start=start,
        end=start + len(raw),
        unit="nm",
        status=AcceptanceStatus.REJECTED_CONTEXT,
        context=context,
        reason=reason,
    )
    return build_ledger(doc, [mention], []), mention


def test_rejected_mention_preserved_exactly_once() -> None:
    ledger, mention = _rejected_mention(ContextClass.EMISSION_WAVELENGTH, "emission/ZPL wavelength", "1132 nm")
    hits = [c for c in ledger.candidates if c.source_ref == mention.mention_id]
    assert len(hits) == 1
    candidate = hits[0]
    assert candidate.source_type.value == "REJECTED_CONDITION_MENTION"
    assert candidate.concept_label == "emission/ZPL wavelength"
    assert candidate.raw_statement == "1132 nm"
    assert candidate.provenance_anchors


def test_rejected_mention_mapping_not_applicable() -> None:
    ledger, mention = _rejected_mention(ContextClass.EMISSION_WAVELENGTH, "emission/ZPL wavelength", "1132 nm")
    candidate = next(c for c in ledger.candidates if c.source_ref == mention.mention_id)
    mapping = [m for m in ledger.mappings if m.candidate_id == candidate.candidate_id]
    assert len(mapping) == 1
    assert mapping[0].status == MappingStatus.NOT_APPLICABLE
    assert mapping[0].target_field is None
    assert mapping[0].target_namespace == "experimental_condition"


def test_rejected_mention_promotion_state() -> None:
    ledger, _ = _rejected_mention(ContextClass.EMISSION_WAVELENGTH, "emission/ZPL wavelength", "1132 nm")
    candidate = ledger.candidates[0]
    assert candidate.promotion_status == PromotionStatus.NOT_PROMOTED
    assert candidate.promotion_reason == "rejected_context"
    assert candidate.source_detail["rejection_reason"] == "emission/ZPL wavelength"
    assert candidate.source_detail["context_class"] == "EMISSION_WAVELENGTH"


def test_equipment_model_rejection_label() -> None:
    ledger, _ = _rejected_mention(ContextClass.EQUIPMENT_MODEL, "equipment model / non-process power", "25 W")
    assert ledger.candidates[0].concept_label == "equipment model specification"
