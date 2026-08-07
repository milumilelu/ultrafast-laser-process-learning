"""FastAPI routes for the independent Topic2 backend."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from apps.topic2_backend.service import Topic2Service
from apps.topic2_backend.settings import Settings
from packages.process_contracts.schemas import (
    E2PPrepareRequest,
    EvidenceCompileRequest,
    ExperimentImportRequest,
    ModelPolicyRequest,
    ModelTrainRequest,
    OptimizationRequest,
    ParameterIdentificationRequest,
)

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "apps" / "topic2_frontend" / "dist"

# Optional same-origin proxy to the Ultrafast Laser Agent. The Agent remains an
# enhancement layer: when it is down or the proxy is disabled, only the Agent
# panel degrades and every Topic2 science flow keeps working.
AGENT_PROXY_TARGET = os.getenv(
    "TOPIC2_AGENT_PROXY_TARGET",
    os.getenv("AGENT_PROXY_TARGET", "http://127.0.0.1:8011"),
).strip()


def _not_found(kind: str, identifier: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} not found: {identifier}")


def _agent_review_is_approved(review_id: str) -> bool:
    """Verify live review state at the knowledge-owning Agent boundary."""
    if not AGENT_PROXY_TARGET:
        return False
    try:
        response = httpx.get(
            f"{AGENT_PROXY_TARGET.rstrip('/')}/knowledge/review/tasks/"
            f"{quote(review_id, safe='')}",
            timeout=3.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return response.json().get("review_status") in {
        "accepted_to_rag",
        "accepted_as_literature_evidence",
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Topic2 E2P-Lite Backend",
        version="topic2-backend-v1.0-test",
        description="Offline-capable process data, modeling, parameter identification and GP-UCB backend.",
    )
    service = Topic2Service(settings, approval_verifier=_agent_review_is_approved)
    app.state.topic2_service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        return PlainTextResponse(str(exc), status_code=422)

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": app.version,
            "agent_required": False,
            "llm_required": False,
            "internet_required": False,
            "database_path": str(service.settings.database_path),
        }

    @app.get("/api/v1/materials")
    def materials():
        return {"items": service.repository.materials()}

    @app.get("/api/v1/equipment")
    def equipment():
        return {"items": service.repository.equipment()}

    @app.get("/api/v1/scope-capability")
    def scope_capability(
        material: str | None = None,
        laser_type: str | None = None,
        equipment_id: str | None = None,
        geometry_type: str | None = None,
    ):
        """给定材料/激光/设备/几何组合的样本能力：逐目标统计样本数与独立设计数。"""
        return service.scope_capability(
            material=material,
            laser_type=laser_type,
            equipment_id=equipment_id,
            geometry_type=geometry_type,
        )

    @app.get("/api/v1/experiments")
    def experiments(
        material: str | None = None,
        laser_type: str | None = None,
        equipment_id: str | None = None,
        geometry_type: str | None = None,
        target: str | None = None,
    ):
        return {
            "items": service.repository.list_experiments(
                material=material,
                laser_type=laser_type,
                equipment_id=equipment_id,
                geometry_type=geometry_type,
                target=target,
            )
        }

    @app.get("/api/v1/experiments/export", response_class=PlainTextResponse)
    def export_experiments(material: str | None = None, laser_type: str | None = None):
        return service.export_experiments_csv(material=material, laser_type=laser_type)

    @app.post("/api/v1/experiments/import")
    def import_experiments(request: ExperimentImportRequest):
        return service.import_experiments(request)

    @app.put("/api/v1/experiments/{experiment_id}")
    def update_experiment(experiment_id: str, changes: dict[str, Any]):
        result = service.repository.update_experiment(experiment_id, changes)
        if result is None:
            raise _not_found("experiment", experiment_id)
        return result

    @app.post("/api/v1/parameter-identification/run")
    def parameter_identification(request: ParameterIdentificationRequest):
        return service.parameter_identification(request)

    @app.get("/api/v1/parameter-identification/{run_id}")
    def get_parameter_identification(run_id: str):
        result = service.repository.run(run_id)
        if result is None or result["run_type"] != "parameter_identification":
            raise _not_found("parameter-identification run", run_id)
        return result

    @app.post("/api/v1/models/train")
    def train_model(request: ModelTrainRequest):
        return service.train_model(request, persist=True)

    @app.post("/api/v1/models/evaluate")
    def evaluate_model(request: ModelTrainRequest):
        return service.train_model(request, persist=False)

    @app.get("/api/v1/models")
    def models():
        return {"items": service.repository.models()}

    @app.get("/api/v1/models/{model_id}")
    def model(model_id: str):
        result = service.repository.models(model_id)
        if not result:
            raise _not_found("model", model_id)
        return result[0]

    @app.post("/api/v1/e2p/evidence/compile")
    def evidence_compile(request: EvidenceCompileRequest):
        return service.compile_evidence(request)

    @app.post("/api/v1/e2p/prepare")
    def e2p_prepare(request: E2PPrepareRequest):
        return service.e2p_prepare(request)

    @app.post("/api/v1/e2p/model-policy")
    def model_policy(request: ModelPolicyRequest):
        return service.model_policy(request)

    @app.get("/api/v1/e2p/runs/{run_id}")
    def e2p_run(run_id: str):
        result = service.repository.run(run_id)
        if result is None:
            raise _not_found("E2P run", run_id)
        return result

    @app.post("/api/v1/optimization/recommend")
    def recommend(request: OptimizationRequest):
        return service.recommend(request)

    @app.get("/api/v1/optimization/{run_id}")
    def optimization(run_id: str):
        result = service.repository.run(run_id)
        if result is None or result["run_type"] != "optimization":
            raise _not_found("optimization run", run_id)
        return result

    @app.get("/api/v1/database/statistics")
    def statistics():
        return service.repository.statistics()

    @app.put("/api/v1/task-contexts/{task_context_id}/versions/{version}")
    def save_task_context(
        task_context_id: str, version: int, snapshot: dict[str, Any]
    ):
        return service.save_task_context(task_context_id, version, snapshot)

    @app.get("/api/v1/task-contexts/{task_context_id}")
    def task_context(task_context_id: str, version: int | None = None):
        result = service.repository.task_context(task_context_id, version)
        if result is None:
            raise _not_found("TaskContext", task_context_id)
        return result

    @app.post("/api/v1/process-observations")
    def save_process_observation(observation: dict[str, Any]):
        return service.save_observation(observation)

    @app.get("/api/v1/process-observations")
    def process_observations(task_id: str):
        return {"items": service.repository.observations(task_id)}

    @app.post("/api/v1/process-workflows/commands")
    def workflow_command(command: dict[str, Any]):
        return service.apply_workflow_command(command)

    @app.get("/api/v1/process-workflows/{workflow_id}")
    def process_workflow(workflow_id: str):
        result = service.repository.workflow(workflow_id)
        if result is None:
            raise _not_found("process workflow", workflow_id)
        return {**result, "events": service.repository.workflow_events(workflow_id)}

    @app.get("/api/v1/runs")
    def runs(run_type: str | None = None):
        return {"items": service.repository.list_runs(run_type=run_type)}

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: str):
        result = service.repository.run(run_id)
        if result is None:
            raise _not_found("run", run_id)
        return result

    @app.api_route(
        "/agent-api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        name="agent_proxy",
    )
    async def agent_proxy(path: str, request: Request):
        """Same-origin proxy to the Agent service; the Agent is never required."""
        if not AGENT_PROXY_TARGET:
            raise HTTPException(status_code=503, detail="agent proxy is disabled")
        url = f"{AGENT_PROXY_TARGET.rstrip('/')}/{path}"
        body = await request.body()
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        try:
            async with httpx.AsyncClient(timeout=240.0) as client:
                upstream = await client.request(
                    request.method, url, headers=headers, content=body
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"agent service unreachable: {exc}",
            ) from exc
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    if FRONTEND_DIST.is_dir() and (FRONTEND_DIST / "index.html").exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app
