"""Compile reviewed evidence claims into an EvidenceBundle without inventing statistical priors."""

from __future__ import annotations

from typing import Any

from ultrafast_e2p.application.applicability import assess_applicability
from ultrafast_e2p.domain.evidence import EvidenceBundle, EvidenceClaim


def compile_evidence(
    task: dict[str, Any],
    candidates: list[EvidenceClaim],
) -> EvidenceBundle:
    bundle = EvidenceBundle(candidates=list(candidates))
    for claim in candidates:
        applicability = assess_applicability(task, claim)
        bundle.applicability_results.append(applicability.as_dict())
        if claim.review_status != "approved":
            bundle.rejected.append(
                {"claim_id": claim.claim_id, "reason": f"review_status_{claim.review_status}"}
            )
        elif applicability.transfer_class == "none":
            bundle.rejected.append(
                {"claim_id": claim.claim_id, "reason": "scope_incompatible"}
            )
        else:
            bundle.accepted.append(claim)
    return bundle
