"""O7/O8: routing (Condition / UNMAPPED) + SchemaGap reporting."""

from __future__ import annotations

import pytest

from tests.conftest import make_doc as make_single_doc
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import MappingStatus, VerificationStatus
from ultrafast_ingestion.discovery.filler import scientific_candidate_from
from ultrafast_ingestion.discovery.grounder import CandidateGrounder
from ultrafast_ingestion.discovery.merge import route_ledger
from ultrafast_ingestion.discovery.models import (
    CandidateKind,
    CandidateSkeleton,
    CandidateVerification,
)
from ultrafast_ingestion.discovery.schema_gap import gap_report, schema_gaps
from ultrafast_ingestion.discovery.verifier import apply_verification
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.mentions.units import parameter_from_label

pytestmark = pytest.mark.unit

QUOTE = "The laser was operated at 1030 nm with a repetition rate of 200 kHz and a pulse width of 300 fs."


def _candidate(doc, label: str, kind: CandidateKind, quote: str):
    from ultrafast_ingestion.discovery.discoverer import DiscoveredSkeleton

    window = DiscoveryWindowBuilder().build(doc)[0]
    skeleton = CandidateSkeleton(
        local_id="s0",
        candidate_kind=kind,
        concept_label=label,
        verbatim_quote=quote,
        window_local_ref="w0",
    )
    result = CandidateGrounder().ground(doc, window, skeleton)
    if result.gate() == "FAIL":
        return None
    return scientific_candidate_from(
        doc,
        DiscoveredSkeleton(
            skeleton=skeleton,
            paper_id=doc.paper_id,
            document_version_id=doc.document_version_id,
            window_id=window.window_id,
            batch_id="route",
        ),
        result,
    )


def test_route_maps_known_quantity_label() -> None:
    doc = make_single_doc()
    candidate = _candidate(doc, "pulse repetition rate", CandidateKind.QUANTITY, QUOTE)
    assert candidate is not None
    assert parameter_from_label(candidate.concept_label) == "frequency"
    ledger = route_ledger(build_ledger(doc, [], [], discovered_candidates=[candidate]))
    mapping = next(m for m in ledger.mappings if m.candidate_id == candidate.candidate_id)
    assert mapping.status == MappingStatus.MAPPED
    assert mapping.target_namespace == "experimental_condition"
    assert mapping.target_field == "frequency"


def test_route_keeps_open_concept_unmapped() -> None:
    doc = make_single_doc()
    candidate = _candidate(
        doc, "intra-burst pulse spacing", CandidateKind.QUANTITY, QUOTE
    )
    assert candidate is not None
    assert parameter_from_label(candidate.concept_label) == "unknown"
    ledger = route_ledger(build_ledger(doc, [], [], discovered_candidates=[candidate]))
    mapping = next(m for m in ledger.mappings if m.candidate_id == candidate.candidate_id)
    assert mapping.status == MappingStatus.UNMAPPED
    # candidate retained - never deleted (D3)
    assert any(c.candidate_id == candidate.candidate_id for c in ledger.candidates)


def test_route_never_touches_deterministic_mappings() -> None:
    doc = make_single_doc()
    mentions = extract_mentions(doc)
    freq = next(m for m in mentions if m.parameter == "frequency")
    candidate = _candidate(doc, "pulse repetition rate", CandidateKind.QUANTITY, freq.raw_text)
    assert candidate is not None
    ledger = build_ledger(doc, mentions, [], discovered_candidates=[candidate])
    before = {m.candidate_id: m for m in ledger.mappings}
    routed = route_ledger(ledger)
    # deterministic mappings are byte-identical (MAPPED/AMBIGUOUS/NOT_APPLICABLE kept)
    for mid, mapping in before.items():
        if mid == candidate.candidate_id:
            continue  # LLM placeholder is updated by routing (asserted below)
        assert mapping == next(m for m in routed.mappings if m.candidate_id == mid)
    # the LLM candidate's placeholder UNMAPPED becomes a real MAPPED routing
    llm_mapping = next(
        m for m in routed.mappings if m.candidate_id == candidate.candidate_id
    )
    assert llm_mapping.status == MappingStatus.MAPPED
    assert llm_mapping.target_field == "frequency"


def test_non_quantity_kind_never_maps_to_condition() -> None:
    doc = make_single_doc()
    candidate = _candidate(
        doc, "scan speed effect on heat-affected zone", CandidateKind.PARAMETER_EFFECT, QUOTE
    )
    assert candidate is not None
    ledger = route_ledger(build_ledger(doc, [], [], discovered_candidates=[candidate]))
    mapping = next(m for m in ledger.mappings if m.candidate_id == candidate.candidate_id)
    assert mapping.status == MappingStatus.UNMAPPED


def test_schema_gap_aggregates_supported_unmapped() -> None:
    doc = make_single_doc()
    candidate = _candidate(
        doc, "intra-burst pulse spacing", CandidateKind.QUANTITY, QUOTE
    )
    assert candidate is not None
    ledger = route_ledger(build_ledger(doc, [], [], discovered_candidates=[candidate]))
    gaps = schema_gaps(ledger)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.concept_label == "intra-burst pulse spacing"
    assert gap.occurrence_count == 1
    assert gap.paper_count == 1
    assert candidate.candidate_id in gap.example_candidate_ids


def test_schema_gap_excludes_contradicted_and_mapped() -> None:
    doc = make_single_doc()
    mapped_candidate = _candidate(doc, "pulse repetition rate", CandidateKind.QUANTITY, QUOTE)
    open_candidate = _candidate(
        doc, "intra-burst pulse spacing", CandidateKind.QUANTITY, QUOTE
    )
    assert mapped_candidate is not None and open_candidate is not None
    contradicted = apply_verification(
        open_candidate,
        CandidateVerification(
            candidate_id=open_candidate.candidate_id,
            verification_status=VerificationStatus.CONTRADICTED,
        ),
    )
    ledger = route_ledger(
        build_ledger(
            doc, [], [], discovered_candidates=[mapped_candidate, contradicted]
        )
    )
    gaps = schema_gaps(ledger)
    assert gaps == []


def test_gap_report_cross_paper() -> None:
    doc = make_single_doc()
    candidates = [
        _candidate(doc, "intra-burst pulse spacing", CandidateKind.QUANTITY, QUOTE),
        _candidate(doc, "intra-burst pulse spacing", CandidateKind.QUANTITY, QUOTE),
    ]
    candidates = [c for c in candidates if c is not None]
    ledger = route_ledger(build_ledger(doc, [], [], discovered_candidates=candidates))
    report = gap_report([ledger])
    assert report[0]["concept"] == "intra-burst pulse spacing"
    assert report[0]["papers"] == 1
    assert report[0]["mentions"] == 2
