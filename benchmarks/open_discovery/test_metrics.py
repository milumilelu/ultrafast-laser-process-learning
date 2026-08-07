"""O9 benchmark harness smoke test (no gold corpus required)."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.open_discovery.metrics import GoldCandidate, compute_metrics


def _fake_candidate(cid: str, block: str = "b1", start: int = 0, end: int = 5):
    from ultrafast_ingestion.candidates.models import (
        CandidateKind,
        CandidateSourceType,
        ScientificCandidate,
    )
    from ultrafast_ingestion.models.provenance import ProvenanceAnchor

    return ScientificCandidate(
        candidate_id=cid,
        paper_id="p1",
        document_version_id="d1",
        candidate_kind=CandidateKind.QUANTITY,
        concept_label="x",
        raw_statement="200 kHz",
        source_type=CandidateSourceType.LLM_DISCOVERY,
        source_ref="",
        source_locator=f"{block}:{start}:{end}",
        provenance_anchors=[
            ProvenanceAnchor(
                paper_id="p1",
                document_version_id="d1",
                pdf_page_index=0,
                block_id=block,
                char_start=start,
                char_end=end,
            )
        ],
    )


def test_incremental_recall_and_unsupported(tmp_path: Path) -> None:
    gold = [
        GoldCandidate(
            paper_id="p1",
            candidate_kind="QUANTITY",
            concept_label="frequency",
            verbatim_quote="200 kHz",
            block_id="b1",
            char_start=0,
            char_end=7,
        )
    ]
    # deterministic path found nothing; hybrid found the gold span
    det = [_fake_candidate("det1", "b9", 0, 5)]
    hyb = [_fake_candidate("det1", "b9", 0, 5), _fake_candidate("llm1", "b1", 0, 7)]
    unsupported = [_fake_candidate("llm2", "b2", 0, 5)]  # grounding FAIL
    metrics = compute_metrics(gold, det, hyb, unsupported)
    assert metrics["deterministic_recall"] == 0.0
    assert metrics["hybrid_recall"] == 1.0
    assert metrics["incremental_open_recall"] == 1.0
    assert metrics["unsupported_candidate_rate"] == 1 / 3


def test_gold_loading_roundtrip(tmp_path: Path) -> None:
    from benchmarks.open_discovery.run_ablation import load_gold

    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "paper_id": "p1",
                "candidate_kind": "QUANTITY",
                "concept_label": "freq",
                "verbatim_quote": "200 kHz",
                "block_id": "b1",
                "char_start": 0,
                "char_end": 7,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gold = load_gold(gold_path)
    assert len(gold) == 1
    assert gold[0].block_id == "b1"
    assert gold[0].char_start == 0
