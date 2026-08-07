"""Topic2 adapter: deterministic Evidence scope applicability rules (delegated to ultrafast_e2p)."""

from __future__ import annotations

from ultrafast_e2p.application.applicability import assess_applicability as _assess

from packages.e2p.application._adapter import (
    evidence_claim_to_e2p,
    task_scope_to_e2p,
)
from packages.process_contracts.schemas import Evidence, TaskScope


def assess_applicability(
    task: TaskScope, evidence: Evidence
) -> dict[str, bool | str | None]:
    report = _assess(task_scope_to_e2p(task), evidence_claim_to_e2p(evidence))
    return {
        "evidence_id": report.claim_id,
        "material_match": report.material_match,
        "laser_type_match": report.laser_type_match,
        "geometry_match": report.geometry_match,
        "equipment_match": report.equipment_match,
        "target_match": report.target_metric_match,
        "transfer_level": report.transfer_class,
    }
