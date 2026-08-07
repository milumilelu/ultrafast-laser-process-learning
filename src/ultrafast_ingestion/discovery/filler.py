"""Candidate Fill (O4) + ScientificCandidate adapter + ledger ingestion.

Contract: OPEN_SCIENTIFIC_DISCOVERY_V0_1 §6 (fill) / §10 (mapping placeholder).

Pipeline: grounded skeleton -> fill context -> CandidateDetail ->
ScientificCandidate (source_type=LLM_DISCOVERY) -> CandidateLedger.
Gate-FAIL skeletons are never constructed (contract §5).
"""

from __future__ import annotations

from ultrafast_ingestion.candidates.models import (
    CandidateSourceType,
    MappingStatus,
    PromotionStatus,
    ScientificCandidate,
    VerificationStatus,
)
from ultrafast_ingestion.discovery.backend import DiscoveryBackend
from ultrafast_ingestion.discovery.discoverer import DiscoveredSkeleton
from ultrafast_ingestion.discovery.models import (
    CandidateDetail,
    DiscoveryWindow,
    GroundingResult,
)
from ultrafast_ingestion.models.document import ScientificDocument
from ultrafast_ingestion.models.provenance import normalize_quote, stable_hash

DISCOVERY_METHOD_LLM = "llm-discovery"
DISCOVERY_VERSION = "v0.1"

# placeholder namespace until O7 routing
NAMESPACE_OPEN_DISCOVERY = "open_discovery"


class GateFailError(ValueError):
    """Raised when constructing a ScientificCandidate from a gate-FAIL grounding."""


class CandidateFiller:
    """Pass 2: enrich grounded skeletons with optional details."""

    def __init__(self, backend: DiscoveryBackend) -> None:
        self.backend = backend

    def fill(
        self,
        document: ScientificDocument,
        window: DiscoveryWindow,
        discovered: DiscoveredSkeleton,
        result: GroundingResult,
    ) -> CandidateDetail | None:
        if result.gate() == "FAIL":
            return None
        context = self._context(document, window, result)
        return self.backend.fill(discovered.skeleton, context)

    def _context(
        self,
        document: ScientificDocument,
        window: DiscoveryWindow,
        result: GroundingResult,
    ) -> str:
        parts = [f"[quote]\n{result.matched_quote}"]
        if result.anchor is not None:
            block = document.blocks_by_id.get(result.anchor.block_id)
            if block is not None:
                parts.append(f"[block]\n{block.text}")
        if window.preceding_context:
            parts.append(f"[preceding context]\n{window.preceding_context}")
        if window.following_context:
            parts.append(f"[following context]\n{window.following_context}")
        if window.caption_refs:
            captions = [
                document.blocks_by_id[c].text
                for c in window.caption_refs
                if c in document.blocks_by_id
            ]
            if captions:
                parts.append("[captions]\n" + "\n\n".join(captions))
        if window.table_refs:
            parts.append(f"[tables]\n{window.text}")
        return "\n\n".join(parts)


def scientific_candidate_from(
    document: ScientificDocument,
    discovered: DiscoveredSkeleton,
    result: GroundingResult,
    detail: CandidateDetail | None = None,
) -> ScientificCandidate:
    """Adapter: grounded skeleton + optional detail -> ScientificCandidate.

    Gate FAIL is a hard error - AMBIGUOUS/UNRESOLVED skeletons are never
    constructed (contract §5); FUZZY_UNIQUE (CONDITIONAL) is allowed but
    carries its permanent match_type and NOT_RUN verification (O6).
    """
    if result.gate() == "FAIL":
        raise GateFailError(
            f"skeleton {discovered.skeleton.local_id} gate={result.gate()} "
            f"match_type={result.match_type.value}"
        )
    skeleton = discovered.skeleton
    anchor = result.anchor
    if anchor is not None:
        locator = f"{anchor.block_id}:{anchor.char_start}:{anchor.char_end}"
    else:
        locator = f"ungrounded:{skeleton.local_id}"
    candidate_id = stable_hash(
        document.document_version_id,
        CandidateSourceType.LLM_DISCOVERY.value,
        locator,
        normalize_quote(skeleton.verbatim_quote),
    )
    source_detail: dict = {
        "window_id": discovered.window_id,
        "batch_id": discovered.batch_id,
        "skeleton_local_id": skeleton.local_id,
        "grounding_mode": result.match_type.value,
        "matched_quote": result.matched_quote,
        "fuzzy_score": result.detail.get("fuzzy_score"),
    }
    if detail is not None:
        source_detail["fill"] = detail.to_canonical_dict()
    return ScientificCandidate(
        candidate_id=candidate_id,
        paper_id=document.paper_id,
        document_version_id=document.document_version_id,
        candidate_kind=skeleton.candidate_kind,
        concept_label=skeleton.concept_label,
        raw_statement=skeleton.verbatim_quote,
        raw_value=detail.raw_value if detail else None,
        raw_unit=detail.raw_unit if detail else None,
        source_type=CandidateSourceType.LLM_DISCOVERY,
        source_ref=skeleton.local_id,
        source_locator=locator,
        source_detail=source_detail,
        provenance_anchors=[anchor] if anchor else [],
        grounding_status=result.status,
        verification_status=VerificationStatus.NOT_RUN,
        promotion_status=PromotionStatus.NOT_PROMOTED,
        promotion_reason="llm_discovery_pending",
        discovery_method=DISCOVERY_METHOD_LLM,
        discovery_version=DISCOVERY_VERSION,
    )


def placeholder_mapping(candidate: ScientificCandidate):
    """UNMAPPED placeholder until O7 routing keeps ledger 1:1 (candidate, mapping)."""
    from ultrafast_ingestion.candidates.models import CandidateMapping

    return CandidateMapping(
        candidate_id=candidate.candidate_id,
        target_namespace=NAMESPACE_OPEN_DISCOVERY,
        target_field=None,
        status=MappingStatus.UNMAPPED,
    )
