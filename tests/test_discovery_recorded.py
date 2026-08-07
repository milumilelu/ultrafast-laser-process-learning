"""O2: RecordedDiscoveryBackend + run_discovery skeleton binding.

Contract: OPEN_SCIENTIFIC_DISCOVERY_V0_1 §11 (recorded backend) / §4 (binding).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_discovery_windows import make_doc
from ultrafast_ingestion.discovery.backend import RecordedDiscoveryBackend
from ultrafast_ingestion.discovery.discoverer import (
    DiscoveryBatchBuilder,
    run_discovery,
)
from ultrafast_ingestion.discovery.models import CandidateKind, DiscoveryWindowConfig

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SAMPLE = FIXTURES / "recorded_discovery_sample.jsonl"


def _doc():
    return make_doc()


def _skeleton(local_id: str, ref: str, label: str = "sample quantity") -> dict:
    return {
        "local_id": local_id,
        "candidate_kind": "QUANTITY",
        "concept_label": label,
        "verbatim_quote": "A repetition rate of 200 kHz was used for all writing experiments.",
        "window_local_ref": ref,
    }


def test_recorded_replay_end_to_end() -> None:
    doc = _doc()
    found = run_discovery(doc, RecordedDiscoveryBackend(SAMPLE))
    assert len(found) == 3
    by_label = {d.skeleton.concept_label: d for d in found}
    assert by_label["pulse repetition rate"].skeleton.candidate_kind == CandidateKind.QUANTITY
    assert by_label["pulse repetition rate"].skeleton.verbatim_quote == (
        "A repetition rate of 200 kHz was used for all writing experiments."
    )
    assert by_label["scan speed effect on heat-affected zone"].skeleton.candidate_kind == (
        CandidateKind.PARAMETER_EFFECT
    )
    # window binding resolves to real window ids
    window_ids = {w.window_id for w in DiscoveryWindowBuilderProxy().build(doc)}
    for d in found:
        assert d.window_id in window_ids
        assert d.paper_id == doc.paper_id
    # w1/w2/w3 refer to methods/results/caption windows in batch order
    refs = DiscoveryBatchBuilder().build(doc)[0].window_refs
    assert len(refs) == 5


def test_unknown_window_local_ref_rejected(tmp_path: Path) -> None:
    record = tmp_path / "badref.jsonl"
    record.write_text(
        json.dumps({"type": "discovery", "skeletons": [_skeleton("s0", "w9")]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown window_local_ref"):
        run_discovery(_doc(), RecordedDiscoveryBackend(record))


def test_recorded_exhaustion_raises() -> None:
    doc = _doc()
    backend = RecordedDiscoveryBackend(SAMPLE)
    run_discovery(doc, backend)
    with pytest.raises(ValueError, match="exhausted"):
        backend.discover(DiscoveryBatchBuilder().build(doc)[0])


def test_recorded_wrong_row_type_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type": "glean", "skeletons": []}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="expected 'discovery'"):
        run_discovery(_doc(), RecordedDiscoveryBackend(bad))


def test_multi_batch_replay_in_order(tmp_path: Path) -> None:
    doc = _doc()
    config = DiscoveryWindowConfig(target_batch_tokens=10)
    batches = DiscoveryBatchBuilder(config=config).build(doc)
    assert len(batches) > 1
    record = tmp_path / "multi.jsonl"
    lines = [
        {
            "type": "discovery",
            "skeletons": [
                _skeleton(f"b{i}-s0", batches[i].window_refs[0], f"batch {i} quantity")
            ],
        }
        for i in range(len(batches))
    ]
    record.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines), encoding="utf-8")
    found = run_discovery(doc, RecordedDiscoveryBackend(record), config=config)
    assert len(found) == len(batches)
    assert [d.skeleton.local_id for d in found] == [f"b{i}-s0" for i in range(len(batches))]
    assert [d.batch_id for d in found] == [b.batch_id for b in batches]
    assert [d.window_id for d in found] == [b.window_ids[0] for b in batches]


def test_empty_result_allowed(tmp_path: Path) -> None:
    record = tmp_path / "empty.jsonl"
    record.write_text('{"type": "discovery", "skeletons": []}\n', encoding="utf-8")
    assert run_discovery(_doc(), RecordedDiscoveryBackend(record)) == []


class DiscoveryWindowBuilderProxy:
    def build(self, doc):
        from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder

        return DiscoveryWindowBuilder().build(doc)
