"""O4: Candidate Fill + ScientificCandidate adapter + ledger ingestion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_discovery_windows import make_doc as make_multi_doc
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import (
    CandidateSourceType,
    MappingStatus,
    PromotionStatus,
    VerificationStatus,
)
from ultrafast_ingestion.discovery.backend import RecordedDiscoveryBackend
from ultrafast_ingestion.discovery.filler import (
    CandidateFiller,
    GateFailError,
    scientific_candidate_from,
)
from ultrafast_ingestion.discovery.grounder import CandidateGrounder
from ultrafast_ingestion.discovery.models import (
    CandidateKind,
    CandidateSkeleton,
    GroundingMatchType,
)
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder

pytestmark = pytest.mark.unit


def _grounded_skeleton(doc, quote: str, local_id: str = "s0"):
    windows = DiscoveryWindowBuilder().build(doc)
    window = next(w for w in windows if quote in w.text)
    skeleton = CandidateSkeleton(
        local_id=local_id,
        candidate_kind=CandidateKind.PARAMETER_EFFECT,
        concept_label="scan speed effect on heat-affected zone",
        verbatim_quote=quote,
        window_local_ref="w0",
    )
    result = CandidateGrounder().ground(doc, window, skeleton)
    assert result.match_type in (
        GroundingMatchType.EXACT,
        GroundingMatchType.NORMALIZED_EXACT,
    )
    return window, skeleton, result


def _discovered(doc, window, skeleton):
    from ultrafast_ingestion.discovery.discoverer import DiscoveredSkeleton

    return DiscoveredSkeleton(
        skeleton=skeleton,
        paper_id=doc.paper_id,
        document_version_id=doc.document_version_id,
        window_id=window.window_id,
        batch_id="batch-test",
    )


def test_fill_replay_and_adapter_end_to_end(tmp_path: Path) -> None:
    doc = make_multi_doc()
    quote = "Scanning velocity strongly affected the heat-affected zone width."
    window, skeleton, result = _grounded_skeleton(doc, quote)
    discovered = _discovered(doc, window, skeleton)

    record = tmp_path / "fill.jsonl"
    record.write_text(
        json.dumps(
            {
                "type": "fill",
                "detail": {
                    "subject_surface": "scanning velocity",
                    "predicate_surface": "affected",
                    "object_surface": "heat-affected zone width",
                    "raw_value": None,
                    "raw_unit": None,
                    "qualifier": "strongly",
                    "scope_hint": None,
                    "source_semantics": "REPORTED",
                },
            }
        ),
        encoding="utf-8",
    )
    filler = CandidateFiller(RecordedDiscoveryBackend(record))
    detail = filler.fill(doc, window, discovered, result)
    assert detail is not None
    assert detail.subject_surface == "scanning velocity"
    assert detail.source_semantics.value == "REPORTED"

    candidate = scientific_candidate_from(doc, discovered, result, detail)
    assert candidate.source_type == CandidateSourceType.LLM_DISCOVERY
    assert candidate.candidate_kind == CandidateKind.PARAMETER_EFFECT
    assert candidate.concept_label == "scan speed effect on heat-affected zone"
    assert candidate.raw_statement == quote
    assert candidate.raw_value is None
    assert candidate.raw_unit is None
    assert candidate.grounding_status.value == "GROUNDED"
    assert candidate.verification_status == VerificationStatus.NOT_RUN
    assert candidate.promotion_status == PromotionStatus.NOT_PROMOTED
    assert candidate.provenance_anchors and candidate.provenance_anchors[0].block_id
    assert candidate.source_detail["grounding_mode"] == "EXACT"
    assert candidate.source_detail["fill"]["subject_surface"] == "scanning velocity"


def test_gate_fail_never_constructed() -> None:
    doc = make_multi_doc()
    windows = DiscoveryWindowBuilder().build(doc)
    skeleton = CandidateSkeleton(
        local_id="s1",
        candidate_kind=CandidateKind.QUANTITY,
        concept_label="hallucinated",
        verbatim_quote="laser power was 50 W",
        window_local_ref="w0",
    )
    result = CandidateGrounder().ground(doc, windows[0], skeleton)
    assert result.gate() == "FAIL"
    discovered = _discovered(doc, windows[0], skeleton)
    with pytest.raises(GateFailError):
        scientific_candidate_from(doc, discovered, result)


def test_fuzzy_conditional_allowed_with_permanent_match_type(tmp_path: Path) -> None:
    doc = make_multi_doc()
    quote = "Scanning velocity strongly affected the heat-affected zone width."
    window, skeleton, _ = _grounded_skeleton(doc, quote)
    altered = "Scanning velocity strongly affects the heat-affected zone width."
    skeleton2 = skeleton.model_copy(update={"local_id": "s2", "verbatim_quote": altered})
    result = CandidateGrounder().ground(doc, window, skeleton2)
    assert result.match_type == GroundingMatchType.FUZZY_UNIQUE
    assert result.gate() == "CONDITIONAL"
    candidate = scientific_candidate_from(doc, _discovered(doc, window, skeleton2), result)
    assert candidate.source_detail["grounding_mode"] == "FUZZY_UNIQUE"
    assert candidate.verification_status == VerificationStatus.NOT_RUN


def test_candidate_id_deterministic_and_bound_to_span() -> None:
    doc = make_multi_doc()
    quote = "Scanning velocity strongly affected the heat-affected zone width."
    window, skeleton, result = _grounded_skeleton(doc, quote)
    discovered = _discovered(doc, window, skeleton)
    first = scientific_candidate_from(doc, discovered, result)
    second = scientific_candidate_from(doc, discovered, result)
    assert first.candidate_id == second.candidate_id
    # different verbatim content -> different id (even if it only grounds fuzzy)
    other = skeleton.model_copy(update={"local_id": "s3", "verbatim_quote": quote + "."})
    result2 = CandidateGrounder().ground(doc, window, other)
    assert result2.gate() == "CONDITIONAL"
    candidate2 = scientific_candidate_from(doc, _discovered(doc, window, other), result2)
    assert candidate2.candidate_id != first.candidate_id


def test_ledger_ingestion_of_discovered_candidates() -> None:
    doc = make_multi_doc()
    quote = "Scanning velocity strongly affected the heat-affected zone width."
    window, skeleton, result = _grounded_skeleton(doc, quote)
    candidate = scientific_candidate_from(doc, _discovered(doc, window, skeleton), result)

    ledger = build_ledger(doc, [], [], discovered_candidates=[candidate])
    assert ledger.metrics["discovered_count"] == 1
    assert ledger.metrics["candidate_count"] == 1
    llm_candidates = [
        c for c in ledger.candidates if c.source_type == CandidateSourceType.LLM_DISCOVERY
    ]
    assert len(llm_candidates) == 1
    assert llm_candidates[0].candidate_id == candidate.candidate_id
    # placeholder mapping keeps 1:1
    mapping = [m for m in ledger.mappings if m.candidate_id == candidate.candidate_id]
    assert len(mapping) == 1
    assert mapping[0].status == MappingStatus.UNMAPPED
    # metrics reflect source type
    assert ledger.metrics["source_type_LLM_DISCOVERY"] == 1
    # canonical roundtrip keeps the discovered candidate
    restored = type(ledger).model_validate(ledger.to_canonical_dict())
    assert restored == ledger


def test_ledger_merge_deterministic_and_discovered_together() -> None:
    doc = make_multi_doc()
    from ultrafast_ingestion.mentions.extractor import extract_mentions

    mentions = extract_mentions(doc)
    quote = "Scanning velocity strongly affected the heat-affected zone width."
    window, skeleton, result = _grounded_skeleton(doc, quote)
    candidate = scientific_candidate_from(doc, _discovered(doc, window, skeleton), result)
    ledger = build_ledger(doc, mentions, [], discovered_candidates=[candidate])
    ids = [c.candidate_id for c in ledger.candidates]
    assert len(ids) == len(set(ids))
    assert ledger.metrics["mention_count"] == len(mentions)
    assert ledger.metrics["discovered_count"] == 1
