from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ultrafast_memory.db.init_db import init_database

router = APIRouter(prefix="/api/v1/process-recommendations", tags=["process-recommendations"])


class ProcessRecommendationCreateRequest(BaseModel):
    task_id: str
    workflow_id: str
    task_spec: dict[str, Any]
    bo_result: dict[str, Any]
    search_space: dict[str, Any]
    current_recipe: dict[str, Any] = Field(default_factory=dict)
    stage: str = "trial_cut"
    parent_recommendation_id: str | None = None
    parameter_units: dict[str, str] = Field(default_factory=dict)
    parameter_sources: dict[str, str] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    run_id: str
    cam_applied_parameters: dict[str, Any] = Field(default_factory=dict)
    machine_actual_parameters: dict[str, Any] = Field(default_factory=dict)
    measurements: dict[str, Any] = Field(default_factory=dict)
    run_status: str
    alarms: list[str] = Field(default_factory=list)
    operator_comment: str | None = None
    measurement_method: str | None = None
    replicate_id: str | None = None


class BOTrainingApprovalRequest(BaseModel):
    approved_by: str
    prior_sample_ids: list[str] = Field(default_factory=list)


def _service():
    from ultrafast_agent.process_recommendations import ProcessRecommendationService

    init_database()
    return ProcessRecommendationService()


@router.get("/bo-candidates/review-queue")
def list_bo_training_candidates(status: str = "all", limit: int = 100) -> list[dict[str, Any]]:
    from ultrafast_integrations.storage.process_recommendation_repository import (
        ProcessRecommendationRepository,
    )

    init_database()
    return ProcessRecommendationRepository().list_training_candidates(status, limit)


@router.post("/bo-candidates/{candidate_id}/approve")
def approve_bo_training_candidate(
    candidate_id: str, request: BOTrainingApprovalRequest
) -> dict[str, Any]:
    from ultrafast_agent.process_recommendations import BOTrainingApprovalService

    init_database()
    try:
        return BOTrainingApprovalService().approve(
            candidate_id,
            request.approved_by,
            prior_sample_ids=request.prior_sample_ids,
        )
    except KeyError as exc:
        raise HTTPException(
            404,
            detail={"code": "candidate_not_found", "message": "candidate not found"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={"code": "candidate_not_approvable", "message": str(exc)},
        ) from exc


@router.post("")
def create_recommendation(request: ProcessRecommendationCreateRequest) -> dict[str, Any]:
    return _service().create(**request.model_dump()).to_dict()


@router.get("/{recommendation_id}")
def get_recommendation(recommendation_id: str) -> dict[str, Any]:
    try:
        return _service().get(recommendation_id)
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "recommendation_not_found", "message": "recommendation not found"}) from exc


@router.get("/{recommendation_id}/cam-parameters")
def get_cam_parameters(recommendation_id: str) -> dict[str, Any]:
    try:
        return _service().cam_parameters(recommendation_id)
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "recommendation_not_found", "message": "recommendation not found"}) from exc
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "validation_failed", "message": str(exc)}) from exc


@router.post("/{recommendation_id}/feedback")
def submit_feedback(recommendation_id: str, request: FeedbackRequest) -> dict[str, Any]:
    try:
        return _service().submit_feedback(recommendation_id, request.model_dump())
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "recommendation_not_found", "message": "recommendation not found"}) from exc
