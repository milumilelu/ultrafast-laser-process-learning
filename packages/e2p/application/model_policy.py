"""Topic2 adapter: rule-based E2P model policy (delegated to ultrafast_e2p)."""

from __future__ import annotations

from typing import Any

from ultrafast_e2p.application.model_policy import (
    MODEL_POLICY_VERSION,
)
from ultrafast_e2p.application.model_policy import (
    decide_model_policy as _decide,
)

from packages.e2p.application._adapter import (
    evidence_claim_to_e2p,
    task_scope_to_e2p,
)
from packages.e2p.domain.evidence import EvidenceBundle
from packages.process_contracts.schemas import DataProfile, TaskScope

__all__ = ["MODEL_POLICY_VERSION", "decide_model_policy"]


def decide_model_policy(
    task: TaskScope,
    profile: DataProfile,
    bundle: EvidenceBundle,
    configured_candidates: list[str] | None = None,
) -> dict[str, Any]:
    from ultrafast_e2p.domain.evidence import EvidenceBundle as E2PBundle

    claims = [evidence_claim_to_e2p(item) for item in bundle.accepted]
    e2p_bundle = E2PBundle(
        candidates=claims,
        accepted=claims,
        applicability_results=list(bundle.applicability_results),
    )
    return _decide(
        task_scope_to_e2p(task),
        profile.model_dump(mode="json"),
        e2p_bundle,
        configured_candidates,
    )
