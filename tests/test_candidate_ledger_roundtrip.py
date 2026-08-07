"""Ledger aggregate roundtrip + artifact persistence (CANDIDATE_LEDGER_V0_1.md §2.4)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import DOC_BLOCK_TEXT, make_doc, make_mention, make_region
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import (
    SCHEMA_VERSION,
    CandidateLedger,
)


def _ledger(version_id: str = "dv_test_0000000000000000"):
    doc = make_doc(version_id=version_id)
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
    return build_ledger(doc, [mention], [make_region(block)])


def test_ledger_version_id_deterministic_and_bound() -> None:
    first, second = _ledger(), _ledger()
    assert first.ledger_version_id == second.ledger_version_id
    assert first.schema_version == SCHEMA_VERSION
    # bound to document version: different doc version -> different ledger id
    other = _ledger(version_id="dv_test_1111111111111111")
    assert other.ledger_version_id != first.ledger_version_id


def test_ledger_canonical_roundtrip() -> None:
    ledger = _ledger()
    restored = CandidateLedger.from_canonical_dict(ledger.to_canonical_dict())
    assert restored == ledger
    assert len(restored.candidates) == len(ledger.candidates)
    assert len(restored.mappings) == len(ledger.mappings)


def test_write_artifact_and_reload(tmp_path: Path) -> None:
    ledger = _ledger()
    path = ledger.write_artifact(tmp_path)
    assert path.exists()
    assert path.name == f"{ledger.ledger_version_id}.json"
    assert path.parent.name == ledger.paper_id
    reloaded = CandidateLedger.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert reloaded == ledger


def test_metrics_counts_consistent() -> None:
    ledger = _ledger()
    candidates = ledger.candidates
    assert ledger.metrics["candidate_count"] == len(candidates)
    source_sum = sum(
        v for k, v in ledger.metrics.items() if k.startswith("source_type_")
    )
    assert source_sum == len(candidates)
    mapping_sum = sum(
        v for k, v in ledger.metrics.items() if k.startswith("mapping_status_")
    )
    assert mapping_sum == len(ledger.mappings)
    # every mapping references an existing candidate
    ids = {c.candidate_id for c in candidates}
    assert all(m.candidate_id in ids for m in ledger.mappings)
