"""Compile reviewed evidence without inventing statistical prior parameters.

算法委托 ultrafast_e2p；此处保持 Topic2 契约形状（evidence_id / transfer_level）。
"""

from __future__ import annotations

from ultrafast_e2p.application.evidence_compiler import compile_evidence as _compile

from packages.e2p.application._adapter import (
    evidence_claim_to_e2p,
    task_scope_to_e2p,
)
from packages.e2p.domain.evidence import EvidenceBundle
from packages.process_contracts.schemas import Evidence, TaskScope


def compile_evidence(task: TaskScope, candidates: list[Evidence]) -> EvidenceBundle:
    claims = [evidence_claim_to_e2p(item) for item in candidates]
    compiled = _compile(task_scope_to_e2p(task), claims)
    accepted_ids = {claim.claim_id for claim in compiled.accepted}
    rejected = [
        {"evidence_id": item["claim_id"], "reason": item["reason"]}
        for item in compiled.rejected
    ]
    applicability = []
    for report in compiled.applicability_results:
        applicability.append(
            {
                "evidence_id": report["claim_id"],
                "material_match": report["material_match"],
                "laser_type_match": report["laser_type_match"],
                "geometry_match": report["geometry_match"],
                "equipment_match": report["equipment_match"],
                "target_match": report["target_metric_match"],
                "transfer_level": report["transfer_class"],
            }
        )
    return EvidenceBundle(
        candidates=list(candidates),
        accepted=[item for item in candidates if item.evidence_id in accepted_ids],
        rejected=rejected,
        applicability_results=applicability,
        version=compiled.version,
    )
