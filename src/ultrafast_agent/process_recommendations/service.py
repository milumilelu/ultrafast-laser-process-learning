from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ultrafast_bo.application.governance import BOEligibilityService
from ultrafast_bo.application.lifecycle import BOModelRegistry
from ultrafast_bo.domain.search_space import CompiledSearchSpace
from ultrafast_domain.process.recommendation import ProcessRecommendation
from ultrafast_integrations.cam import GenericJsonCamAdapter
from ultrafast_integrations.storage.process_recommendation_repository import (
    ProcessRecommendationRepository,
)


class ProcessRecommendationService:
    def __init__(self, repository: ProcessRecommendationRepository | None = None):
        self.repository = repository or ProcessRecommendationRepository()

    def create(
        self, *, task_id: str, workflow_id: str, task_spec: dict[str, Any],
        bo_result: dict[str, Any], search_space: CompiledSearchSpace | dict[str, Any],
        current_recipe: dict[str, Any] | None = None, stage: str = "trial_cut",
        parent_recommendation_id: str | None = None,
        parameter_units: dict[str, str] | None = None,
        parameter_sources: dict[str, str] | None = None,
        recommendation_source: str | None = None,
        source_run_id: str | None = None,
    ) -> ProcessRecommendation:
        space = search_space.to_dict() if isinstance(search_space, CompiledSearchSpace) else dict(search_space)
        optimized = dict(bo_result.get("recommended_parameters") or {})
        fixed = {**dict(current_recipe or {}), **dict(space.get("fixed_parameters") or {})}
        for name in optimized:
            fixed.pop(name, None)
        recipe = {**fixed, **optimized}
        violations = _validate_against_search_space(recipe, space)
        if violations:
            raise ValueError(
                "recommended parameters violate search space bounds: "
                + "; ".join(violations)
            )
        sources, units = dict(parameter_sources or {}), dict(parameter_units or {})
        metadata = {}
        for name, value in recipe.items():
            variable = (space.get("variables") or {}).get(name) or {}
            metadata[name] = {
                "source": sources.get(name) or ("bo_recommendation" if name in optimized else "user_fixed" if name in fixed else "equipment_default"),
                "mode": variable.get("mode") or "fixed", "unit": units.get(name),
                "allowed_range": [variable["lower"], variable["upper"]] if "lower" in variable else None,
                "value": value,
            }
        if space.get("feasibility_status") != "ready" or bo_result.get("status") == "blocked":
            status = "blocked"
        elif not recipe or any(item["unit"] is None for item in metadata.values()) or stage == "production_candidate":
            status = "pending_review"
        else:
            status = "ready_for_cam" if stage in {"production_approved", "trial_cut"} else "ready_for_trial"
        source = recommendation_source or (
            "bo_parameter_recommendation" if optimized else "approved_prior_or_rule"
        )
        if stage == "production_approved" and source == "llm_trial_fallback":
            raise ValueError("LLM trial fallback cannot become production approved")
        value = ProcessRecommendation(
            recommendation_id=f"recommendation_{uuid.uuid4().hex}", task_id=task_id,
            workflow_id=workflow_id, iteration_number=self.repository.next_iteration(task_id),
            parent_recommendation_id=parent_recommendation_id, process_type=task_spec["process_type"],
            material=task_spec["material"], component_type=task_spec.get("component_type"), stage=stage,
            complete_recipe=recipe, parameter_metadata=metadata, optimized_parameters=optimized,
            fixed_parameters=fixed, forbidden_parameters=dict(space.get("forbidden_parameters") or {}),
            predictions=dict(bo_result.get("predictions") or {}),
            constraints={"derived": space.get("derived_constraints") or [], "outcome": space.get("outcome_constraints") or []},
            recommendation_source=source, source_run_id=source_run_id,
            confidence={"support_status": bo_result.get("model_status"), "uncertainty": bo_result.get("uncertainty")},
            model_version=bo_result.get("model_version"), dataset_version=bo_result.get("dataset_version"),
            search_space_version=space["search_space_version"], objective_version=bo_result.get("objective_version", "1.0"),
            constraint_version=task_spec.get("constraint_version", "1.0"),
            evidence_ids=tuple(task_spec.get("evidence_ids") or ()), prior_ids=tuple(task_spec.get("prior_ids") or ()),
            status=status, created_at=_now(), expires_at=task_spec.get("expires_at"),
        )
        self.repository.save(value)
        return value

    def get(self, recommendation_id: str) -> dict[str, Any]:
        return self.repository.get(recommendation_id)

    def cam_parameters(self, recommendation_id: str) -> dict[str, Any]:
        recommendation = self.get(recommendation_id)
        # CAM 导出前的服务端最终校验：推荐值必须仍在搜索空间允许范围内。
        violations = _validate_recommendation_against_metadata(recommendation)
        if violations:
            raise ValueError(
                "CAM export blocked: parameters violate stored search space bounds: "
                + "; ".join(violations)
            )
        mapped = GenericJsonCamAdapter().map_parameters(recommendation)
        self.repository.save_cam_export(
            f"cam_export_{uuid.uuid4().hex}", recommendation_id, mapped, _now()
        )
        return mapped

    def submit_feedback(self, recommendation_id: str, feedback: dict[str, Any]) -> dict[str, Any]:
        recommendation = self.get(recommendation_id)
        feedback_id = f"process_feedback_{uuid.uuid4().hex}"
        payload = {
            **dict(feedback), "recommendation_id": recommendation_id,
            "task_id": recommendation["task_id"], "raw_feedback_id": feedback_id,
        }
        eligibility = BOEligibilityService().assess(payload)
        candidate_id, now = f"bo_sample_candidate_{uuid.uuid4().hex}", _now()
        self.repository.save_feedback_candidate(
            feedback_id, recommendation_id, feedback, candidate_id, payload,
            eligibility.to_dict(), "eligible_pending_approval" if eligibility.eligible else "ineligible", now,
        )
        return {
            "feedback_id": feedback_id, "recommendation_id": recommendation_id,
            "candidate_id": candidate_id, "eligibility": eligibility.to_dict(),
            "training_sample_created": False,
        }


class BOTrainingApprovalService:
    """Explicit human-approval boundary from feedback candidate to dataset version."""

    def __init__(
        self,
        repository: ProcessRecommendationRepository | None = None,
        registry: BOModelRegistry | None = None,
    ):
        self.repository = repository or ProcessRecommendationRepository()
        self.registry = registry or BOModelRegistry()

    def approve(
        self,
        candidate_id: str,
        approved_by: str,
        prior_sample_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        candidate = self.repository.get_training_candidate(candidate_id)
        eligibility = candidate["eligibility_report"]
        if not eligibility.get("eligible"):
            raise ValueError("ineligible feedback candidate cannot be approved")
        validated_prior_ids = self.repository.require_training_samples(
            prior_sample_ids or []
        )
        approval = self.repository.approve_training_candidate(candidate_id, approved_by)
        payload = candidate["candidate"]
        dataset = self.registry.register_dataset(
            [*validated_prior_ids, approval["sample_id"]],
            {
                "task_id": payload.get("task_id"),
                "recommendation_id": payload.get("recommendation_id"),
                "source": "approved_feedback",
            },
            payload.get("feature_schema_version", "1.0"),
        )
        self.repository.save_dataset_version(dataset.to_dict())
        return {**approval, "candidate_id": candidate_id, "dataset_version": dataset.to_dict()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_against_search_space(
    recipe: dict[str, Any], space: dict[str, Any]
) -> list[str]:
    """服务端最终校验：推荐值必须落在 search_space.variables 的范围内。"""
    violations: list[str] = []
    for name, value in recipe.items():
        variable = (space.get("variables") or {}).get(name) or {}
        if "lower" not in variable or "upper" not in variable:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        lower, upper = float(variable["lower"]), float(variable["upper"])
        if numeric < lower or numeric > upper:
            violations.append(f"{name}={value} outside [{lower}, {upper}]")
    return violations


def _validate_recommendation_against_metadata(
    recommendation: dict[str, Any],
) -> list[str]:
    """CAM 导出前按持久化的 parameter_metadata.allowed_range 复核。"""
    violations: list[str] = []
    metadata = recommendation.get("parameter_metadata") or {}
    recipe = recommendation.get("complete_recipe") or {}
    for name, value in recipe.items():
        item = metadata.get(name) or {}
        allowed = item.get("allowed_range")
        if not allowed or len(allowed) != 2:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        lower, upper = float(allowed[0]), float(allowed[1])
        if numeric < lower or numeric > upper:
            violations.append(f"{name}={value} outside [{lower}, {upper}]")
    return violations
