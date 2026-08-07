"""Independent candidate verification (O6) - contract §8.

The verifier NEVER sees the proposer's reasoning - only the source context
and the candidate structure. Three-state output (no confidence floats).

Cost tiers (frozen):
  Tier 0  deterministic-confirmed (anchor overlaps a deterministic mention)
          -> no LLM verification (status stays NOT_RUN)
  Tier 1  simple open candidates (exact grounding) -> one verifier call
  Tier 2  PARAMETER_EFFECT / MECHANISM / COMPARISON / multi-value /
          cross-block / FUZZY_UNIQUE -> mandatory verifier call
  Tier 3  AMBIGUOUS grounding / conflict -> default INSUFFICIENT
          (V0.1: such candidates never pass the grounding gate anyway)
"""

from __future__ import annotations

from ultrafast_ingestion.candidates.models import (
    CandidateKind,
    VerificationStatus,
)
from ultrafast_ingestion.discovery.backend import DiscoveryBackend
from ultrafast_ingestion.discovery.models import (
    CandidateVerification,
    GroundingMatchType,
)
from ultrafast_ingestion.models.document import ScientificDocument

VERIFIER_NAME = "verifier-llm-v0.1"
VERIFIER_VERSION = "v0.1"

_TIER2_KINDS = frozenset(
    {
        CandidateKind.PARAMETER_EFFECT,
        CandidateKind.MECHANISM,
        CandidateKind.COMPARISON,
    }
)


def tier_for(candidate) -> int:
    """Cost tier per contract §8."""
    grounding_mode = candidate.source_detail.get("grounding_mode")
    if grounding_mode == GroundingMatchType.FUZZY_UNIQUE.value:
        return 2
    if candidate.candidate_kind in _TIER2_KINDS:
        return 2
    if candidate.source_detail.get("discovery_methods") and any(
        m != "llm-discovery" for m in candidate.source_detail["discovery_methods"]
    ):
        return 0
    if candidate.source_detail.get("fill", {}).get("raw_value"):
        return 2  # multi-value text needs extra scrutiny
    return 1


def _context(document: ScientificDocument, candidate) -> str:
    parts = [
        f"[candidate]\nkind: {candidate.candidate_kind.value}",
        f"label: {candidate.concept_label}",
        f"quote: {candidate.raw_statement}",
    ]
    if candidate.source_detail.get("fill"):
        fill = candidate.source_detail["fill"]
        parts.append(
            f"claimed scope: {fill.get('scope_hint') or 'unspecified'}"
        )
    if candidate.provenance_anchors:
        block = document.blocks_by_id.get(candidate.provenance_anchors[0].block_id)
        if block is not None:
            parts.append(f"[source context]\n{block.text}")
    return "\n".join(parts)


class CandidateVerifier:
    """Tier-aware independent verifier."""

    def __init__(self, backend: DiscoveryBackend) -> None:
        self.backend = backend

    def verify(
        self,
        document: ScientificDocument,
        candidate,
    ) -> CandidateVerification:
        """Verify one candidate; returns the verification record.

        Tier 0 is skipped by construction (verification stays NOT_RUN).
        Tier 3 would default to INSUFFICIENT without an LLM call; in V0.1
        such candidates never reach here (grounding gate).
        """
        tier = tier_for(candidate)
        if tier == 0:
            return CandidateVerification(
                candidate_id=candidate.candidate_id,
                verification_status=VerificationStatus.NOT_RUN,
                verifier="deterministic-tier0",
                verification_version=VERIFIER_VERSION,
                supporting_provenance=list(candidate.provenance_anchors),
                basis="deterministic-confirmed span; LLM verification not required",
            )
        status, basis = self.backend.verify(candidate, _context(document, candidate))
        return CandidateVerification(
            candidate_id=candidate.candidate_id,
            verification_status=status,
            verifier=VERIFIER_NAME,
            verification_version=VERIFIER_VERSION,
            supporting_provenance=list(candidate.provenance_anchors),
            basis=basis,
        )


def apply_verification(candidate, verification: CandidateVerification):
    """Return a copy of the candidate with verification_status updated."""
    return candidate.model_copy(
        update={
            "verification_status": verification.verification_status,
            "source_detail": {
                **candidate.source_detail,
                "verification": verification.to_canonical_dict(),
            },
        }
    )
