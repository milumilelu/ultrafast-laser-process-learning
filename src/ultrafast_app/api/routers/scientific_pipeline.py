"""Scientific pipeline API（文档 §42.1-42.3）。

POST /api/v1/scientific-retrieval/build-corpus
POST /api/v1/scientific-analysis/analyze
POST /api/v1/scientific-analysis/validate
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ultrafast_knowledge.corpus.builder import ScientificCorpusBuilder
from ultrafast_knowledge.corpus.schemas import EvidenceCorpusPack, RetrievalIntent

router = APIRouter(prefix="/api/v1", tags=["scientific-pipeline"])


class BuildCorpusRequest(BaseModel):
    task_scope: dict[str, Any]
    task_context_id: str = "task-local"
    task_context_version: int = 1
    retrieval_intents: list[str] | None = None


class AnalyzeRequest(BaseModel):
    corpus_pack: EvidenceCorpusPack


class AnalyzeJobRequest(BaseModel):
    """异步科学分析 Job（RAG 检索 → Map → Reduce → Selective Critic，实时进度）。"""

    task_scope: dict[str, Any]
    retrieval_intents: list[str] | None = None
    level: str = "E2P_STRICT"


class ValidateRequest(BaseModel):
    knowledge_pack: dict[str, Any]


class IdentificationV2Request(BaseModel):
    """参数辨识 V2：三模式（raw/physics/hybrid）+ 设备光学属性（可选）。

    knowledge_pack（可选）：共享科学知识包；提供时经 E2P 编译为 FeatureSpec，
    物理特征列表由 E2P 驱动（而非固定公式表）。
    """

    rows: list[dict[str, Any]] = Field(default_factory=list)
    target: str
    mode: str = "raw"
    device_properties: dict[str, Any] = Field(default_factory=dict)
    knowledge_pack: dict[str, Any] | None = None


@router.post("/scientific-retrieval/build-corpus")
def build_corpus(request: BuildCorpusRequest) -> dict[str, Any]:
    intents = None
    if request.retrieval_intents:
        intents = []
        for value in request.retrieval_intents:
            try:
                intents.append(RetrievalIntent(value))
            except ValueError as exc:
                raise HTTPException(
                    400, detail={"code": "invalid_intent", "message": str(exc)}
                ) from exc
    try:
        pack = ScientificCorpusBuilder().build(
            request.task_scope,
            task_context_id=request.task_context_id,
            task_context_version=request.task_context_version,
            intents=intents,
        )
    except ValueError as exc:
        raise HTTPException(
            400, detail={"code": "corpus_build_failed", "message": str(exc)}
        ) from exc
    return pack.model_dump(mode="json")


@router.post("/scientific-analysis/analyze")
def analyze_corpus(request: AnalyzeRequest) -> dict[str, Any]:
    from ultrafast_app.services.scientific_pipeline import (
        LLMNotConfiguredError,
        ScientificAnalysisService,
    )

    try:
        service = ScientificAnalysisService()
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            503,
            detail={
                "code": "llm_not_configured",
                "message": str(exc),
                "hint": "Agent 侧边栏 → 配置 → 保存 API Key 并测试连接后重试",
            },
        ) from exc
    try:
        result = service.analyze(request.corpus_pack)
    except ValueError as exc:
        raise HTTPException(
            400, detail={"code": "analysis_failed", "message": str(exc)}
        ) from exc
    return result


@router.post("/scientific-analysis/validate")
def validate_knowledge(request: ValidateRequest) -> dict[str, Any]:
    from ultrafast_knowledge.scientific.schemas import ScientificKnowledgePack
    from ultrafast_knowledge.scientific.validator import (
        DeterministicScientificValidator,
        default_source_checker,
    )
    from ultrafast_memory.db.session import get_connection

    try:
        pack = ScientificKnowledgePack.model_validate(request.knowledge_pack)
    except Exception as exc:
        raise HTTPException(
            400, detail={"code": "invalid_knowledge_pack", "message": str(exc)}
        ) from exc
    validator = DeterministicScientificValidator(
        source_checker=default_source_checker(get_connection)
    )
    result = validator.validate(pack)
    return result.model_dump(mode="json")


@router.post("/scientific-analysis/jobs")
def create_analysis_job(request: AnalyzeJobRequest) -> dict[str, Any]:
    """异步科学分析 Job：立即返回 run_id；进度经 GET /jobs/{id} 轮询。"""
    from ultrafast_app.services.scientific_jobs import get_job_service

    service = get_job_service()
    job = service.create_job(
        request.task_scope,
        request.retrieval_intents,
        level=request.level,
    )
    return {"analysis_run_id": job.job_id, "status": job.status, "stage": job.stage}


@router.get("/scientific-analysis/jobs/{job_id}")
def get_analysis_job(job_id: str) -> dict[str, Any]:
    from ultrafast_app.services.scientific_jobs import get_job_service

    job = get_job_service().get_job(job_id)
    if job is None:
        raise HTTPException(
            404, detail={"code": "analysis_job_not_found", "message": job_id}
        )
    return job.to_dict()


@router.get("/scientific-analysis/runs")
def list_analysis_runs(limit: int = 20) -> dict[str, Any]:
    """Run Trace：科学分析运行记录（task→job→corpus→knowledge→pipeline 统计）。"""
    from ultrafast_app.services.scientific_trace import RecommendationRunTraceService

    runs = RecommendationRunTraceService().list_recent(limit=min(limit, 100))
    return {"items": runs}


@router.post("/scientific/identification-v2")
def run_identification_v2(request: IdentificationV2Request) -> dict[str, Any]:
    """参数辨识 V2（文档 §32-33）：raw / physics / hybrid 三模式 + 双排名输出。

    physics/hybrid 模式由 PhysicsFeatureBuilder 先构建物理特征（缺设备光学
    属性时对应特征 unavailable 并说明原因，不静默假设）。
    """
    import pandas as pd

    from ultrafast_knowledge.identification.service import identify_v2
    from ultrafast_physics.feature_builder import PhysicsFeatureBuilder

    if request.mode not in {"raw", "physics", "hybrid"}:
        raise HTTPException(
            400, detail={"code": "invalid_mode", "message": "mode must be raw|physics|hybrid"}
        )
    if not request.rows or not request.target:
        raise HTTPException(
            400, detail={"code": "invalid_request", "message": "rows and target are required"}
        )
    frame = pd.DataFrame(request.rows)
    if "parameter_combination_id" not in frame.columns:
        frame["parameter_combination_id"] = [
            f"row-{index}" for index in range(len(frame))
        ]
    device_properties = {
        name: (float(value["value"]), str(value["unit"]))
        for name, value in request.device_properties.items()
        if isinstance(value, dict) and "value" in value
    }
    # E2P 驱动的特征列表（审阅 P2）：knowledge_pack → E2PKnowledgeRouter → FeatureSpec
    feature_specs = None
    if request.knowledge_pack:
        try:
            from ultrafast_knowledge.scientific.knowledge_router import E2PKnowledgeRouter
            from ultrafast_knowledge.scientific.schemas import ScientificKnowledgePack

            knowledge = ScientificKnowledgePack.model_validate(request.knowledge_pack)
            decision = E2PKnowledgeRouter().route(
                knowledge.candidates, {"material": "auto", "target": request.target}
            )
            feature_specs = [spec.feature_id for spec in decision.feature_specs]
        except Exception:  # noqa: BLE001 - 知识包编译失败回退固定特征表
            feature_specs = None
    built = None
    if request.mode in {"physics", "hybrid"}:
        built = PhysicsFeatureBuilder(
            features=tuple(feature_specs) if feature_specs else None
        ).build(request.rows, device_properties)
    feature_columns = {
        "controllable": [
            name for name in (
                "laser_power_W", "frequency_kHz", "pulse_width_fs",
                "scan_speed_mm_s", "hatch_spacing_um", "passes",
            )
            if name in frame.columns
        ],
        "mechanism": built.available_features if built else [],
    }
    if request.mode in {"physics", "hybrid"} and built is not None:
        for name in built.available_features:
            frame[name] = [row.get(name) for row in built.rows]
    feature_build_report = None
    if built is not None:
        feature_build_report = {
            "available_features": built.available_features,
            "unavailable_features": built.unavailable_features,
            "missing_device_properties": built.missing_device_properties,
        }
    # 缺设备光学属性时物理特征不可用：如实返回空排名 + 可用性报告（不 400）
    if request.mode in {"physics", "hybrid"} and not feature_columns["mechanism"]:
        result: dict[str, Any] = {
            "mode": request.mode,
            "target": request.target,
            "feature_count": 0,
            "n_samples": 0,
            "n_unique_designs": 0,
            "cv_strategy": "GroupKFold",
            "controllable_ranking": [],
            "mechanism_ranking": [],
            "mechanism_group_importance": {},
            "claim_boundary": (
                "物理特征不可用：缺少设备/材料属性（如 spot_radius_um 必须与 "
                "spot_definition 成对提供）。补全属性后重试。"
            ),
        }
        if feature_build_report is not None:
            result["feature_build"] = feature_build_report
        return result
    try:
        result = identify_v2(
            frame,
            request.target,
            frame["parameter_combination_id"],
            mode=request.mode,
            feature_columns=feature_columns,
        )
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "identification_failed", "message": str(exc)}) from exc
    if feature_build_report is not None:
        result["feature_build"] = feature_build_report
    return result
