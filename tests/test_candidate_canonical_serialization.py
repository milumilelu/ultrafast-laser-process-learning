"""Canonical serialization (CANDIDATE_LEDGER_V0_1.md §0.6, I7)."""

from __future__ import annotations

import json

from tests.conftest import DOC_BLOCK_TEXT, make_doc, make_mention, make_region
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import (
    CandidateLedger,
    ScientificCandidate,
)
from ultrafast_ingestion.mentions.models import MentionValueType


def _ledger():
    doc = make_doc()
    block = doc.pages[0][0]
    mention = make_mention(
        doc,
        block=block,
        parameter="frequency",
        values=[200.0],
        raw_text="200 kHz",
        start=DOC_BLOCK_TEXT.index("200 kHz"),
        end=DOC_BLOCK_TEXT.index("200 kHz") + 7,
        value_type=MentionValueType.SCALAR,
    )
    return build_ledger(doc, [mention], [make_region(block)])


def test_canonical_dict_is_json_serializable() -> None:
    ledger = _ledger()
    payload = json.dumps(ledger.to_canonical_dict(), sort_keys=True)
    assert isinstance(payload, str)
    # deterministic: identical bytes across calls
    assert payload == json.dumps(ledger.to_canonical_dict(), sort_keys=True)


def test_candidate_roundtrip_equality() -> None:
    candidate = _ledger().candidates[0]
    restored = ScientificCandidate.from_canonical_dict(candidate.to_canonical_dict())
    assert restored == candidate
    assert restored.provenance_anchors[0].quote_fingerprint == candidate.provenance_anchors[0].quote_fingerprint


def test_ledger_roundtrip_equality() -> None:
    ledger = _ledger()
    restored = CandidateLedger.from_canonical_dict(ledger.to_canonical_dict())
    assert restored == ledger
    assert restored.ledger_version_id == ledger.ledger_version_id
    assert restored.mappings == ledger.mappings


def test_canonical_dict_has_no_python_types() -> None:
    """model_dump(mode='json') must not leak tuples/bytes/enums."""
    payload = json.loads(json.dumps(_ledger().to_canonical_dict()))
    anchor = payload["candidates"][0]["provenance_anchors"][0]
    assert isinstance(anchor["bbox"], list)
    assert isinstance(payload["candidates"][0]["candidate_kind"], str)
