"""O6: Independent verification (tiers, three-state, no confidence floats)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import make_doc as make_single_doc
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import CandidateSourceType, VerificationStatus
from ultrafast_ingestion.discovery.backend import RecordedDiscoveryBackend
from ultrafast_ingestion.discovery.filler import scientific_candidate_from
from ultrafast_ingestion.discovery.grounder import CandidateGrounder
from ultrafast_ingestion.discovery.models import (
    CandidateKind,
    CandidateSkeleton,
)
from ultrafast_ingestion.discovery.verifier import (
    CandidateVerifier,
    apply_verification,
    tier_for,
)
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder
from ultrafast_ingestion.mentions.extractor import extract_mentions

pytestmark = pytest.mark.unit


def _make_candidate(doc, quote: str, kind: CandidateKind = CandidateKind.QUANTITY):
    from ultrafast_ingestion.discovery.discoverer import DiscoveredSkeleton

    window = DiscoveryWindowBuilder().build(doc)[0]
    skeleton = CandidateSkeleton(
        local_id="s0",
        candidate_kind=kind,
        concept_label="test",
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
            batch_id="verify-test",
        ),
        result,
    )


def _recorded(tmp_path: Path, status: str, basis: str = "") -> RecordedDiscoveryBackend:
    record = tmp_path / "verify.jsonl"
    record.write_text(
        json.dumps({"type": "verify", "verification_status": status, "basis": basis}),
        encoding="utf-8",
    )
    return RecordedDiscoveryBackend(record)


def test_tier0_deterministic_confirmed_skips_llm() -> None:
    doc = make_single_doc()
    mentions = extract_mentions(doc)
    freq = next(m for m in mentions if m.parameter == "frequency")
    window = DiscoveryWindowBuilder().build(doc)[0]
    from ultrafast_ingestion.discovery.discoverer import DiscoveredSkeleton

    skeleton = CandidateSkeleton(
        local_id="s0",
        candidate_kind=CandidateKind.QUANTITY,
        concept_label="frequency",
        verbatim_quote=freq.raw_text,
        window_local_ref="w0",
    )
    result = CandidateGrounder().ground(doc, window, skeleton)
    candidate = scientific_candidate_from(
        doc,
        DiscoveredSkeleton(
            skeleton=skeleton,
            paper_id=doc.paper_id,
            document_version_id=doc.document_version_id,
            window_id=window.window_id,
            batch_id="t",
        ),
        result,
    )
    # simulate the merge that records both discovery methods (tier 0 signal)
    candidate = candidate.model_copy(
        update={
            "source_detail": {
                **candidate.source_detail,
                "discovery_methods": ["condition-mention-extractor", "llm-discovery"],
            }
        }
    )
    assert tier_for(candidate) == 0
    backend = _recorded(Path("."), "SUPPORTED")  # must never be consumed
    verification = CandidateVerifier(backend).verify(doc, candidate)
    assert verification.verification_status == VerificationStatus.NOT_RUN
    assert verification.verifier == "deterministic-tier0"


def test_tier2_fuzzy_unique_mandatory_verification(tmp_path: Path) -> None:
    doc = make_single_doc()
    from tests.conftest import DOC_BLOCK_TEXT

    quote = DOC_BLOCK_TEXT
    altered = quote.replace("operated", "operates")
    candidate = _make_candidate(doc, altered)
    assert candidate is not None
    assert candidate.source_detail["grounding_mode"] == "FUZZY_UNIQUE"
    assert tier_for(candidate) == 2
    verification = CandidateVerifier(_recorded(tmp_path, "SUPPORTED", "explicit")).verify(
        doc, candidate
    )
    assert verification.verification_status == VerificationStatus.SUPPORTED
    assert verification.supporting_provenance


def test_tier1_simple_exact_verified_once(tmp_path: Path) -> None:
    doc = make_single_doc()
    from tests.conftest import DOC_BLOCK_TEXT

    candidate = _make_candidate(doc, DOC_BLOCK_TEXT)
    assert candidate is not None
    assert tier_for(candidate) == 1
    verification = CandidateVerifier(_recorded(tmp_path, "SUPPORTED")).verify(doc, candidate)
    assert verification.verification_status == VerificationStatus.SUPPORTED


def test_tier2_parameter_effect_mandatory(tmp_path: Path) -> None:
    doc = make_single_doc()
    from tests.conftest import DOC_BLOCK_TEXT

    candidate = _make_candidate(doc, DOC_BLOCK_TEXT, kind=CandidateKind.PARAMETER_EFFECT)
    assert candidate is not None
    assert tier_for(candidate) == 2


def test_contradicted_propagates_to_candidate(tmp_path: Path) -> None:
    """Paper-13-style regression: a measurement-frequency claim must not end
    up as a processing frequency - CONTRADICTED must propagate."""
    doc = make_single_doc()
    from tests.conftest import DOC_BLOCK_TEXT

    candidate = _make_candidate(doc, DOC_BLOCK_TEXT, kind=CandidateKind.QUANTITY)
    assert candidate is not None
    verification = CandidateVerifier(
        _recorded(tmp_path, "CONTRADICTED", "measurement context, not processing")
    ).verify(doc, candidate)
    updated = apply_verification(candidate, verification)
    assert updated.verification_status == VerificationStatus.CONTRADICTED
    assert updated.source_detail["verification"]["verification_status"] == "CONTRADICTED"
    # a CONTRADICTED candidate is never promoted by consumers that gate on
    # SUPPORTED; promotion gating is O7's concern but the status is the contract
    assert VerificationStatus.CONTRADICTED.value == "CONTRADICTED"


def test_verification_status_survives_ledger_roundtrip(tmp_path: Path) -> None:
    doc = make_single_doc()
    from tests.conftest import DOC_BLOCK_TEXT

    candidate = _make_candidate(doc, DOC_BLOCK_TEXT)
    assert candidate is not None
    verification = CandidateVerifier(_recorded(tmp_path, "INSUFFICIENT")).verify(doc, candidate)
    updated = apply_verification(candidate, verification)
    ledger = build_ledger(doc, [], [], discovered_candidates=[updated])
    restored = type(ledger).model_validate(ledger.to_canonical_dict())
    llm = [
        c for c in restored.candidates if c.source_type == CandidateSourceType.LLM_DISCOVERY
    ]
    assert llm[0].verification_status == VerificationStatus.INSUFFICIENT
