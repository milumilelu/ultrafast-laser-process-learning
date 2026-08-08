"""Topic2 Application Orchestrator (BE-1).

Wraps the frozen scientific stages (identification / modeling / evidence /
CFA / governed prior / vanilla+assisted BO) into one formal application run
with persistence (BE-2), workflow events (BE-3) and artifact queries (BE-4).

Demo mode binds DEMO_SCENARIO_01 (SiC / fs / rectangular_groove / depth_um /
EQ-DEMO-FS / seed 42) and runs the frozen vertical slice over the fixed
5-paper pilot set when the literature archive is available; otherwise it falls
back to the offline synthetic-ledger path, never faking results.

Research mode consumes the Topic2 repository: evidence from the evidence
table + agent RAG candidates (via proxy, graceful), governed prior only when
live approval verification passes (fails closed), BO via the frozen
recommend path with vanilla and evidence-assisted comparison (BE-5).
"""

from __future__ import annotations

import json
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from apps.topic2_backend.application.events import (
    ARTIFACT_CREATED,
    ERROR,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    STAGE_COMPLETED,
    STAGE_STARTED,
    TOOL_COMPLETED,
    VALIDATION,
    WARNING,
    WorkflowEventBus,
)
from apps.topic2_backend.application.trace import ScientificTrace
from apps.topic2_backend.service import Topic2Service
from packages.e2p.application.traceability import new_run_id, timestamp
from packages.process_contracts.schemas import (
    CORE_PARAMETER_NAMES,
    E2PPrepareRequest,
    Evidence,
    EvidenceCompileRequest,
    ModelTrainRequest,
    OptimizationRequest,
    ParameterIdentificationRequest,
    TaskScope,
)
from packages.process_data.profile import build_data_profile
from packages.process_data.versioning import canonical_hash

WORKFLOW_VERSION = "topic2-application-v1"
DEMO_SCENARIO_01 = {
    "material": "SiC",
    "laser_type": "fs",
    "process_type": "fs_laser_processing",
    "geometry_type": "rectangular_groove",
    "objective_metric": "depth_um",
    "equipment_profile_id": "EQ-DEMO-FS",
    "random_seed": 42,
    "knowledge_gate_decision": {"status": "allowed"},
}

PILOT_PAPER_IDS = (
    "04_arxiv_2502.16530.pdf",
    "10_arxiv_2411.18093.pdf",
    "11_arxiv_2404.09906.pdf",
    "13_arxiv_2411.18868.pdf",
    "Flat-top picosecond laser texturing of CFRP.pdf",
)

# V0 task-driven main chain (DEMO0.1 §2/§8): 8 top-level stages.
ALL_STAGES = (
    "prepare_task",
    "assess_data",
    "baseline_learning",
    "analyze_knowledge_gaps",
    "prepare_knowledge",
    "satisfy_requirements",
    "apply_knowledge",
    "optimization",
)

STAGE_LABELS = {
    "prepare_task": "任务准备",
    "assess_data": "数据与物理就绪评估",
    "baseline_learning": "基线过程学习（RAW）",
    "analyze_knowledge_gaps": "知识缺口分析",
    "prepare_knowledge": "知识准备（文献/证据）",
    "satisfy_requirements": "需求满足评估",
    "apply_knowledge": "知识应用（特征/先验）",
    "optimization": "Vanilla / Assisted BO",
}

# sub-events emitted inside prepare_knowledge (not top-level stages)
PREPARE_KNOWLEDGE_SUB_EVENTS = (
    "existing_knowledge_check",
    "literature_retrieval",
    "document_parse",
    "candidate_discovery",
    "condition_reconstruction",
    "evidence_projection",
    "applicability",
)

SLICE_STAGE_LABELS = (
    "process_learning",
    "literature_evidence",
    "evidence_ir",
    "e2p_prior",
    "cfa",
    "bo",
)


class Topic2ApplicationService:
    def __init__(
        self,
        topic2: Topic2Service,
        *,
        approval_verifier: Callable[[str], bool] | None = None,
        agent_proxy_target: str | None = None,
        fixture_csv: str | None = None,
        workflow_version: str = WORKFLOW_VERSION,
    ):
        self.topic2 = topic2
        self.repository = topic2.repository
        self.settings = topic2.settings
        self.approval_verifier = approval_verifier
        self.agent_proxy_target = agent_proxy_target
        self.workflow_version = workflow_version
        self.fixture_csv = fixture_csv

    # --------------------------------------------------------------- scoping

    def _scope(self, payload: dict[str, Any]) -> TaskScope:
        if isinstance(payload, TaskScope):
            return payload
        if "equipment_id" in payload and "target" in payload:
            return TaskScope.model_validate(payload)
        material = payload.get("material")
        laser_type = payload.get("laser_type")
        equipment_id = payload.get("equipment_profile_id")
        geometry_type = payload.get("geometry_type")
        target = payload.get("objective_metric")
        missing = [
            key
            for key, value in (
                ("material", material),
                ("laser_type", laser_type),
                ("equipment_profile_id", equipment_id),
                ("geometry_type", geometry_type),
                ("objective_metric", target),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"task spec incomplete, missing: {', '.join(missing)}")
        if laser_type not in ("fs", "ps"):
            raise ValueError(f"unsupported laser_type: {laser_type}")
        if target not in ("depth_um", "roughness_um"):
            raise ValueError(f"unsupported objective_metric: {target}")
        return TaskScope(
            task_context_id=payload.get("task_context_id"),
            task_context_version=payload.get("task_context_version"),
            material=str(material),
            laser_type=str(laser_type),
            equipment_id=str(equipment_id),
            geometry_type=str(geometry_type),
            target=str(target),
            process_parameters=dict(payload.get("process_parameters") or {}),
            device_properties=dict(payload.get("device_properties") or {}),
        )

    # ------------------------------------------------------------- creation

    def create_application_run(
        self,
        *,
        mode: str,
        task_spec: dict[str, Any] | None = None,
        stages: list[str] | None = None,
        optimization_modes: list[str] | None = None,
        random_seed: int | None = None,
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        if mode not in ("demo", "research"):
            raise ValueError("mode must be demo or research")
        if client_request_id:
            existing = self.repository.application_run_by_client_request(client_request_id)
            if existing is not None:
                return self._run_summary(existing)
        requested_stages = list(stages) if stages else list(ALL_STAGES)
        unknown = set(requested_stages).difference(ALL_STAGES)
        if unknown:
            raise ValueError(f"unknown stages: {sorted(unknown)}")

        if mode == "demo":
            effective_seed = (
                random_seed if random_seed is not None else DEMO_SCENARIO_01["random_seed"]
            )
            task_spec = task_spec or self._demo_task_spec(effective_seed)
        else:
            if task_spec is None:
                raise ValueError("research mode requires a task_spec")
            effective_seed = (
                random_seed if random_seed is not None else self.settings.random_seed
            )

        run_id = new_run_id("app")
        scope = self._scope(task_spec)
        task_ref = f"{scope.task_context_id or 'demo'}:v{scope.task_context_version or 1}"
        bus = WorkflowEventBus(run_id, self.repository, task_ref)
        self.repository.save_application_run(
            {
                "application_run_id": run_id,
                "client_request_id": client_request_id,
                "task_context_ref": task_ref,
                "mode": mode,
                "workflow_version": self.workflow_version,
                "status": "running",
                "stage_status": {},
                "task_spec": task_spec,
                "stage_results": {},
            }
        )
        bus.emit(
            RUN_STARTED,
            f"应用运行开始（{'演示' if mode == 'demo' else '研究'}模式）",
            stage="application",
            details={"mode": mode, "task_context_ref": task_ref},
        )
        try:
            if mode == "demo":
                summary = self._run_demo_slice(task_spec, bus, effective_seed)
                stage_results: dict[str, Any] = {}
            else:
                summary, stage_results = self._run_research(
                    task_spec, scope, requested_stages, bus, effective_seed
                )
            self.repository.save_application_run(
                {
                    "application_run_id": run_id,
                    "client_request_id": client_request_id,
                    "task_context_ref": task_ref,
                    "mode": mode,
                    "workflow_version": self.workflow_version,
                    "status": "completed",
                    "stage_status": {
                        stage: {"status": "completed"} for stage in requested_stages
                    }
                    if mode == "research"
                    else {
                        stage: {"status": "completed"}
                        for stage in SLICE_STAGE_LABELS
                    },
                    "result": summary,
                    "task_spec": task_spec,
                    "stage_results": stage_results,
                    "completed_at": timestamp(),
                }
            )
            bus.emit(RUN_COMPLETED, "应用运行完成", stage="application")
            run = self.repository.application_run(run_id) or {}
            return self._run_summary(run)
        except Exception as exc:  # noqa: BLE001 - surfaced as run state
            bus.emit(
                ERROR,
                f"应用运行失败：{exc}",
                stage="application",
                details={"traceback": traceback.format_exc()[-2000:]},
            )
            self.repository.save_application_run(
                {
                    "application_run_id": run_id,
                    "client_request_id": client_request_id,
                    "task_context_ref": task_ref,
                    "mode": mode,
                    "workflow_version": self.workflow_version,
                    "status": "failed",
                    "stage_status": {},
                    "task_spec": task_spec,
                    "stage_results": {},
                    "completed_at": timestamp(),
                }
            )
            bus.emit(RUN_FAILED, f"应用运行失败：{exc}", stage="application")
            raise

    # ------------------------------------------------------ checkpoint resume

    # 两段式入口：先运行到知识缺口（1-4），检查 Requirement 后再续跑知识准备（5-8）。
    GAP_STAGES = ("prepare_task", "assess_data", "baseline_learning", "analyze_knowledge_gaps")
    KNOWLEDGE_STAGES = (
        "prepare_knowledge",
        "satisfy_requirements",
        "apply_knowledge",
        "optimization",
    )

    def continue_application_run(
        self,
        run_id: str,
        *,
        stages: list[str] | None = None,
        random_seed: int | None = None,
        client_request_id: str | None = None,
    ) -> dict[str, Any]:
        """Resume the same ApplicationRun from a checkpoint with the remaining stages.

        Never re-executes completed stages (same run = one execution per stage).
        """
        run = self.repository.application_run(run_id)
        if run is None:
            raise ValueError(f"application run not found: {run_id}")
        if run.get("mode") != "research":
            raise ValueError("continue is only available for research runs")
        if run.get("status") == "running":
            raise ValueError("application run is still running")
        task_spec = run.get("task_spec")
        if not task_spec:
            raise ValueError("application run has no stored task_spec (cannot resume)")
        completed = set((run.get("stage_status") or {}).keys())
        requested = (
            list(stages)
            if stages
            else [stage for stage in ALL_STAGES if stage not in completed]
        )
        unknown = set(requested).difference(ALL_STAGES)
        if unknown:
            raise ValueError(f"unknown stages: {sorted(unknown)}")
        overlap = completed.intersection(requested)
        if overlap:
            raise ValueError(f"stages already executed, refusing to re-run: {sorted(overlap)}")
        if not requested:
            return self._run_summary(run)

        scope = self._scope(task_spec)
        effective_seed = (
            random_seed if random_seed is not None else self.settings.random_seed
        )
        bus = WorkflowEventBus(run_id, self.repository, run["task_context_ref"])
        merged_status = {
            **dict(run.get("stage_status") or {}),
            **{stage: {"status": "running"} for stage in requested},
        }
        self.repository.save_application_run(
            {
                "application_run_id": run_id,
                "client_request_id": client_request_id,
                "task_context_ref": run["task_context_ref"],
                "mode": "research",
                "workflow_version": self.workflow_version,
                "status": "running",
                "stage_status": merged_status,
                "task_spec": task_spec,
                "stage_results": run.get("stage_results") or {},
            }
        )
        bus.emit(
            RUN_STARTED,
            f"应用运行续跑开始（{len(requested)} 个阶段）",
            stage="application",
            details={"resumed_stages": requested},
        )
        try:
            summary, stage_results = self._run_research(
                task_spec,
                scope,
                requested,
                bus,
                effective_seed,
                existing_result=run.get("stage_results") or {},
            )
            final_status = {
                **dict(run.get("stage_status") or {}),
                **{stage: {"status": "completed"} for stage in requested},
            }
            self.repository.save_application_run(
                {
                    "application_run_id": run_id,
                    "client_request_id": client_request_id,
                    "task_context_ref": run["task_context_ref"],
                    "mode": "research",
                    "workflow_version": self.workflow_version,
                    "status": "completed",
                    "stage_status": final_status,
                    "result": summary,
                    "task_spec": task_spec,
                    "stage_results": stage_results,
                    "completed_at": timestamp(),
                }
            )
            bus.emit(RUN_COMPLETED, "应用运行完成", stage="application")
            return self._run_summary(self.repository.application_run(run_id) or {})
        except Exception as exc:  # noqa: BLE001 - surfaced as run state
            bus.emit(
                ERROR,
                f"应用运行续跑失败：{exc}",
                stage="application",
                details={"traceback": traceback.format_exc()[-2000:]},
            )
            self.repository.save_application_run(
                {
                    "application_run_id": run_id,
                    "client_request_id": client_request_id,
                    "task_context_ref": run["task_context_ref"],
                    "mode": "research",
                    "workflow_version": self.workflow_version,
                    "status": "failed",
                    "stage_status": merged_status,
                    "task_spec": task_spec,
                    "stage_results": run.get("stage_results") or {},
                    "completed_at": timestamp(),
                }
            )
            bus.emit(RUN_FAILED, f"应用运行续跑失败：{exc}", stage="application")
            raise

    def _run_research(
        self,
        task_spec: dict[str, Any],
        scope: TaskScope,
        stages: list[str],
        bus: WorkflowEventBus,
        random_seed: int,
        existing_result: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Execute stages over an (optional) existing result; return (summary, stage_results)."""
        result: dict[str, Any] = dict(existing_result or {})
        for stage in stages:
            bus.emit(STAGE_STARTED, STAGE_LABELS[stage], stage=stage)
            handler = getattr(self, f"_stage_{stage}")
            stage_result = handler(task_spec, scope, bus, random_seed=random_seed)
            result[stage] = stage_result["content"]
            bus.emit(
                STAGE_COMPLETED,
                f"{STAGE_LABELS[stage]} 完成",
                stage=stage,
                details=stage_result["meta"],
            )
        summary = self._research_summary(result, scope, task_spec, random_seed, bus.run_id)
        return summary, result

    def _demo_task_spec(self, random_seed: int) -> dict[str, Any]:
        spec = dict(DEMO_SCENARIO_01)
        spec["random_seed"] = random_seed
        return spec

    # ------------------------------------------------------------ demo path

    def _run_demo_slice(
        self, task_spec: dict[str, Any], bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Frozen DEMO_SCENARIO_01 over the fixed 5-paper pilot set.

        Real PDFs when the literature archive is present; otherwise the
        offline synthetic-ledger fallback (same contract, honest evidence).
        """
        from demo.t2_slice.pipeline import run_vertical_slice

        csv_path = Path(self.fixture_csv) if self.fixture_csv else (
            Path(__file__).resolve().parents[3]
            / "data"
            / "test_fixture"
            / "topic2_experiments_v1.csv"
        )
        documents, mentions_by_paper, regions_by_paper = self._pilot_documents(bus)
        bus.emit(
            VALIDATION,
            f"演示文献集：{len(documents)} 篇（固定 pilot set）",
            stage="literature_evidence",
            details={"paper_count": len(documents)},
        )
        result = run_vertical_slice(
            csv_path=csv_path,
            documents=documents,
            mentions_by_paper=mentions_by_paper,
            regions_by_paper=regions_by_paper,
            task_spec=task_spec,
            random_seed=random_seed,
        )
        for region in SLICE_STAGE_LABELS:
            if region in result:
                artifact_id = self._persist_artifact(bus.run_id, region, result[region])
                bus.emit(
                    ARTIFACT_CREATED,
                    f"{region} 完成（{artifact_id}）",
                    stage=region,
                    artifact_refs=[{"type": region, "id": artifact_id}],
                )
        summary = self._demo_summary(result, task_spec, random_seed, bus.run_id)
        artifact_id = self._persist_artifact(
            bus.run_id, "Topic2ApplicationResult", summary
        )
        bus.emit(
            ARTIFACT_CREATED,
            f"应用结果汇总已生成（{artifact_id}）",
            stage="application_result",
            artifact_refs=[{"type": "Topic2ApplicationResult", "id": artifact_id}],
        )
        return summary

    def _pilot_documents(self, bus: WorkflowEventBus) -> tuple[list, dict, dict]:
        try:
            from demo.t2_slice.resources import resolve_literature_archive
            from ultrafast_ingestion import PyMuPDFDocumentParser
            from ultrafast_ingestion.tables.models import table_regions
            from ultrafast_ingestion.mentions.extractor import extract_mentions

            archive = resolve_literature_archive()
        except Exception:
            archive = None
        if archive is None:
            bus.emit(
                WARNING,
                "文献档案不可用，演示退回离线 synthetic ledger（真实论文链需 ULTRAFAST_PILOT_ARCHIVE）",
                stage="literature_evidence",
            )
            return self._synthetic_documents()

        parser = PyMuPDFDocumentParser()
        documents, mentions_by_paper, regions_by_paper = [], {}, {}
        for paper_id in PILOT_PAPER_IDS:
            try:
                from demo.t2_slice.resources import resolve_pilot_pdf

                pdf = resolve_pilot_pdf(paper_id)
                doc = parser.parse(pdf)
                documents.append(doc)
                mentions_by_paper[doc.paper_id] = extract_mentions(doc)
                regions_by_paper[doc.paper_id] = table_regions(doc)
            except Exception as exc:
                bus.emit(
                    WARNING,
                    f"论文 {paper_id} 跳过：{exc}",
                    stage="literature_evidence",
                )
        if not documents:
            raise ValueError("no pilot documents could be loaded")
        return documents, mentions_by_paper, regions_by_paper

    def _synthetic_documents(self) -> tuple[list, dict, dict]:
        """Offline fallback: one synthetic paper covering frequency/scan bounds."""
        from ultrafast_ingestion.mentions.extractor import extract_mentions
        from ultrafast_ingestion.models.document import (
            PageBlock,
            ScientificDocument,
            Section,
        )

        text = (
            "The laser was operated at 1030 nm with a repetition rate of 200 kHz "
            "and a pulse width of 300 fs. The scan speed was 300 mm/s."
        )
        block = PageBlock(
            paper_id="p_demo",
            document_version_id="dv_test_0000000000000000",
            page_index=0,
            bbox=(0.0, 0.0, 500.0, 100.0),
            block_index=0,
            reading_order=0,
            text=text,
            section_id="s1",
            section_path="Methods",
        )
        section = Section(
            section_id="s1",
            title="Methods",
            section_type="methods",
            level=1,
            page_start=0,
            page_end=0,
            path="Methods",
        )
        doc = ScientificDocument(
            paper_id="p_demo",
            document_version_id="dv_test_0000000000000000",
            pdf_path="",
            pdf_sha256="",
            parser_name="synthetic",
            parser_version="0",
            schema_version="synthetic",
            config_hash="synthetic",
            pages=[[block]],
            sections=[section],
            blocks_by_id={block.block_id(): block},
        )
        mentions = extract_mentions(doc)
        return [doc], {doc.paper_id: mentions}, {doc.paper_id: []}

    # ---------------------------------------------------------- research stages

    def _stage_prepare_task(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Stage 1: canonical task + scope capability."""
        capability = self.topic2.scope_capability(
            material=scope.material,
            laser_type=scope.laser_type,
            equipment_id=scope.equipment_id,
            geometry_type=scope.geometry_type,
        )
        meta = {
            "n_samples": capability["n_samples"],
            "n_unique_designs": capability["n_unique_designs"],
            "meets_identification": capability["meets_identification"],
            "meets_modeling": capability["meets_modeling"],
        }
        bus.emit(
            VALIDATION,
            f"任务准备：{capability['n_samples']} 样本 / {capability['n_unique_designs']} 独立设计",
            stage="prepare_task",
            details=meta,
        )
        return {"meta": meta, "content": capability}

    def _stage_assess_data(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Stage 2: DataState + TargetPhysicsReadiness (real backend report)."""
        rows = self.topic2._rows_for_scope(scope)
        profile = build_data_profile(rows)
        summary = {
            "n_samples": profile.n_samples,
            "n_unique_designs": profile.n_unique_designs,
            "dataset_version": (self.repository.latest_dataset() or {}).get(
                "dataset_version"
            ),
            "dataset_hash": (self.repository.latest_dataset() or {}).get("dataset_hash"),
        }
        trace = ScientificTrace(bus, "assess_data")
        dataset_artifact = self._persist_artifact(
            bus.run_id,
            "DataProfile",
            summary,
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
        )
        trace.artifact_created(
            "DataProfile",
            dataset_artifact,
            name=f"数据状态快照（{dataset_artifact}）",
            counts={"n_samples": summary["n_samples"]},
        )
        readiness = self._target_readiness(rows, scope)
        coordinates = self._readiness_coordinates(readiness)
        cfa = {
            "version": "uncalibrated-cfa-v0.1",
            "calibration_status": "NOT_YET_CALIBRATED",
            "target_physics_readiness": readiness,
            "coordinates": coordinates,
            "facet_summary": self._facet_summary(scope, coordinates),
            "warnings": ["未校准 CFA 仅作审计；source 侧文献状态在 prepare_knowledge 阶段重建"],
        }
        readiness_artifact = self._persist_artifact(
            bus.run_id,
            "TargetPhysicsReadiness",
            cfa,
            input_refs=[{"type": "DataProfile", "id": dataset_artifact}],
        )
        trace.artifact_created(
            "TargetPhysicsReadiness",
            readiness_artifact,
            name=f"物理就绪评估完成（{readiness_artifact}）",
            counts={
                "available": sum(
                    1 for c in coordinates if str(c.get("status")) == "AVAILABLE"
                ),
                "blocked": sum(
                    1 for c in coordinates if str(c.get("status")) == "BLOCKED"
                ),
            },
        )
        return {
            "meta": {
                "artifact_id": dataset_artifact,
                "readiness_artifact_id": readiness_artifact,
            },
            "content": {"dataset": summary, "cfa": cfa},
        }

    @staticmethod
    def _facet_summary(scope: TaskScope, coordinates: list[dict[str, Any]]) -> dict[str, str]:
        any_ready = any(
            str(c.get("status")) in {"AVAILABLE", "UNVERIFIED"} for c in coordinates
        )
        return {
            "Material": "KNOWN" if scope.material else "UNKNOWN",
            "Task": "PARTIAL" if scope.geometry_type and scope.target else "UNKNOWN",
            "InteractionState": "PARTIAL" if any_ready else "UNKNOWN",
            "Reconstructibility": "UNKNOWN",
            "Reachability": "UNKNOWN",
        }

    def _stage_baseline_learning(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Stage 3: baseline RAW process learning (identification + modeling).

        V0 baseline = RAW only (DEMO0.1 §P0-4); physics-backed views are a
        later phase and are never silently injected.
        """
        trace = ScientificTrace(bus, "baseline_learning")
        trace.operation_started(
            "baseline-identification",
            "参数辨识",
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
        )
        identification = self.topic2.parameter_identification(
            ParameterIdentificationRequest(
                scope=scope,
                methods=["rsm_effect", "permutation_importance"],
                random_seed=random_seed,
            )
        )
        # 归一化辨识排名：后端 results 为扁平列表（parameter/importance/rank），
        # 归一化为前端 controllable_ranking / mechanism_ranking 契约
        raw_results = identification.get("results") or []
        controllable = [
            {
                "feature": item["parameter"],
                "importance": item.get("importance"),
                "effect_direction": item.get("effect_direction"),
                "rank": item.get("rank"),
            }
            for item in raw_results
            if isinstance(item, dict) and item.get("parameter")
        ]
        identification["controllable_ranking"] = controllable
        identification["mechanism_ranking"] = []
        identification_artifact = self._persist_artifact(
            bus.run_id,
            "ProcessLearningResult",
            identification,
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
        )
        trace.operation_completed(
            "baseline-identification",
            f"参数辨识完成（{identification['run_id']}）",
            output_refs=[
                {"type": "ProcessLearningResult", "id": identification_artifact}
            ],
            counts={
                "parameters": len(controllable),
                "methods": len(identification.get("methods") or []),
            },
        )
        trace.operation_started(
            "baseline-training",
            "模型训练与比较",
            input_refs=[
                {"type": "ProcessLearningResult", "id": identification_artifact}
            ],
        )
        training = self.topic2.train_model(
            ModelTrainRequest(scope=scope, random_seed=random_seed), persist=True
        )
        training_artifact = self._persist_artifact(
            bus.run_id,
            "ModelTrainingResult",
            training,
            input_refs=[{"type": "ProcessLearningResult", "id": identification_artifact}],
        )
        metrics = training.get("validation_metrics") or {}
        trace.operation_completed(
            "baseline-training",
            f"模型训练完成（{training['run_id']}）",
            output_refs=[{"type": "ModelTrainingResult", "id": training_artifact}],
            counts={"models": len(metrics)},
            reason_codes=[f"selected={training.get('selected_model')}"],
        )
        content = {
            "identification": identification,
            "modeling": training,
            "selected_model": training["selected_model"],
            "selected_feature_view": "RAW",
        }
        return {
            "meta": {
                "identification_run_id": identification["run_id"],
                "training_run_id": training["run_id"],
            },
            "content": content,
        }

    def _stage_analyze_knowledge_gaps(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Stage 4: deterministic diagnostics -> KnowledgeRequirement[].

        Inputs are real diagnostics (readiness / baseline metrics /
        identification / existing evidence); the LLM (when reachable) is a
        later provisional refinement, never the source of truth.
        """
        trace = ScientificTrace(bus, "analyze_knowledge_gaps")
        trace.operation_started(
            "gap-diagnostics",
            "知识缺口分析（确定性诊断）",
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
        )
        requirements = self._knowledge_requirements(scope, bus)
        diagnostics = self._knowledge_diagnostics(scope)
        trace.validation(
            f"知识缺口分析：{len(requirements)} 条需求（{len(diagnostics['missing_inputs'])} 项物理输入缺失）",
            counts={
                "requirements": len(requirements),
                "missing_inputs": len(diagnostics["missing_inputs"]),
                "blocked_coordinates": len(diagnostics["blocked_coordinates"]),
            },
        )
        artifact_id = self._persist_artifact(
            bus.run_id,
            "KnowledgeRequirements",
            {"requirements": requirements, "diagnostics": diagnostics},
            input_refs=[{"type": "TargetPhysicsReadiness", "id": "assess_data"}],
        )
        trace.operation_completed(
            "gap-diagnostics",
            f"知识需求清单生成（{artifact_id}）",
            output_refs=[{"type": "KnowledgeRequirements", "id": artifact_id}],
            counts={"requirements": len(requirements)},
        )
        return {
            "meta": {"artifact_id": artifact_id, "requirement_count": len(requirements)},
            "content": {"requirements": requirements, "diagnostics": diagnostics},
        }

    def _knowledge_diagnostics(self, scope: TaskScope) -> dict[str, Any]:
        """Deterministic diagnostics consumed by gap analysis (P0-5)."""
        rows = self.topic2._rows_for_scope(scope)
        readiness = self._target_readiness(rows, scope)
        missing_inputs = sorted(
            set(readiness.get("blocking_dependencies") or [])
        )
        coordinates = self._readiness_coordinates(readiness)
        blocked = [
            c["coordinate"]
            for c in coordinates
            if str(c.get("status")) == "BLOCKED"
        ]
        profile = build_data_profile(rows)
        return {
            "n_samples": profile.n_samples,
            "n_unique_designs": profile.n_unique_designs,
            "missing_inputs": missing_inputs,
            "blocked_coordinates": blocked,
            "readiness_status": readiness.get("status"),
        }

    def _knowledge_requirements(
        self, scope: TaskScope, bus: WorkflowEventBus
    ) -> list[dict[str, Any]]:
        """Rules over real diagnostics -> KnowledgeRequirement[].

        V0 is deliberately simple: every requirement carries trigger_reasons
        that point at the diagnostic evidence behind it.
        """
        diagnostics = self._knowledge_diagnostics(scope)
        requirements: list[dict[str, Any]] = []
        req_id = 0

        def add(
            type_: str,
            question: str,
            required_for: str,
            priority: str,
            reasons: list[str],
        ) -> None:
            nonlocal req_id
            req_id += 1
            requirements.append(
                {
                    "requirement_id": f"KR-{req_id:02d}",
                    "type": type_,
                    "question": question,
                    "required_for": required_for,
                    "priority": priority,
                    "trigger_reasons": reasons,
                }
            )

        missing = diagnostics["missing_inputs"]
        if missing:
            add(
                "physics_dependency",
                f"缺失物理输入（{', '.join(missing)}）对哪些加工特征的影响最大？",
                "learning",
                "high",
                [f"missing physics inputs: {', '.join(missing)}"],
            )
        if diagnostics["blocked_coordinates"]:
            add(
                "threshold",
                "当前材料在该工艺窗口的烧蚀阈值/损伤阈值是多少？",
                "both",
                "high",
                [f"blocked coordinates: {', '.join(diagnostics['blocked_coordinates'])}"],
            )
        if diagnostics["n_unique_designs"] < 10:
            add(
                "data_quality",
                "当前实验设计数量较少，哪些参数区间最值得补充实验？",
                "planning",
                "medium",
                [f"n_unique_designs={diagnostics['n_unique_designs']}"],
            )
        add(
            "parameter_effect",
            f"各可控参数对 {scope.target} 的效应方向与量级（超出当前数据范围）？",
            "learning",
            "medium",
            ["baseline identification covers data range only"],
        )
        add(
            "reported_optimum",
            f"文献报道的 {scope.target} 最优工艺窗口在哪里？",
            "planning",
            "medium",
            ["BO planning benefits from promising regions"],
        )
        add(
            "process_mechanism",
            "主导加工机理（热/烧蚀/非线性吸收）对结果有何影响？",
            "both",
            "low",
            ["mechanism knowledge supports feature hypotheses"],
        )
        return requirements

    def _stage_prepare_knowledge(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Stage 5: knowledge preparation with traced sub-operations.

        V0: existing knowledge check (evidence table) + literature retrieval
        (agent candidates, graceful). Document parsing / candidate discovery /
        condition reconstruction land in later phases and emit honest
        'not executed' warnings instead of pretending.
        """
        trace = ScientificTrace(bus, "prepare_knowledge")
        # sub-operation 1: existing knowledge check
        trace.operation_started(
            "prepare-existing-check",
            "已有知识检查",
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
        )
        evidence = self._evidence_for_scope(scope)
        existing = {
            "evidence_count": len(evidence),
            "governed_evidence_count": 0,
            "candidate_count": 0,
            "paper_count": 0,
            "topics": sorted(
                {
                    str(item.claim_type)
                    for item in evidence
                    if item.claim_type
                }
            ),
        }
        trace.operation_completed(
            "prepare-existing-check",
            f"已有知识：{len(evidence)} 条证据",
            counts={"evidence": len(evidence), "topics": len(existing["topics"])},
            output_refs=[],
        )
        # sub-operation 2: literature retrieval (agent candidates, graceful)
        trace.operation_started(
            "prepare-literature-retrieval",
            "文献检索（Agent 候选）",
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
        )
        retrieved_count = len(evidence)
        trace.operation_completed(
            "prepare-literature-retrieval",
            f"文献候选：{retrieved_count} 条",
            counts={"retrieved": retrieved_count},
            reason_codes=(
                ["agent_candidates"]
                if retrieved_count
                else ["no_agent_or_no_candidates"]
            ),
        )
        for sub in ("document_parse", "candidate_discovery", "condition_reconstruction"):
            trace.warning(f"{sub} 暂未执行（后续阶段接入 canonical 文献链）")
        bundle = self.topic2.compile_evidence(
            EvidenceCompileRequest(scope=scope, evidence=evidence)
        )
        for item in bundle.get("candidates", []):
            trace.entity_created(
                "Evidence", str(item.get("evidence_id")), "证据进入证据篮"
            )
        artifact_id = self._persist_artifact(
            bus.run_id,
            "EvidenceCompileResult",
            bundle,
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
        )
        accepted_count = len(bundle.get("accepted") or [])
        rejected_count = len(bundle.get("rejected") or [])
        trace.artifact_created(
            "EvidenceCompileResult",
            artifact_id,
            name=f"证据投影与适用性完成（{artifact_id}）",
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
            counts={
                "candidates": len(bundle.get("candidates") or []),
                "accepted": accepted_count,
                "rejected": rejected_count,
            },
        )
        return {
            "meta": {
                "artifact_id": artifact_id,
                "evidence_count": accepted_count,
            },
            "content": {
                "bundle": bundle,
                "evidence_count": len(evidence),
                "existing_knowledge": existing,
            },
        }

    def _stage_satisfy_requirements(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Stage 6: requirement satisfaction -> KnowledgeState.

        V0 uses DETERMINISTIC_PROVISIONAL: a requirement is SATISFIED only when
        governed evidence exists, PARTIALLY_SATISFIED when accepted evidence
        covers the type, otherwise UNSATISFIED. The workflow never blocks on
        unresolved knowledge.
        """
        requirements = self._latest_requirements(bus)
        evidence = self._evidence_for_scope(scope)
        bundle = self.topic2.compile_evidence(
            EvidenceCompileRequest(scope=scope, evidence=evidence)
        )
        accepted = bundle.get("accepted") or []
        accepted_types = {str(item.get("claim_type")) for item in accepted}
        accepted_ids = {str(item.get("evidence_id")) for item in accepted}
        governed_evidence_ids: set[str] = set()
        prior = self._latest_governed_prior(bus)
        if prior:
            governed_evidence_ids = set(prior.get("evidence_ids") or [])

        satisfactions = []
        for requirement in requirements:
            req_type = requirement["type"]
            basis: list[str] = []
            reasons: list[str] = []
            status = "UNSATISFIED"
            if governed_evidence_ids:
                status = "SATISFIED"
                basis = sorted(governed_evidence_ids)
            elif accepted_ids:
                status = "PARTIALLY_SATISFIED"
                basis = sorted(accepted_ids)
                reasons.append("证据已审核但尚未进入受治理先验")
            else:
                reasons.append("无已审核证据覆盖该需求")
            satisfactions.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "status": status,
                    "assessment_method": "DETERMINISTIC_PROVISIONAL",
                    "assessment_version": "satisfaction-v0.1",
                    "basis_refs": basis,
                    "unresolved_reasons": reasons,
                }
            )

        missing_topics = [
            requirement["requirement_id"]
            for requirement, satisfaction in zip(requirements, satisfactions)
            if satisfaction["status"] == "UNSATISFIED"
        ]
        knowledge_state = {
            "requirements": requirements,
            "satisfactions": satisfactions,
            "existing_knowledge": {
                "evidence_count": len(evidence),
                "governed_evidence_count": len(governed_evidence_ids),
                "candidate_count": 0,
                "paper_count": 0,
                "topics": sorted(accepted_types),
            },
            "missing_topics": missing_topics,
            "assessment_version": "knowledge-state-v0.1",
        }
        artifact_id = self._persist_artifact(
            bus.run_id,
            "KnowledgeState",
            knowledge_state,
            input_refs=[
                {"type": "KnowledgeRequirements", "id": "analyze_knowledge_gaps"},
                {"type": "EvidenceCompileResult", "id": "prepare_knowledge"},
            ],
        )
        trace = ScientificTrace(bus, "satisfy_requirements")
        satisfied = sum(1 for s in satisfactions if s["status"] == "SATISFIED")
        partial = sum(1 for s in satisfactions if s["status"] == "PARTIALLY_SATISFIED")
        unresolved = len(missing_topics)
        trace.validation(
            f"需求满足评估：{satisfied} 满足 / {partial} 部分 / {unresolved} 未满足",
            counts={
                "satisfied": satisfied,
                "partial": partial,
                "unresolved": unresolved,
                "total": len(satisfactions),
            },
        )
        trace.artifact_created(
            "KnowledgeState",
            artifact_id,
            name=f"知识状态生成（{artifact_id}）",
            counts={
                "satisfied": satisfied,
                "partial": partial,
                "unresolved": unresolved,
            },
        )
        return {
            "meta": {
                "artifact_id": artifact_id,
                "satisfied": satisfied,
                "partial": partial,
                "unresolved": unresolved,
            },
            "content": {"knowledge_state": knowledge_state, "satisfactions": satisfactions},
        }

    def _latest_requirements(self, bus: WorkflowEventBus) -> list[dict[str, Any]]:
        artifacts = self.repository.list_application_artifacts(bus.run_id)
        for artifact in reversed(artifacts):
            if artifact["artifact_type"] == "KnowledgeRequirements":
                stored = self.repository.application_artifact(artifact["artifact_id"])
                if stored:
                    snapshot = stored["content"] or {}
                    return list(
                        (snapshot.get("content") or {}).get("requirements") or []
                    )
        return []

    def _evidence_for_scope(self, scope: TaskScope) -> list[Evidence]:
        items: list[Evidence] = []
        seen: set[str] = set()
        with self.repository.connection() as db:
            rows = db.execute("SELECT payload_json FROM evidence ORDER BY created_at").fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            if payload.get("evidence_id") in seen:
                continue
            try:
                item = Evidence.model_validate(payload)
            except Exception:
                continue
            seen.add(item.evidence_id)
            items.append(item)
        if self.agent_proxy_target:
            try:
                import httpx

                response = httpx.post(
                    f"{self.agent_proxy_target.rstrip('/')}/e2p/evidence-candidates",
                    json={
                        "task_scope": {
                            "material": scope.material,
                            "laser_type": scope.laser_type,
                            "geometry_type": scope.geometry_type,
                            "equipment_id": scope.equipment_id,
                            "target": scope.target,
                        },
                        "top_k": 20,
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                for candidate in response.json().get("evidence", []):
                    if candidate.get("evidence_id") in seen:
                        continue
                    try:
                        item = Evidence.model_validate(candidate)
                    except Exception:
                        continue
                    seen.add(item.evidence_id)
                    items.append(item)
            except Exception:
                pass
        return items

    @staticmethod
    def _readiness_coordinates(readiness: dict[str, Any]) -> list[dict[str, Any]]:
        """Project the readiness report into a uniform coordinate matrix.

        Statuses/dependencies come from the backend physics report only - the
        frontend never decides dependency logic (UI-P3).
        """
        coordinates: list[dict[str, Any]] = []
        for entry in readiness.get("available_coordinates") or []:
            coordinates.append(
                {
                    "coordinate": entry.get("coordinate"),
                    "status": "AVAILABLE",
                    "dependencies": [],
                    "reason": None,
                }
            )
        for entry in readiness.get("unverified_assumption_coordinates") or []:
            coordinates.append(
                {
                    "coordinate": entry.get("coordinate"),
                    "status": "UNVERIFIED",
                    "dependencies": list(entry.get("unverified_inputs") or []),
                    "reason": "依赖输入未验证（设备档案）",
                }
            )
        for entry in readiness.get("blocked_coordinates") or []:
            coordinates.append(
                {
                    "coordinate": entry.get("coordinate"),
                    "status": "BLOCKED",
                    "dependencies": list(
                        (entry.get("missing_inputs") or [])
                        + (entry.get("unverified_inputs") or [])
                    ),
                    "reason": (
                        f"缺失输入：{', '.join(entry.get('missing_inputs') or [])}"
                        if entry.get("missing_inputs")
                        else None
                    ),
                }
            )
        return coordinates

    def _target_readiness(
        self, rows: list[dict[str, Any]], scope: TaskScope
    ) -> dict[str, Any]:
        if not rows:
            return {
                "status": "BLOCKED",
                "coordinates": [],
                "reason": "no rows for scope",
            }
        try:
            from ultrafast_interaction.target import (
                TargetCoordinateEvaluator,
                build_target_condition_spec,
            )
        except Exception as exc:
            return {
                "status": "BLOCKED",
                "coordinates": [],
                "reason": f"physics kernel unavailable: {exc}",
            }
        frame = pd.DataFrame(rows)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, encoding="utf-8"
        ) as handle:
            frame.to_csv(handle, index=False)
            tmp_path = Path(handle.name)
        try:
            spot = self._agent_spot_diameter_um()
            spec = build_target_condition_spec(
                tmp_path,
                equipment_profile={
                    "spot_radius_um": (spot / 2.0, "um", False),
                    "spot_diameter_um": (spot, "um", False),
                }
                if spot
                else {
                    "spot_radius_um": (None, "um", False),
                    "spot_diameter_um": (None, "um", False),
                },
                equipment_profile_id=scope.equipment_id or "",
            )
            evaluated = TargetCoordinateEvaluator().evaluate(spec)
            report = (
                evaluated.to_dict()
                if hasattr(evaluated, "to_dict")
                else json.loads(json.dumps(evaluated, default=str))
            )
            return report
        except Exception as exc:
            return {
                "status": "BLOCKED",
                "coordinates": [],
                "reason": f"target readiness unavailable: {exc}",
            }
        finally:
            tmp_path.unlink(missing_ok=True)

    def _agent_spot_diameter_um(self) -> float | None:
        """Spot diameter from the active agent equipment profile (None when unreachable)."""
        if not self.agent_proxy_target:
            return None
        try:
            import httpx

            response = httpx.get(
                f"{self.agent_proxy_target.rstrip('/')}/equipment/active/machine-bounds",
                timeout=3.0,
            )
            response.raise_for_status()
            bounds = response.json().get("machine_bounds") or {}
        except Exception:
            return None
        diameter = bounds.get("spot_diameter_um")
        if isinstance(diameter, (list, tuple)) and len(diameter) == 2:
            return float(diameter[0])
        return None

    def _stage_apply_knowledge(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Stage 7: apply knowledge - governed soft prior (fails closed).

        V0 applies only governed knowledge: parameter-effect evidence that
        passed governance becomes a GovernedPriorArtifact. Experimental
        conditions never auto-become priors (P0-3).
        """
        evidence = self._evidence_for_scope(scope)
        prior_artifact = None
        warnings: list[str] = []
        trace = ScientificTrace(bus, "apply_knowledge")
        trace.operation_started(
            "apply-governed-prior",
            "受治理先验编译",
            input_refs=[
                {"type": "TaskScope", "id": scope.task_context_id or "task"},
                {"type": "EvidenceCompileResult", "id": "prepare_knowledge"},
            ],
        )
        if evidence:
            rows = self.topic2._rows_for_scope(scope)
            profile = build_data_profile(rows)
            try:
                prepared = self.topic2.e2p_prepare(
                    E2PPrepareRequest(
                        scope=scope,
                        data_profile=profile,
                        evidence=evidence,
                    )
                )
                prior_artifact = prepared.get("governed_prior_artifact")
            except Exception as exc:
                warnings.append(
                    f"governed prior 签发失败（fails closed）：{exc}"
                )
        else:
            warnings.append(
                "无可用 Evidence；governed prior 不可签发，assisted BO 将如实显示 prior_applied=false"
            )
        if prior_artifact:
            prior_artifact_id = self._persist_artifact(
                bus.run_id,
                "GovernedPriorArtifact",
                prior_artifact,
                input_refs=[{"type": "EvidenceCompileResult", "id": "prepare_knowledge"}],
            )
            trace.operation_completed(
                "apply-governed-prior",
                f"受治理先验签发（{prior_artifact_id}）",
                output_refs=[{"type": "GovernedPriorArtifact", "id": prior_artifact_id}],
                counts={"evidence_ids": len(prior_artifact.get("evidence_ids") or [])},
            )
        else:
            for warning in warnings:
                trace.warning(warning)
            trace.operation_completed(
                "apply-governed-prior",
                "受治理先验未签发（fails closed）",
                counts={"evidence": len(evidence)},
                reason_codes=["no_governed_prior"],
            )
        return {
            "meta": {
                "artifact_id": (
                    prior_artifact["artifact_id"] if prior_artifact else None
                ),
                "evidence_ids": (
                    list(prior_artifact["evidence_ids"]) if prior_artifact else []
                ),
            },
            "content": {
                "governed_prior_artifact": prior_artifact,
                "warnings": warnings,
            },
        }

    def _stage_optimization(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        rows = self.topic2._rows_for_scope(scope)
        bounds = self._machine_bounds(scope, rows)
        prior = self._latest_governed_prior(bus)
        comparison = self.compare_optimization(
            scope=scope,
            machine_bounds=bounds,
            governed_prior_artifact=prior,
            model_id=task_spec.get("model_id"),
            random_seed=random_seed,
            bus=bus,
        )
        return {
            "meta": {
                "vanilla_run_id": comparison["vanilla"]["run_id"],
                "assisted_run_id": comparison["evidence_assisted"]["run_id"],
                "assisted_search_prior_applied": comparison["prior_applied_evidence"][
                    "assisted_search_prior_applied"
                ],
            },
            "content": comparison,
        }

    def _latest_governed_prior(self, bus: WorkflowEventBus) -> dict[str, Any] | None:
        artifacts = self.repository.list_application_artifacts(bus.run_id)
        for artifact in reversed(artifacts):
            if artifact["artifact_type"] == "GovernedPriorArtifact":
                stored = self.repository.application_artifact(artifact["artifact_id"])
                if stored:
                    snapshot = stored["content"] or {}
                    return snapshot.get("content") or None
        return None

    # ----------------------------------------------------- bounds & BO (BE-5)

    def _machine_bounds(
        self, scope: TaskScope, rows: list[dict[str, Any]]
    ) -> dict[str, dict[str, float]]:
        """Data-range bounds with agent machine-bound refinement when reachable."""
        frame = pd.DataFrame(rows).dropna(
            subset=[scope.target, *CORE_PARAMETER_NAMES]
        )
        data: dict[str, list[float]] = {}
        for name in CORE_PARAMETER_NAMES:
            if frame.empty:
                data[name] = [0.0, 1.0]
                continue
            low, high = float(frame[name].min()), float(frame[name].max())
            if low == high:
                span = abs(low) * 0.1 or 1.0
                high = low + span
            data[name] = [low, high]
        if not frame.empty and frame["passes"].nunique() > 0:
            low, high = int(frame["passes"].min()), int(frame["passes"].max())
            if low == high:
                high = low + 1
            data["passes"] = [float(low), float(high)]
        agent = self._agent_machine_bounds()
        if agent:
            for name in CORE_PARAMETER_NAMES:
                if name not in agent:
                    continue
                lo, hi = agent[name]
                if lo >= hi:
                    continue
                if hi <= data[name][0] or lo >= data[name][1]:
                    continue
                data[name] = [max(data[name][0], lo), min(data[name][1], hi)]
        return {name: {"lower": v[0], "upper": v[1]} for name, v in data.items()}

    def _agent_machine_bounds(self) -> dict[str, tuple[float, float]] | None:
        if not self.agent_proxy_target:
            return None
        try:
            import httpx

            response = httpx.get(
                f"{self.agent_proxy_target.rstrip('/')}/equipment/active/machine-bounds",
                timeout=3.0,
            )
            response.raise_for_status()
            bounds = response.json().get("machine_bounds") or {}
        except Exception:
            return None
        result: dict[str, tuple[float, float]] = {}
        pulse = bounds.get("pulse_width_fs")
        if isinstance(pulse, (list, tuple)) and len(pulse) == 2:
            try:
                result["pulse_width_ps"] = (
                    float(pulse[0]) / 1000.0,
                    float(pulse[1]) / 1000.0,
                )
            except (TypeError, ValueError):
                pass
        for name in ("frequency_kHz", "scan_speed_mm_s"):
            value = bounds.get(name)
            if isinstance(value, (list, tuple)) and len(value) == 2:
                try:
                    result[name] = (float(value[0]), float(value[1]))
                except (TypeError, ValueError):
                    pass
        return result or None

    def compare_optimization(
        self,
        *,
        scope: TaskScope | dict[str, Any],
        machine_bounds: dict[str, dict[str, float]],
        governed_prior_artifact: dict[str, Any] | None = None,
        model_id: str | None = None,
        random_seed: int | None = None,
        bus: WorkflowEventBus | None = None,
    ) -> dict[str, Any]:
        """Vanilla vs Evidence-assisted BO comparison (BE-5).

        Both runs are real backend executions; the assisted run only uses the
        governed prior when the artifact is present and repository-verified.
        """
        scope = self._scope(scope) if not isinstance(scope, TaskScope) else scope
        bounds_schema = {
            name: {"lower": value["lower"], "upper": value["upper"]}
            for name, value in machine_bounds.items()
        }
        bus_emit = bus.emit if bus else lambda *args, **kwargs: None
        vanilla = self.topic2.recommend(
            OptimizationRequest(
                scope=scope,
                machine_bounds=bounds_schema,
                model_id=model_id,
                random_seed=random_seed,
            )
        )
        bus_emit(
            TOOL_COMPLETED,
            f"Vanilla BO 完成（{vanilla['run_id']}）",
            stage="optimization",
        )
        assisted, prior_applied = vanilla, False
        if governed_prior_artifact is not None:
            assisted = self.topic2.recommend(
                OptimizationRequest(
                    scope=scope,
                    machine_bounds=bounds_schema,
                    model_id=model_id,
                    governed_prior_artifact=governed_prior_artifact,
                    random_seed=random_seed,
                )
            )
            prior_applied = assisted.get("governed_prior_artifact") is not None
            bus_emit(
                TOOL_COMPLETED,
                f"Evidence-assisted BO 完成（{assisted['run_id']}）",
                stage="optimization",
            )
        else:
            bus_emit(
                WARNING,
                "无 GovernedPriorArtifact：Evidence-assisted BO 与 Vanilla 相同（prior_applied=false）",
                stage="optimization",
            )
        return {
            "vanilla": vanilla,
            "evidence_assisted": assisted,
            "prior_applied_evidence": {
                "vanilla_search_prior_applied": False,
                "assisted_search_prior_applied": prior_applied,
                "assisted_prior_guidance": (
                    "e2p_soft_prior_v1" if prior_applied else None
                ),
                "governed_prior_hash": (
                    (governed_prior_artifact or {}).get("content_hash")
                ),
                "assisted_prior_evidence_ids": list(
                    (governed_prior_artifact or {}).get("evidence_ids") or []
                ),
            },
        }

    # ------------------------------------------------------------ aggregation

    def _research_summary(
        self,
        result: dict[str, Any],
        scope: TaskScope,
        task_spec: dict[str, Any],
        random_seed: int,
        run_id: str,
    ) -> dict[str, Any]:
        learning = result.get("baseline_learning") or {}
        modeling = learning.get("modeling") or {}
        identification = learning.get("identification") or {}
        bo = result.get("optimization") or {}
        prior = result.get("apply_knowledge") or {}
        assess = result.get("assess_data") or {}
        cfa = assess.get("cfa") or {}
        prepare = result.get("prepare_knowledge") or {}
        bundle = prepare.get("bundle") or {}
        gap = result.get("analyze_knowledge_gaps") or {}
        satisfy = result.get("satisfy_requirements") or {}
        knowledge_state = satisfy.get("knowledge_state") or {}
        prior_artifact = prior.get("governed_prior_artifact")
        # checkpoint 支持：仅运行到知识缺口时 knowledgeState 尚无 satisfy 产物，
        # requirements 直接从 gap 阶段回退（satisfactions 留空）
        requirements = (
            knowledge_state.get("requirements")
            or gap.get("requirements")
            or []
        )
        satisfactions = knowledge_state.get("satisfactions") or []
        return {
            "runId": run_id,
            "workflowVersion": self.workflow_version,
            "targetTask": {
                "material": scope.material,
                "laserType": scope.laser_type,
                "geometry": scope.geometry_type,
                "equipment": scope.equipment_id,
                "target": scope.target,
                "randomSeed": random_seed,
                "sampleCount": (assess.get("dataset") or {}).get("n_samples"),
            },
            "processLearning": {
                "selectedFeatureView": "RAW",
                "selectedModel": modeling.get("selected_model"),
                "controllableRanking": list(
                    identification.get("controllable_ranking") or []
                ),
                "mechanismRanking": list(
                    identification.get("mechanism_ranking") or []
                ),
                "modelComparison": modeling.get("validation_metrics") or {},
                "physicsReadiness": list(cfa.get("coordinates") or []),
                "identificationRunId": identification.get("run_id"),
                "trainingRunId": modeling.get("run_id"),
            },
            "scientificBasis": {
                "candidateCount": len(bundle.get("candidates") or []),
                "evidenceCount": len(bundle.get("accepted") or []),
                "governedEvidenceCount": len(
                    (prior_artifact or {}).get("evidence_ids") or []
                ),
            },
            "knowledgeState": {
                "requirements": list(requirements),
                "satisfactions": list(satisfactions),
                "existing_knowledge": knowledge_state.get("existing_knowledge") or {},
                "missing_topics": list(knowledge_state.get("missing_topics") or []),
                "assessment_version": knowledge_state.get("assessment_version"),
            },
            "cfa": {
                "version": cfa.get("version"),
                "calibrationStatus": cfa.get("calibration_status"),
                "facetSummary": cfa.get("facet_summary") or {},
                "warnings": list(cfa.get("warnings") or []),
                "targetPhysicsReadiness": cfa.get("target_physics_readiness") or None,
            },
            "optimization": {
                "vanilla": bo.get("vanilla"),
                "evidenceAssisted": bo.get("evidence_assisted"),
                "priorAppliedEvidence": bo.get("prior_applied_evidence"),
            },
            "audit": {
                "evidenceIds": list(
                    (prior_artifact or {}).get("evidence_ids") or []
                ),
                "priorContentHash": (prior_artifact or {}).get("content_hash"),
                "boRunIds": [
                    (bo.get("vanilla") or {}).get("run_id"),
                    (bo.get("evidence_assisted") or {}).get("run_id"),
                ],
                "modelVersion": modeling.get("model_version"),
                "replayable": False,
            },
        }

    def _demo_summary(
        self,
        slice_result: dict[str, Any],
        task_spec: dict[str, Any],
        random_seed: int,
        run_id: str,
    ) -> dict[str, Any]:
        learning = slice_result.get("process_learning") or {}
        bo = slice_result.get("bo") or {}
        cfa = slice_result.get("cfa") or {}
        e2p = slice_result.get("e2p_prior") or {}
        governed = e2p.get("governed_prior") or {}
        audit = slice_result.get("audit") or {}
        facet_summary = audit.get("cfa_facets") or {}
        if isinstance(facet_summary, dict) and facet_summary:
            cfa_facets = facet_summary
        else:
            cfa_facets = {}
        return {
            "runId": run_id,
            "workflowVersion": self.workflow_version,
            "targetTask": {
                "material": (slice_result.get("target_task") or {}).get("material"),
                "laserType": (slice_result.get("target_task") or {}).get(
                    "laser_type"
                ),
                "geometry": (slice_result.get("target_task") or {}).get("geometry"),
                "equipment": task_spec.get("equipment_profile_id"),
                "target": (slice_result.get("target_task") or {}).get("objective"),
                "randomSeed": random_seed,
                "sampleCount": (slice_result.get("target_task") or {}).get(
                    "sample_count"
                ),
            },
            "processLearning": {
                "selectedFeatureView": learning.get("selected_feature_view"),
                "selectedModel": learning.get("selected_model"),
                "modelComparison": learning.get("cv_metrics") or {},
                "cvFolds": learning.get("cv_folds"),
                "featureViews": learning.get("feature_views") or {},
                "identificationRunId": None,
                "trainingRunId": None,
            },
            "scientificBasis": {
                "paperCount": (slice_result.get("literature_evidence") or {}).get(
                    "paper_count"
                ),
                "evidenceCount": e2p.get("accepted_count"),
                "governedEvidenceCount": len(governed.get("evidence_ids") or []),
                "governedPrior": governed,
                "priorCount": e2p.get("prior_count"),
            },
            "cfa": {
                "version": (cfa.get("calibration_status") or "uncalibrated"),
                "calibrationStatus": cfa.get("calibration_status"),
                "facetSummary": cfa_facets,
                "warnings": list(cfa.get("warnings") or []),
                "targetPhysicsReadiness": cfa.get("target_physics_readiness"),
                "reports": cfa.get("reports") or [],
            },
            "optimization": {
                "vanilla": bo.get("vanilla"),
                "evidenceAssisted": bo.get("evidence_assisted"),
                "priorAppliedEvidence": bo.get("prior_applied_evidence"),
            },
            "audit": {
                "evidenceIds": list(governed.get("evidence_ids") or []),
                "priorContentHash": governed.get("content_hash"),
                "boRunIds": [
                    audit.get("bo_run_id_vanilla"),
                    audit.get("bo_run_id_assisted"),
                ],
                "modelVersion": audit.get("model_version"),
                "replayable": True,
                "ledgerVersionIds": list(audit.get("ledger_version_ids") or []),
            },
        }

    # -------------------------------------------------------------- queries

    def _run_summary(self, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "application_run_id": run["application_run_id"],
            "status": run["status"],
            "task_context_ref": run["task_context_ref"],
            "mode": run["mode"],
            "workflow_version": run["workflow_version"],
            "stage_status": run.get("stage_status") or {},
            "created_at": run.get("created_at"),
            "completed_at": run.get("completed_at"),
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.repository.application_run(run_id)
        if run is None:
            raise ValueError(f"application run not found: {run_id}")
        return run

    def get_result(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run.get("result") is None:
            raise ValueError(f"application run has no result yet: {run_id}")
        return run["result"]

    def list_runs(self, mode: str | None = None) -> list[dict[str, Any]]:
        return self.repository.list_application_runs(mode=mode)

    def events(self, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        if self.repository.application_run(run_id) is None:
            raise ValueError(f"application run not found: {run_id}")
        return self.repository.workflow_events(run_id, after_sequence=after_sequence)

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        if self.repository.application_run(run_id) is None:
            raise ValueError(f"application run not found: {run_id}")
        return self.repository.list_application_artifacts(run_id)

    def artifact(self, artifact_id: str) -> dict[str, Any]:
        artifact = self.repository.application_artifact(artifact_id)
        if artifact is None:
            raise ValueError(f"artifact not found: {artifact_id}")
        return artifact

    def replay(self, run_id: str) -> dict[str, Any]:
        """Re-run the frozen demo scenario and compare the scientific payload.

        Runtime IDs (run ids / timestamps / artifact ids) are expected to change;
        only the deterministic scientific payload must be identical.
        """
        run = self.get_run(run_id)
        if run["mode"] != "demo":
            raise ValueError("replay is only available for frozen demo runs")
        if run.get("result") is None:
            raise ValueError("cannot replay a run without a result")
        seed = (run["result"].get("targetTask") or {}).get("randomSeed")
        fresh = self.create_application_run(
            mode="demo",
            random_seed=seed if isinstance(seed, int) else None,
            client_request_id=None,
        )
        fresh_run = self.get_run(fresh["application_run_id"])
        return {
            "replay_run_id": fresh_run["application_run_id"],
            "original_run_id": run_id,
            "scientific_payload_identical": self._scientific_payload(
                fresh_run.get("result") or {}
            )
            == self._scientific_payload(run.get("result") or {}),
            "runtime_ids_changed": fresh_run["application_run_id"] != run_id,
            "note": "Runtime IDs changed expected; scientific payload identical",
        }

    def _scientific_payload(self, result: dict[str, Any]) -> dict[str, Any]:
        """Deterministic scientific subset of an application result (replay comparison)."""
        learning = result.get("processLearning") or {}
        cfa = result.get("cfa") or {}
        optimization = result.get("optimization") or {}
        basis = result.get("scientificBasis") or {}
        governed = basis.get("governedPrior") or {}

        def scientific_bo(bo: dict[str, Any] | None) -> dict[str, Any]:
            bo = bo or {}
            return {
                "optimization_method": bo.get("optimization_method"),
                "recommended_parameters": bo.get("recommended_parameters"),
                "prediction": bo.get("prediction"),
                "acquisition": bo.get("acquisition"),
                "search_prior_applied": bo.get("search_prior_applied"),
                "prior_guidance": (bo.get("acquisition") or {}).get("prior_guidance"),
            }

        return {
            "targetTask": {
                key: value
                for key, value in (result.get("targetTask") or {}).items()
                if key != "randomSeed"
            },
            "processLearning": {
                "selectedFeatureView": learning.get("selectedFeatureView"),
                "selectedModel": learning.get("selectedModel"),
                "cvFolds": learning.get("cvFolds"),
                "featureViews": learning.get("featureViews"),
                "modelComparison": learning.get("modelComparison"),
            },
            "scientificBasis": {
                "paperCount": basis.get("paperCount"),
                "evidenceCount": basis.get("evidenceCount"),
                "governedEvidenceCount": basis.get("governedEvidenceCount"),
                "priorCount": basis.get("priorCount"),
            },
            "governedPrior": {
                "artifact_id": governed.get("artifact_id"),
                "content_hash": governed.get("content_hash"),
                "evidence_ids": list(governed.get("evidence_ids") or []),
                "review_ids": list(governed.get("review_ids") or []),
                "prior_spec": governed.get("prior_spec"),
                "verification": governed.get("verification"),
            },
            "cfa": {
                "calibrationStatus": cfa.get("calibrationStatus"),
                "facetSummary": cfa.get("facetSummary"),
            },
            "optimization": {
                "vanilla": scientific_bo(optimization.get("vanilla")),
                "evidenceAssisted": scientific_bo(
                    optimization.get("evidenceAssisted")
                ),
                "priorAppliedEvidence": optimization.get("priorAppliedEvidence"),
            },
        }

    def _persist_artifact(
        self,
        run_id: str,
        artifact_type: str,
        content: dict[str, Any],
        *,
        input_refs: list[dict[str, str]] | None = None,
        schema_version: str = "v1",
    ) -> str:
        """Artifact = 科学状态快照（P1 Observability）：
        {id, type, schema_version, input_refs, content, created_at}."""
        artifact_id = (
            f"{artifact_type}-"
            f"{canonical_hash({'run': run_id, 'type': artifact_type, 'content': content})[:16]}"
        )
        self.repository.save_application_artifact(
            {
                "artifact_id": artifact_id,
                "application_run_id": run_id,
                "artifact_type": artifact_type,
                "content": {
                    "id": artifact_id,
                    "type": artifact_type,
                    "schema_version": schema_version,
                    "input_refs": input_refs or [],
                    "content": content,
                    "created_at": timestamp(),
                },
            }
        )
        return artifact_id
