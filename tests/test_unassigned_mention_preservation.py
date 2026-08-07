"""Unassigned mention traceability (CANDIDATE_LEDGER_V0_1.md §1.1/§1.3, I4).

Phase B: compiler output is keyed by ledger candidate ids.
"""

from __future__ import annotations

from tests.conftest import DOC_BLOCK_TEXT, make_doc, make_mention
from ultrafast_ingestion.candidates.ledger import build_ledger, candidate_id_for_mention
from ultrafast_ingestion.candidates.models import PromotionStatus
from ultrafast_ingestion.conditions.compiler import CompileResult
from ultrafast_ingestion.conditions.models import ExperimentalConditionSpec
from ultrafast_ingestion.linking.models import ConditionRole, Scope


def _mentions():
    doc = make_doc()
    block = doc.pages[0][0]
    start = DOC_BLOCK_TEXT.index("200 kHz")
    a = make_mention(
        doc,
        block=block,
        parameter="frequency",
        values=[200.0],
        raw_text="200 kHz",
        start=start,
        end=start + 7,
    )
    b = make_mention(
        doc,
        block=block,
        parameter="pulse_width",
        values=[300.0],
        raw_text="300 fs",
        start=DOC_BLOCK_TEXT.index("300 fs"),
        end=DOC_BLOCK_TEXT.index("300 fs") + 6,
        unit="fs",
    )
    return doc, a, b


def test_unassigned_mention_traceable_not_duplicated() -> None:
    doc, a, b = _mentions()
    compiled = CompileResult(
        conditions=[],
        unassigned_mentions=[
            candidate_id_for_mention(doc, a),
            candidate_id_for_mention(doc, b),
        ],
        synthetic_condition_count=0,
        metrics={},
    )
    ledger = build_ledger(doc, [a, b], [], compile_result=compiled)
    assert len(ledger.candidates) == 2
    for mention in (a, b):
        hits = [c for c in ledger.candidates if c.source_ref == mention.mention_id]
        assert len(hits) == 1, "unassigned must never duplicate a mention candidate"
        candidate = hits[0]
        assert candidate.source_type.value == "CONDITION_MENTION"
        assert candidate.promotion_status == PromotionStatus.NOT_PROMOTED
        assert candidate.promotion_reason == "unassigned_after_linking"


def test_promoted_mention_carries_condition_ref() -> None:
    doc, a, b = _mentions()
    condition = ExperimentalConditionSpec(
        condition_id="cond-1",
        paper_id=doc.paper_id,
        role=ConditionRole.PROCESSING,
        scope=Scope.EXPERIMENT_GROUP,
        mention_ids=[candidate_id_for_mention(doc, a)],
        fields={},
    )
    compiled = CompileResult(
        conditions=[condition],
        unassigned_mentions=[candidate_id_for_mention(doc, b)],
        synthetic_condition_count=0,
        metrics={},
    )
    ledger = build_ledger(doc, [a, b], [], compile_result=compiled)
    by_ref = {c.source_ref: c for c in ledger.candidates}
    assert by_ref[a.mention_id].promotion_status == PromotionStatus.PROMOTED
    assert by_ref[a.mention_id].promotion_ref == "cond-1"
    assert by_ref[b.mention_id].promotion_reason == "unassigned_after_linking"


def test_metrics_reflect_unassigned_count() -> None:
    doc, a, b = _mentions()
    compiled = CompileResult(
        conditions=[],
        unassigned_mentions=[candidate_id_for_mention(doc, b)],
        synthetic_condition_count=0,
        metrics={},
    )
    ledger = build_ledger(doc, [a, b], [], compile_result=compiled)
    assert ledger.metrics["unassigned_mention_count"] == 1
    assert ledger.metrics["promotion_status_NOT_PROMOTED"] == 2
    assert ledger.metrics["condition_count"] == 0
