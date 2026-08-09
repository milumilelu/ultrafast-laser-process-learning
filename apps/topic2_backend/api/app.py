"""FastAPI routes for the independent Topic2 backend."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from apps.topic2_backend.application.service import Topic2ApplicationService
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


class ApplicationRunRequest(BaseModel):
    """Application Run creation contract (BE-1, idempotent via client_request_id)."""

    model_config = ConfigDict(extra="forbid")

    mode: str = "research"
    task_spec: dict[str, Any] | None = None
    stages: list[str] | None = None
    optimization_modes: list[str] | None = None
    random_seed: int | None = None
    client_request_id: str | None = Field(default=None, min_length=1)


class ApplicationContinueRequest(BaseModel):
    """Checkpoint resume contract：续跑同一 ApplicationRun 的剩余阶段。"""

    model_config = ConfigDict(extra="forbid")

    stages: list[str] | None = None
    random_seed: int | None = None
    client_request_id: str | None = Field(default=None, min_length=1)


class OptimizationCompareRequest(BaseModel):
    """Vanilla / Evidence-assisted comparison contract (BE-5)."""

    model_config = ConfigDict(extra="allow")

    scope: dict[str, Any]
    machine_bounds: dict[str, dict[str, float]]
    governed_prior_artifact: dict[str, Any] | None = None
    model_id: str | None = None
    random_seed: int | None = None

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
    application_service = Topic2ApplicationService(
        service,
        approval_verifier=_agent_review_is_approved,
        agent_proxy_target=AGENT_PROXY_TARGET,
    )
    app.state.application_service = application_service

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
            "agent_required": True,
            "llm_required": True,
            "internet_required": True,
            "requirements_by_execution_mode": {
                "RESEARCH": {
                    "agent_equipment_repository": "required",
                    "real_llm_on_cache_miss": "required",
                    "network": "required_when_remote_resources_are_used",
                },
                "DEMO_FIXTURE": {
                    "agent_equipment_repository": "not_used",
                    "real_llm_on_cache_miss": "forbidden_fail_closed",
                    "network": "not_required",
                },
                "SANDBOX": {
                    "agent_equipment_repository": "optional",
                    "real_llm_on_cache_miss": "not_required",
                    "network": "not_required",
                },
            },
            "database_path": str(service.settings.database_path),
        }

    @app.get("/api/v1/materials")
    def materials():
        return {"items": service.repository.materials(real_only=True)}

    @app.get("/api/v1/equipment")
    def equipment():
        """Administrative provenance view; task scope is resolved by the backend."""
        return {"items": service.repository.equipment(real_only=True)}

    @app.get("/api/v1/datasets")
    def datasets():
        return {"items": service.repository.datasets(real_only=True)}

    @app.get("/api/v1/equipment-profiles")
    def equipment_profiles():
        """Synthetic/demo profiles are not part of the user-facing resource API."""
        return {"items": []}

    @app.get("/api/v1/calibration-observation-sets")
    def calibration_observation_sets():
        path = service.settings.calibration_fixture_path
        if path is None or not Path(path).exists():
            return {"items": []}
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"items": []}
        if str(payload.get("origin") or "").upper() in {
            "SYNTHETIC_TEST_FIXTURE",
            "DEMO_FIXTURE",
        }:
            return {"items": []}
        return {
            "items": [
                {
                    "observation_set_id": payload.get("observation_set_id"),
                    "schema_version": payload.get("schema_version"),
                    "material": payload.get("material"),
                    "equipment_profile_id": payload.get("equipment_profile_id"),
                    "origin": payload.get("origin"),
                    "count": len(payload.get("observations") or []),
                }
            ]
            if payload.get("observation_set_id")
            else []
        }

    @app.get("/api/v1/literature")
    def literature():
        try:
            from ultrafast_memory.db.session import get_connection

            with get_connection() as connection:
                rows = connection.execute(
                    """
                    SELECT p.paper_id,p.canonical_title,p.authors,p.year,p.material,
                           p.process_type,p.laser_type,p.source,p.url,
                           c.metadata_json
                    FROM literature_paper p
                    LEFT JOIN literature_chunk c ON c.chunk_id=(
                      SELECT c2.chunk_id FROM literature_chunk c2
                      WHERE c2.paper_id=p.paper_id AND c2.active=1
                      ORDER BY c2.chunk_index LIMIT 1
                    )
                    ORDER BY p.paper_id
                    """
                ).fetchall()
        except Exception:  # noqa: BLE001 - optional catalog degrades to empty
            return {"items": []}
        items = []
        for row in rows:
            item = dict(row)
            try:
                metadata = json.loads(item.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                metadata = {}
            source = str(item.get("source") or "").lower()
            fixture_label = str(metadata.get("fixture_label") or "").upper()
            if "fixture" in source or fixture_label in {
                "CURATED_LITERATURE_FIXTURE",
                "SYNTHETIC_TEST_FIXTURE",
            }:
                continue
            items.append(
                {
                    **item,
                    "fixture_label": metadata.get("fixture_label"),
                    "pdf_ref": metadata.get("pdf_ref") or item.get("url"),
                    "pdf_sha256": metadata.get("pdf_sha256"),
                    "scientific_document_ref": metadata.get(
                        "scientific_document_ref"
                    ),
                }
            )
        return {"items": items}

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
                real_only=True,
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
        return {
            **result,
            "events": service.repository.process_workflow_events(workflow_id),
        }

    @app.get("/api/v1/runs")
    def runs(run_type: str | None = None):
        return {"items": service.repository.list_runs(run_type=run_type)}

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: str):
        result = service.repository.run(run_id)
        if result is None:
            raise _not_found("run", run_id)
        return result

    # ------------------------- Application Run API (BE-1..BE-5) -------------------------

    @app.post("/api/v1/application-runs")
    def create_application_run(payload: ApplicationRunRequest):
        if payload.mode != "research":
            raise HTTPException(
                status_code=422,
                detail="用户入口仅允许 RESEARCH；Demo/Sandbox 不得进入产品界面",
            )
        execution_mode = str(
            (payload.task_spec or {}).get("execution_mode") or "RESEARCH"
        ).upper()
        if execution_mode != "RESEARCH":
            raise HTTPException(
                status_code=422,
                detail="用户入口不接受 Demo/Sandbox 科学输入",
            )
        try:
            return application_service.create_application_run(
                mode=payload.mode,
                task_spec=payload.task_spec,
                stages=payload.stages,
                optimization_modes=payload.optimization_modes,
                random_seed=payload.random_seed,
                client_request_id=payload.client_request_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/application-runs")
    def list_application_runs(mode: str | None = None):
        return {"items": application_service.list_runs(mode="research")}

    def require_public_research_run(run_id: str) -> dict[str, Any]:
        try:
            run = application_service.get_run(run_id)
        except ValueError as exc:
            raise _not_found("application run", run_id) from exc
        execution_mode = str(
            (run.get("task_spec") or {}).get("execution_mode") or "RESEARCH"
        ).upper()
        if run.get("mode") != "research" or execution_mode != "RESEARCH":
            raise _not_found("application run", run_id)
        return run

    @app.get("/api/v1/application-runs/{run_id}")
    def get_application_run(run_id: str):
        return require_public_research_run(run_id)

    @app.get("/api/v1/application-runs/{run_id}/result")
    def application_run_result(run_id: str):
        require_public_research_run(run_id)
        try:
            return application_service.get_result(run_id)
        except ValueError as exc:
            raise _not_found("application run result", run_id) from exc

    @app.get("/api/v1/application-runs/{run_id}/events")
    def application_run_events(
        run_id: str, request: Request, after_sequence: int = 0
    ):
        require_public_research_run(run_id)
        try:
            events = application_service.events(run_id, after_sequence=after_sequence)
        except ValueError as exc:
            raise _not_found("application run", run_id) from exc
        if request.headers.get("accept", "").lower().startswith("application/x-ndjson"):
            lines = "\n".join(
                json.dumps(event, ensure_ascii=False) for event in events
            )
            return Response(
                content=lines,
                media_type="application/x-ndjson",
            )
        return {"items": events}

    @app.get("/api/v1/application-runs/{run_id}/artifacts")
    def application_run_artifacts(run_id: str):
        require_public_research_run(run_id)
        try:
            return {"items": application_service.artifacts(run_id)}
        except ValueError as exc:
            raise _not_found("application run", run_id) from exc

    @app.post("/api/v1/application-runs/{run_id}/replay")
    def replay_application_run(run_id: str):
        del run_id
        raise HTTPException(
            status_code=404,
            detail="用户入口不提供 Demo replay",
        )

    @app.post("/api/v1/application-runs/{run_id}/continue")
    def continue_application_run(run_id: str, payload: ApplicationContinueRequest):
        """Checkpoint resume：同一 ApplicationRun 续跑剩余阶段（不重复已执行阶段）。"""
        require_public_research_run(run_id)
        try:
            return application_service.continue_application_run(
                run_id,
                stages=payload.stages,
                random_seed=payload.random_seed,
                client_request_id=payload.client_request_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/artifacts/{artifact_id}")
    def artifact(artifact_id: str):
        try:
            item = application_service.artifact(artifact_id)
        except ValueError as exc:
            raise _not_found("artifact", artifact_id) from exc
        require_public_research_run(str(item.get("application_run_id") or ""))
        return item

    @app.post("/api/v1/optimization/compare")
    def compare_optimization(payload: OptimizationCompareRequest):
        try:
            return application_service.compare_optimization(
                scope=payload.scope,
                machine_bounds=payload.machine_bounds,
                governed_prior_artifact=payload.governed_prior_artifact,
                model_id=payload.model_id,
                random_seed=payload.random_seed,
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_static(full_path: str):
            """Serve built frontend with SPA fallback (registered last; API routes win)."""
            if full_path.startswith(("api/", "agent-api/")):
                raise HTTPException(status_code=404, detail="not found")
            candidate = (FRONTEND_DIST / full_path).resolve()
            try:
                candidate.relative_to(FRONTEND_DIST.resolve())
            except ValueError:
                raise HTTPException(status_code=404, detail="not found") from None
            headers = {"Cache-Control": "no-cache"}
            if full_path and candidate.is_file():
                return FileResponse(candidate, headers=headers)
            return FileResponse(FRONTEND_DIST / "index.html", headers=headers)

    return app
