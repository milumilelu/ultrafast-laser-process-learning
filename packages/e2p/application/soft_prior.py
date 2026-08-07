"""Topic2 adapter: soft search prior (delegated to ultrafast_e2p).

文献只产生搜索偏好 π_E(x)，机器边界始终是唯一硬约束。
"""

from __future__ import annotations

from typing import Any

from ultrafast_e2p.application.soft_prior import (
    PRIOR_SPEC_VERSION,
    decayed_evidence_weight,
    log_prior_score,
)
from ultrafast_e2p.application.soft_prior import (
    compile_prior_spec as _compile_prior_spec,
)

from packages.e2p.application._adapter import evidence_claim_to_e2p
from packages.e2p.domain.evidence import EvidenceBundle

__all__ = [
    "PRIOR_SPEC_VERSION",
    "compile_prior_spec",
    "decayed_evidence_weight",
    "log_prior_score",
]


def compile_prior_spec(bundle: EvidenceBundle) -> dict[str, Any]:
    """将 Topic2 EvidenceBundle 编译为 PriorSpec；claim_id 映射回 evidence_id。"""
    from ultrafast_e2p.domain.evidence import EvidenceBundle as E2PBundle

    claims = [evidence_claim_to_e2p(item) for item in bundle.accepted]
    e2p_bundle = E2PBundle(
        candidates=claims,
        accepted=claims,
        applicability_results=[
            {
                "claim_id": item["evidence_id"],
                "material_match": item.get("material_match"),
                "laser_type_match": item.get("laser_type_match"),
                "process_type_match": None,
                "geometry_match": item.get("geometry_match"),
                "equipment_match": item.get("equipment_match"),
                "target_metric_match": item.get("target_match"),
                "transfer_class": item.get("transfer_level"),
            }
            for item in bundle.applicability_results
        ],
    )
    spec = _compile_prior_spec(e2p_bundle)
    for preference in spec["range_preferences"]:
        preference["evidence_id"] = preference.pop("claim_id")
    return spec
