"""O5: Gleaning pass + anchor-based dedupe (contract §7/§9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_discovery_windows import make_doc as make_multi_doc
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import CandidateSourceType
from ultrafast_ingestion.discovery.backend import RecordedDiscoveryBackend
from ultrafast_ingestion.discovery.discoverer import DiscoveryBatchBuilder
from ultrafast_ingestion.discovery.filler import scientific_candidate_from
from ultrafast_ingestion.discovery.gleaner import glean_over_document, run_glean
from ultrafast_ingestion.discovery.grounder import CandidateGrounder
from ultrafast_ingestion.discovery.merge import merge_into_ledger
from ultrafast_ingestion.discovery.models import (
    CandidateKind,
    CandidateSkeleton,
)
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder
from ultrafast_ingestion.mentions.extractor import extract_mentions

pytestmark = pytest.mark.unit

QUOTE = "Scanning velocity strongly affected the heat-affected zone width."


def _skeleton(local_id: str, quote: str, kind: CandidateKind = CandidateKind.PARAMETER_EFFECT) -> dict:
    return {
        "local_id": local_id,
        "candidate_kind": kind.value,
        "concept_label": "scan speed effect on heat-affected zone",
        "verbatim_quote": quote,
        "window_local_ref": "w1",
    }


def _grounded(doc, window, skeleton):
    from ultrafast_ingestion.discovery.discoverer import DiscoveredSkeleton

    result = CandidateGrounder().ground(doc, window, skeleton)
    if result.gate() == "FAIL":
        return None, None
    discovered = DiscoveredSkeleton(
        skeleton=skeleton,
        paper_id=doc.paper_id,
        document_version_id=doc.document_version_id,
        window_id=window.window_id,
        batch_id="glean-test",
    )
    return discovered, result


def _results_window(doc):
    windows = DiscoveryWindowBuilder().build(doc)
    return next(w for w in windows if QUOTE in w.text)


def test_glean_replay_binds_and_grounds(tmp_path: Path) -> None:
    doc = make_multi_doc()
    batch = DiscoveryBatchBuilder().build(doc)[0]
    window = _results_window(doc)
    record = tmp_path / "glean.jsonl"
    record.write_text(
        json.dumps(
            {
                "type": "glean",
                "skeletons": [
                    {
                        "local_id": "g0",
                        "candidate_kind": "MECHANISM",
                        "concept_label": "fluence-induced graphitization",
                        "verbatim_quote": QUOTE,
                        "window_local_ref": "w2",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    backend = RecordedDiscoveryBackend(record)
    gleaned = run_glean(doc, batch, backend, existing=[])
    assert len(gleaned) == 1
    assert gleaned[0].skeleton.local_id == "g0"
    assert gleaned[0].skeleton.candidate_kind == CandidateKind.MECHANISM
    # glean skeleton goes through the same grounding path (no backdoor)
    result = CandidateGrounder().ground(doc, window, gleaned[0].skeleton)
    assert result.gate() != "FAIL"


def test_glean_unknown_ref_rejected(tmp_path: Path) -> None:
    doc = make_multi_doc()
    batch = DiscoveryBatchBuilder().build(doc)[0]
    record = tmp_path / "bad.jsonl"
    # w9 does not exist in a 5-window batch (w0..w4)
    record.write_text(
        json.dumps(
            {
                "type": "glean",
                "skeletons": [
                    {
                        "local_id": "g0",
                        "candidate_kind": "QUANTITY",
                        "concept_label": "x",
                        "verbatim_quote": "A repetition rate of 200 kHz was used for all writing experiments.",
                        "window_local_ref": "w9",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown window_local_ref"):
        run_glean(doc, batch, RecordedDiscoveryBackend(record), existing=[])


def test_glean_over_document_pass1_then_pass3(tmp_path: Path) -> None:
    doc = make_multi_doc()
    record = tmp_path / "both.jsonl"
    record.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "discovery",
                        "skeletons": [_skeleton("s0", QUOTE, CandidateKind.PARAMETER_EFFECT)],
                    }
                ),
                json.dumps(
                    {
                        "type": "glean",
                        "skeletons": [
                            _skeleton("g0", "A repetition rate of 200 kHz was used for all writing experiments.", CandidateKind.QUANTITY)
                        ],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    gleaned = glean_over_document(doc, RecordedDiscoveryBackend(record))
    assert [d.skeleton.local_id for d in gleaned] == ["g0"]


def test_merge_same_span_same_kind_combines_methods() -> None:
    """Deterministic mention and LLM candidate share the exact anchored span
    (use the mention's own raw_text so EXACT grounding lands on the same
    block+offsets)."""
    from tests.conftest import make_doc as make_single_doc

    doc = make_single_doc()
    mentions = extract_mentions(doc)
    freq = next(m for m in mentions if m.parameter == "frequency")
    window = DiscoveryWindowBuilder().build(doc)[0]
    skeleton = CandidateSkeleton(
        local_id="s0",
        candidate_kind=CandidateKind.QUANTITY,
        concept_label="frequency",
        verbatim_quote=freq.raw_text,
        window_local_ref="w0",
    )
    discovered, result = _grounded(doc, window, skeleton)
    assert discovered is not None and result is not None
    assert result.match_type.value == "EXACT"
    llm_candidate = scientific_candidate_from(doc, discovered, result)

    ledger = build_ledger(doc, mentions, [])
    merged = merge_into_ledger(ledger, [llm_candidate])
    assert merged.metrics.get("merged_discovered_count") == 1
    assert merged.metrics["candidate_count"] == ledger.metrics["candidate_count"]
    # identity preserved; discovery_methods list now carries both sources
    hit = next(
        c for c in merged.candidates
        if c.source_detail.get("discovery_methods") is not None
    )
    assert set(hit.source_detail["discovery_methods"]) == {
        "condition-mention-extractor",
        "llm-discovery",
    }


def test_merge_disjoint_span_appends() -> None:
    doc = make_multi_doc()
    window = _results_window(doc)
    # a quote that shares no span with any deterministic mention
    from ultrafast_ingestion.models.provenance import stable_hash

    template = doc.pages[0][0]
    new_block = type(template)(
        paper_id=template.paper_id,
        document_version_id=template.document_version_id,
        page_index=4,
        bbox=template.bbox,
        block_index=700,
        reading_order=700,
        text="Redeposition appeared when the overlap exceeded 90 percent.",
        section_path="1/results/1",
        section_id=stable_hash(template.document_version_id, "z"),
    )
    doc.pages[0].append(new_block)
    doc.blocks_by_id[new_block.block_id()] = new_block
    windows = DiscoveryWindowBuilder().build(doc)
    window = next(w for w in windows if new_block.block_id() in w.block_ids)
    skeleton = CandidateSkeleton(
        local_id="s1",
        candidate_kind=CandidateKind.OUTCOME,
        concept_label="redeposition onset",
        verbatim_quote="Redeposition appeared when the overlap exceeded 90 percent.",
        window_local_ref="w0",
    )
    discovered, result = _grounded(doc, window, skeleton)
    assert discovered is not None and result is not None
    candidate = scientific_candidate_from(doc, discovered, result)

    ledger = build_ledger(doc, [], [])
    merged = merge_into_ledger(ledger, [candidate])
    assert merged.metrics["candidate_count"] == 1
    assert merged.metrics.get("merged_discovered_count", 0) == 0
    assert merged.candidates[0].candidate_id == candidate.candidate_id
    mapping = [m for m in merged.mappings if m.candidate_id == candidate.candidate_id]
    assert mapping and mapping[0].status.value == "UNMAPPED"


def test_cross_span_similar_never_collapses() -> None:
    """D8: two distinct spans with semantically similar content stay separate
    candidates (no auto-collapse, no relation field on candidates)."""
    doc = make_multi_doc()
    template = doc.pages[0][0]
    texts = (
        "The laser repetition rate was 200 kHz in the first regime.",
        "The system also operated at 200 kHz for marking experiments.",
    )
    blocks = []
    for i, text in enumerate(texts):
        block = type(template)(
            paper_id=template.paper_id,
            document_version_id=template.document_version_id,
            page_index=5 + i,
            bbox=template.bbox,
            block_index=900 + i,
            reading_order=900 + i,
            text=text,
            section_path="1/methods/1",
            section_id=template.section_id,
        )
        doc.pages[0].append(block)
        doc.blocks_by_id[block.block_id()] = block
        blocks.append(block)
    windows = DiscoveryWindowBuilder().build(doc)
    candidates = []
    for i, block in enumerate(blocks):
        window = next(w for w in windows if block.block_id() in w.block_ids)
        skeleton = CandidateSkeleton(
            local_id=f"s{i}",
            candidate_kind=CandidateKind.QUANTITY,
            concept_label="repetition rate",
            verbatim_quote=texts[i],
            window_local_ref="w0",
        )
        discovered, result = _grounded(doc, window, skeleton)
        assert discovered is not None and result is not None
        candidates.append(scientific_candidate_from(doc, discovered, result))
    merged = merge_into_ledger(build_ledger(doc, [], []), candidates)
    llm = [c for c in merged.candidates if c.source_type == CandidateSourceType.LLM_DISCOVERY]
    assert len(llm) == 2, "cross-span candidates must both be retained (D8)"
    assert merged.metrics["candidate_count"] == 2
