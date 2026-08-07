"""Topic2 adapter: EvidenceClaim conversion between the pydantic contract and ultrafast_e2p."""

from __future__ import annotations

from typing import Any

from ultrafast_e2p.domain.evidence import EvidenceClaim

from packages.process_contracts.schemas import Evidence, TaskScope

_SEMANTIC_ROLE_BY_CLAIM_TYPE = {
    "range_preference": "recommended_range",
    "preferred_range": "recommended_range",
    "parameter_direction": "observed_relation",
    "relative_importance": "observed_relation",
    "functional_shape": "observed_relation",
    "historical_dataset": "experimental_condition",
    "historical_model": "experimental_condition",
}


def task_scope_to_e2p(task: TaskScope) -> dict[str, Any]:
    return {
        "material_id": task.material,
        "laser_type": task.laser_type,
        "geometry_type": task.geometry_type,
        "equipment_id": task.equipment_id,
        "target_metric": task.target,
    }


def evidence_claim_to_e2p(item: Evidence) -> EvidenceClaim:
    scope = {
        "material_id": item.scope.material,
        "laser_type": item.scope.laser_type,
        "geometry_type": item.scope.geometry_type,
        "equipment_id": item.scope.equipment_id,
        "target_metric": item.scope.target,
    }
    return EvidenceClaim(
        claim_id=item.evidence_id,
        claim_type=str(item.claim_type),
        parameter=item.parameter,
        target=item.target,
        value=dict(item.claim),
        scope=scope,
        semantic_role=_SEMANTIC_ROLE_BY_CLAIM_TYPE.get(str(item.claim_type), "unspecified"),
        source={
            "source_id": item.provenance.source_id,
            "review_id": item.provenance.review_id,
        },
        review_status=item.review_status,
        version=item.version,
    )
