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
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

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
from packages.e2p.application.typed_prior_compiler import compile_typed_priors
from packages.e2p.domain.prior_objects import (
    MechanismModelPrior,
    ParameterPrior,
    PlanningPreferencePrior,
    PriorObjectSet,
)
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
from packages.scientific_computation.canonicalization import PhysicsCanonicalizer
from packages.scientific_computation.capability import ScientificCapabilityAnalyzer
from packages.scientific_computation.contracts import (
    ArtifactRef,
    CalibrationResult,
    ConstraintValue,
    EvidenceOrigin,
    LocalRemovalModel,
    ObservationMeasurement,
    ObservationResult,
    PathFamily,
    PhysicalModelState,
    ProcessCorrectionInterface,
    ProvenanceRecord,
    RemovalKernel,
    RemovalModelMode,
    ScientificStatus,
    SimulationFidelity,
    TargetGeometry,
)
from packages.scientific_computation.identification import ParameterIdentificationEngine
from packages.scientific_computation.local_removal import LocalRemovalModelFactory
from packages.scientific_computation.planning import ToolpathPlanner
from packages.scientific_retrieval.planner import plan_retrieval

WORKFLOW_VERSION = "physics-to-planning-application-v1"
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

# Physics-to-Planning V1 canonical ApplicationRun.  Legacy BO remains a
# compatibility output inside plan_process, not a parallel workflow.
ALL_STAGES = (
    "prepare_task",
    "assess_capability",
    "assess_data",
    "baseline_learning",
    "analyze_knowledge_requirements",
    "prepare_knowledge",
    "satisfy_requirements",
    "calibrate_physics",
    "establish_process_model",
    "plan_process",
)
OPTIONAL_STAGES = ("evaluate_observation",)

STAGE_LABELS = {
    "prepare_task": "任务准备",
    "assess_capability": "科学能力预检",
    "assess_data": "数据与物理就绪评估",
    "baseline_learning": "基线过程学习（RAW）",
    "analyze_knowledge_requirements": "计算缺口驱动的知识需求",
    "prepare_knowledge": "知识准备（文献/证据）",
    "satisfy_requirements": "需求满足评估",
    "calibrate_physics": "E2P Prior 与物理参数标定",
    "establish_process_model": "局部去除模型与物理状态",
    "plan_process": "形貌仿真驱动的路径规划",
    "evaluate_observation": "实验观察与闭环更新意图",
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
        unknown = set(requested_stages).difference((*ALL_STAGES, *OPTIONAL_STAGES))
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
        if stages is None and task_spec.get("observation"):
            requested_stages.append("evaluate_observation")

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
        except Exception as exc:
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

    # 两段式入口：先运行到能力/知识需求，检查 Requirement 后续跑物理与规划。
    GAP_STAGES = (
        "prepare_task",
        "assess_capability",
        "assess_data",
        "baseline_learning",
        "analyze_knowledge_requirements",
    )
    KNOWLEDGE_STAGES = (
        "prepare_knowledge",
        "satisfy_requirements",
        "calibrate_physics",
        "establish_process_model",
        "plan_process",
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
            else [
                stage
                for stage in (
                    *ALL_STAGES,
                    *(OPTIONAL_STAGES if task_spec.get("observation") else ()),
                )
                if stage not in completed
            ]
        )
        unknown = set(requested).difference((*ALL_STAGES, *OPTIONAL_STAGES))
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
        except Exception as exc:
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
            from ultrafast_ingestion.mentions.extractor import extract_mentions
            from ultrafast_ingestion.tables.models import table_regions

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
        task_state = {
            "schema_version": "task-state-v1",
            "task_scope": scope.model_dump(mode="json"),
            "target_geometry": task_spec.get("target_geometry") or {
                "geometry_type": scope.geometry_type,
            },
            "machine_profile": task_spec.get("machine_profile") or {},
            "random_seed": random_seed,
            "capability_summary": capability,
        }
        artifact_id = self._persist_artifact(
            bus.run_id,
            "TaskState",
            task_state,
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
            schema_version="task-state-v1",
        )
        ScientificTrace(bus, "prepare_task").artifact_created(
            "TaskState", artifact_id, counts={"n_samples": capability["n_samples"]}
        )
        return {"meta": {**meta, "artifact_id": artifact_id}, "content": task_state}

    def _stage_assess_capability(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Downstream-computation-driven preflight; never calls retrieval."""
        trace = ScientificTrace(bus, "assess_capability")
        task_state_id = self._latest_artifact_id(bus, "TaskState")
        trace.operation_started(
            "scientific-capability-preflight",
            "科学计算能力与依赖预检",
            input_refs=[{"type": "TaskState", "id": task_state_id}],
        )
        rows = self.topic2._rows_for_scope(scope)
        report = ScientificCapabilityAnalyzer().analyze(
            task={
                **scope.model_dump(mode="json"),
                "process_parameters": task_spec.get("process_parameters") or scope.process_parameters,
                "device_properties": task_spec.get("device_properties") or scope.device_properties,
            },
            data_rows=rows,
            machine_profile=dict(task_spec.get("machine_profile") or {}),
            knowledge_state={},
            input_refs=[ArtifactRef(type="TaskState", id=task_state_id)],
        )
        content = report.model_dump(mode="json")
        artifact_id = self._persist_artifact(
            bus.run_id,
            "ScientificCapabilityReport",
            content,
            input_refs=[{"type": "TaskState", "id": task_state_id}],
            schema_version=report.schema_version,
        )
        trace.operation_completed(
            "scientific-capability-preflight",
            f"能力预检完成（{artifact_id}）",
            output_refs=[{"type": "ScientificCapabilityReport", "id": artifact_id}],
            counts={
                "available": len(report.available),
                "missing": len(report.missing),
                "requirements": len(report.recommended_requirements),
            },
            reason_codes=report.reason_codes,
        )
        trace.artifact_created(
            "ScientificCapabilityReport",
            artifact_id,
            input_refs=[{"type": "TaskState", "id": task_state_id}],
        )
        return {
            "meta": {
                "artifact_id": artifact_id,
                "simulation_supported": report.simulation_supported,
                "requirement_count": len(report.recommended_requirements),
            },
            "content": content,
        }

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

    def _stage_analyze_knowledge_requirements(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Capability/computation gaps -> canonical KnowledgeRequirementSet.

        LLM questions may be added later, but downstream computation gaps own
        priority and provenance in V1.
        """
        trace = ScientificTrace(bus, "analyze_knowledge_requirements")
        trace.operation_started(
            "requirement-compilation",
            "计算缺口驱动的知识需求编译",
            input_refs=[
                {
                    "type": "ScientificCapabilityReport",
                    "id": self._latest_artifact_id(bus, "ScientificCapabilityReport"),
                }
            ],
        )
        capability = self._latest_artifact_content(bus, "ScientificCapabilityReport") or {}
        capability_requirements = list(capability.get("recommended_requirements") or [])
        requirements: list[dict[str, Any]] = []
        for item in capability_requirements:
            normalized = dict(item)
            question = normalized.get("scientific_question") or normalized.get("question")
            normalized["scientific_question"] = question
            normalized["question"] = question
            normalized.setdefault("satisfaction_criteria", [])
            normalized.setdefault("status", "UNKNOWN")
            normalized.setdefault("provenance", [])
            requirements.append(normalized)

        # Preserve the proven P0 learning/planning questions as lower-priority
        # supplemental requirements; they do not displace computation gaps.
        existing_types = {str(item.get("type")) for item in requirements}
        for item in self._knowledge_requirements(scope, bus):
            if item["type"] == "threshold" and "PARAMETER_PRIOR" in existing_types:
                continue
            next_id = f"KR-{len(requirements) + 1:03d}"
            requirements.append(
                {
                    **item,
                    "requirement_id": next_id,
                    "scientific_question": item["question"],
                    "satisfaction_criteria": [],
                    "status": "UNKNOWN",
                    "provenance": [
                        {
                            "type": "ScientificCapabilityReport",
                            "id": self._latest_artifact_id(bus, "ScientificCapabilityReport"),
                        }
                    ],
                }
            )
        diagnostics = self._knowledge_diagnostics(scope)
        trace.validation(
            f"知识需求：{len(requirements)} 条（{len(diagnostics['missing_inputs'])} 项物理输入缺失）",
            counts={
                "requirements": len(requirements),
                "missing_inputs": len(diagnostics["missing_inputs"]),
                "blocked_coordinates": len(diagnostics["blocked_coordinates"]),
            },
        )
        capability_ref = self._latest_artifact_id(bus, "ScientificCapabilityReport")
        artifact_id = self._persist_artifact(
            bus.run_id,
            "KnowledgeRequirementSet",
            {"requirements": requirements, "diagnostics": diagnostics},
            input_refs=[
                {"type": "ScientificCapabilityReport", "id": capability_ref},
                {"type": "DataProfile", "id": self._latest_artifact_id(bus, "DataProfile")},
            ],
            schema_version="knowledge-requirement-set-v1",
        )
        # Compatibility alias for existing Inspector/API consumers.  It points
        # to the canonical set instead of recomputing a second requirement set.
        legacy_artifact_id = self._persist_artifact(
            bus.run_id,
            "KnowledgeRequirements",
            {"requirements": requirements, "diagnostics": diagnostics},
            input_refs=[{"type": "KnowledgeRequirementSet", "id": artifact_id}],
            schema_version="knowledge-requirement-set-v1-compat",
        )
        trace.operation_completed(
            "requirement-compilation",
            f"知识需求清单生成（{artifact_id}）",
            output_refs=[{"type": "KnowledgeRequirementSet", "id": artifact_id}],
            counts={"requirements": len(requirements)},
        )
        trace.artifact_created(
            "KnowledgeRequirementSet",
            artifact_id,
            input_refs=[{"type": "ScientificCapabilityReport", "id": capability_ref}],
        )
        return {
            "meta": {
                "artifact_id": artifact_id,
                "compatibility_artifact_id": legacy_artifact_id,
                "requirement_count": len(requirements),
            },
            "content": {"requirements": requirements, "diagnostics": diagnostics},
        }

    # Explicit migration alias for stored/legacy callers.  It is not part of
    # the canonical ALL_STAGES list and creates the same artifacts.
    def _stage_analyze_knowledge_gaps(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        return self._stage_analyze_knowledge_requirements(
            task_spec, scope, bus, random_seed
        )

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

    # requirement type -> acceptable Evidence claim_type roles (V0 coverage map).
    # 一条证据只满足与其 claim_type 匹配的需求（requirement-specific coverage）。
    REQUIREMENT_EVIDENCE_ROLES: ClassVar[dict[str, tuple[str, ...]]] = {
        "threshold": ("threshold", "material_property"),
        "parameter_effect": ("parameter_direction", "range_preference"),
        "reported_optimum": ("range_preference",),
        "material_property": ("range_preference",),
        "physics_dependency": ("range_preference",),
        "process_mechanism": ("functional_shape",),
        "formula": ("functional_shape",),
        "experimental_condition": ("historical_dataset", "range_preference"),
        "parameter_range": ("range_preference",),
        "data_quality": (),  # 文献无法满足：由实验数据决定，恒 UNSATISFIED
        "PARAMETER_PRIOR": ("threshold", "material_property", "parameter_prior"),
        "MECHANISM_MODEL": ("mechanism_model", "formula", "functional_shape"),
        "PHYSICS_DEPENDENCY": ("experimental_condition", "historical_dataset"),
        "INTERACTION_MECHANISM": ("mechanism_model", "functional_shape"),
        "PARAMETER_EFFECT": ("parameter_direction", "range_preference"),
        "MODEL_VALIDATION": ("external_validation_case", "historical_dataset"),
        "EXTERNAL_VALIDATION_CASE": ("external_validation_case",),
        "PATH_STRATEGY": ("path_strategy",),
        "OTHER": (),
    }

    def _knowledge_requirements(
        self, scope: TaskScope, bus: WorkflowEventBus
    ) -> list[dict[str, Any]]:
        """Rules over real diagnostics -> KnowledgeRequirement[].

        V0 is deliberately simple: every requirement carries trigger_reasons
        that point at the diagnostic evidence behind it, plus
        required_evidence_roles for requirement-specific satisfaction.
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
                    "required_evidence_roles": list(
                        self.REQUIREMENT_EVIDENCE_ROLES.get(type_, ())
                    ),
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
        requirements = self._latest_requirements(bus)
        query_plans = [
            plan_retrieval(requirement, scope.model_dump(mode="json")).model_dump(mode="json")
            for requirement in requirements
        ]
        query_plan_artifact = self._persist_artifact(
            bus.run_id,
            "LiteratureRetrievalQueryPlan",
            {
                "schema_version": "requirement-retrieval-v1",
                "plans": query_plans,
                "geometry_policy": "SOFT_RANKING_HINT_ONLY",
            },
            input_refs=[
                {
                    "type": "KnowledgeRequirementSet",
                    "id": self._latest_artifact_id(bus, "KnowledgeRequirementSet"),
                }
            ],
            schema_version="requirement-retrieval-v1",
        )
        trace.artifact_created(
            "LiteratureRetrievalQueryPlan",
            query_plan_artifact,
            counts={"requirements": len(requirements), "query_plans": len(query_plans)},
        )
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
        evidence_ir = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in evidence
        ]
        evidence_ir.extend(
            dict(item) for item in (task_spec.get("evidence_ir") or [])
        )
        evidence_ir_artifact = self._persist_artifact(
            bus.run_id,
            "EvidenceIRSet",
            {
                "schema_version": "evidence-ir-set-v1",
                "items": evidence_ir,
                "query_plan_ref": query_plan_artifact,
            },
            input_refs=[
                {"type": "LiteratureRetrievalQueryPlan", "id": query_plan_artifact},
                {"type": "EvidenceCompileResult", "id": artifact_id},
            ],
            schema_version="evidence-ir-set-v1",
        )
        trace.artifact_created(
            "EvidenceIRSet",
            evidence_ir_artifact,
            input_refs=[
                {"type": "LiteratureRetrievalQueryPlan", "id": query_plan_artifact}
            ],
            counts={"evidence": len(evidence_ir)},
        )
        return {
            "meta": {
                "artifact_id": artifact_id,
                "query_plan_artifact_id": query_plan_artifact,
                "evidence_ir_artifact_id": evidence_ir_artifact,
                "evidence_count": accepted_count,
            },
            "content": {
                "bundle": bundle,
                "query_plans": query_plans,
                "evidence_ir": evidence_ir,
                "evidence_count": len(evidence),
                "existing_knowledge": existing,
            },
        }

    def _stage_satisfy_requirements(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Stage 6: requirement-specific satisfaction -> KnowledgeState.

        V0 uses DETERMINISTIC_PROVISIONAL with requirement-specific coverage:
        an evidence only satisfies requirements whose required_evidence_roles
        contain its claim_type. A single parameter_effect evidence therefore
        never satisfies a threshold requirement. SATISFIED requires governed
        evidence, PARTIALLY_SATISFIED requires accepted evidence, data_quality
        can never be satisfied by literature. The workflow never blocks.
        """
        requirements = self._latest_requirements(bus)
        evidence = self._evidence_for_scope(scope)
        bundle = self.topic2.compile_evidence(
            EvidenceCompileRequest(scope=scope, evidence=evidence)
        )
        accepted = bundle.get("accepted") or []
        accepted_by_claim_type: dict[str, set[str]] = {}
        for item in accepted:
            claim_type = str(item.get("claim_type") or "")
            accepted_by_claim_type.setdefault(claim_type, set()).add(
                str(item.get("evidence_id"))
            )
        accepted_types = {str(item.get("claim_type")) for item in accepted}
        governed_evidence_ids: set[str] = set()
        prior = self._latest_governed_prior(bus)
        governed_by_claim_type: dict[str, set[str]] = {}
        if prior:
            for evidence_id in prior.get("evidence_ids") or []:
                governed_evidence_ids.add(str(evidence_id))
        if governed_evidence_ids:
            # governed 证据同样按 claim_type 归类（来自同批 evidence）
            for item in accepted:
                if str(item.get("evidence_id")) in governed_evidence_ids:
                    claim_type = str(item.get("claim_type") or "")
                    governed_by_claim_type.setdefault(claim_type, set()).add(
                        str(item.get("evidence_id"))
                    )

        satisfactions = []
        for requirement in requirements:
            roles = requirement.get("required_evidence_roles") or []
            basis: list[str] = []
            reasons: list[str] = []
            if not roles:
                # 文献不可满足的需求（如 data_quality）：如实 UNSATISFIED
                reasons.append("该需求由实验数据决定，文献无法满足")
                status = "UNSATISFIED"
            else:
                covered_governed: set[str] = set()
                covered_accepted: set[str] = set()
                for role in roles:
                    covered_governed.update(governed_by_claim_type.get(role, set()))
                    covered_accepted.update(accepted_by_claim_type.get(role, set()))
                if covered_governed:
                    status = "SATISFIED"
                    basis = sorted(covered_governed)
                elif covered_accepted:
                    status = "PARTIALLY_SATISFIED"
                    basis = sorted(covered_accepted)
                    reasons.append("存在匹配证据但尚未进入受治理先验")
                else:
                    status = "UNSATISFIED"
                    reasons.append(
                        f"无匹配证据（需要 claim_type ∈ {roles}，现有 accepted claim_types ∈ {sorted(accepted_types) or '∅'}）"
                    )
            satisfactions.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "status": status,
                    "assessment_method": "DETERMINISTIC_PROVISIONAL",
                    "assessment_version": "satisfaction-v0.2",
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
                {
                    "type": "KnowledgeRequirementSet",
                    "id": self._latest_artifact_id(bus, "KnowledgeRequirementSet"),
                },
                {
                    "type": "EvidenceCompileResult",
                    "id": self._latest_artifact_id(bus, "EvidenceCompileResult"),
                },
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
        for expected_type in ("KnowledgeRequirementSet", "KnowledgeRequirements"):
            for artifact in reversed(artifacts):
                if artifact["artifact_type"] == expected_type:
                    stored = self.repository.application_artifact(artifact["artifact_id"])
                    if stored:
                        snapshot = stored["content"] or {}
                        return list(
                            (snapshot.get("content") or {}).get("requirements") or []
                        )
        return []

    def _latest_artifact_id(
        self, bus: WorkflowEventBus, artifact_type: str
    ) -> str:
        """Real artifact ID of the most recent artifact of a type (provenance).

        Stage names are never used as provenance IDs - the DAG must reference
        actual artifact UUIDs so every input is traceable.
        """
        artifacts = self.repository.list_application_artifacts(bus.run_id)
        for artifact in reversed(artifacts):
            if artifact["artifact_type"] == artifact_type:
                return artifact["artifact_id"]
        return f"{artifact_type}-unavailable"

    def _latest_artifact_id_for_run(self, run_id: str, artifact_type: str) -> str | None:
        for artifact in reversed(self.repository.list_application_artifacts(run_id)):
            if artifact["artifact_type"] == artifact_type:
                return str(artifact["artifact_id"])
        return None

    def _latest_artifact_content(
        self, bus: WorkflowEventBus, artifact_type: str
    ) -> dict[str, Any] | None:
        artifact_id = self._latest_artifact_id(bus, artifact_type)
        if artifact_id.endswith("-unavailable"):
            return None
        stored = self.repository.application_artifact(artifact_id)
        if stored is None:
            return None
        snapshot = stored.get("content") or {}
        content = snapshot.get("content")
        return dict(content) if isinstance(content, dict) else None

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

    def _stage_calibrate_physics(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """E2P typed Prior compilation followed by independent parameter ID."""
        trace = ScientificTrace(bus, "calibrate_physics")
        rows = self.topic2._rows_for_scope(scope)
        machine = {
            **dict(scope.device_properties or {}),
            **dict(task_spec.get("machine_profile") or {}),
        }

        def median(name: str) -> float | None:
            values = sorted(float(row[name]) for row in rows if row.get(name) is not None)
            return values[len(values) // 2] if values else None

        canonical_inputs: dict[str, float | int | None] = {
            "average_power_W": machine.get("average_power_W")
            or machine.get("actual_power_W")
            or machine.get("laser_power_W"),
            "frequency_kHz": median("frequency_kHz"),
            "pulse_width_ps": median("pulse_width_ps"),
            "scan_speed_mm_s": median("scan_speed_mm_s"),
            "hatch_spacing_um": median("hatch_spacing_um"),
            "beam_radius_um": machine.get("beam_radius_um")
            or machine.get("spot_radius_um"),
            "passes": median("passes"),
        }
        dataset_inputs = {
            "frequency_kHz",
            "pulse_width_ps",
            "scan_speed_mm_s",
            "hatch_spacing_um",
            "passes",
        }
        verified_inputs = {
            name
            for name, value in canonical_inputs.items()
            if value is not None
            and (
                name in dataset_inputs
                or bool(machine.get(f"{name}_verified", False))
                or (
                    name == "average_power_W"
                    and bool(machine.get("actual_power_W_verified", False))
                )
                or (
                    name == "beam_radius_um"
                    and bool(machine.get("spot_radius_um_verified", False))
                )
            )
        }
        canonical = PhysicsCanonicalizer().canonicalize(
            canonical_inputs,
            verified_inputs=verified_inputs,
            input_refs=[
                ArtifactRef(
                    type="ScientificCapabilityReport",
                    id=self._latest_artifact_id(bus, "ScientificCapabilityReport"),
                ),
                ArtifactRef(
                    type="DataProfile",
                    id=self._latest_artifact_id(bus, "DataProfile"),
                ),
            ],
        )
        canonical_artifact = self._persist_artifact(
            bus.run_id,
            "CanonicalPhysicsState",
            canonical.model_dump(mode="json"),
            input_refs=[item.model_dump(mode="json") for item in canonical.input_refs],
            schema_version=canonical.schema_version,
        )
        trace.artifact_created(
            "CanonicalPhysicsState",
            canonical_artifact,
            counts={
                "coordinates": len(canonical.quantities),
                "missing": len(canonical.missing_inputs),
            },
        )
        evidence_ir_id = self._latest_artifact_id(bus, "EvidenceIRSet")
        evidence_payload = self._latest_artifact_content(bus, "EvidenceIRSet") or {}
        evidence_items = list(evidence_payload.get("items") or [])
        trace.operation_started(
            "compile-typed-priors",
            "EvidenceIR 编译为 typed PriorObject",
            input_refs=[{"type": "EvidenceIRSet", "id": evidence_ir_id}],
        )
        prior_set = compile_typed_priors(evidence_items)
        prior_set_artifact = self._persist_artifact(
            bus.run_id,
            "PriorObjectSet",
            prior_set.model_dump(mode="json"),
            input_refs=[{"type": "EvidenceIRSet", "id": evidence_ir_id}],
            schema_version=prior_set.schema_version,
        )
        trace.operation_completed(
            "compile-typed-priors",
            f"typed Prior 编译完成（{prior_set_artifact}）",
            output_refs=[{"type": "PriorObjectSet", "id": prior_set_artifact}],
            counts={"priors": len(prior_set.priors), "conflicts": len(prior_set.conflicts)},
            reason_codes=["conflicts_preserved_separately"] if prior_set.conflicts else [],
        )
        trace.artifact_created(
            "PriorObjectSet",
            prior_set_artifact,
            input_refs=[{"type": "EvidenceIRSet", "id": evidence_ir_id}],
        )

        parameter_priors = [item for item in prior_set.priors if isinstance(item, ParameterPrior)]
        data_profile_id = self._latest_artifact_id(bus, "DataProfile")
        trace.operation_started(
            "parameter-identification-v1",
            "有界多起点参数辨识与可辨识性审计",
            input_refs=[
                {"type": "DataProfile", "id": data_profile_id},
                {"type": "PriorObjectSet", "id": prior_set_artifact},
                {"type": "CanonicalPhysicsState", "id": canonical_artifact},
            ],
        )
        engine = ParameterIdentificationEngine()
        observations = list(task_spec.get("calibration_observations") or [])
        if observations:
            identifiability, calibration = engine.identify(
                observations,
                parameter_priors=parameter_priors,
                requested_parameters=task_spec.get("calibration_parameters")
                or ("F_th_eff", "incubation_S", "delta_eff", "thermal_diffusivity"),
                random_seed=random_seed,
                input_refs=[
                    ArtifactRef(type="DataProfile", id=data_profile_id),
                    ArtifactRef(type="PriorObjectSet", id=prior_set_artifact),
                    ArtifactRef(type="CanonicalPhysicsState", id=canonical_artifact),
                ],
            )
        else:
            identifiability, calibration = engine.identify_from_macro_rows(
                self.topic2._rows_for_scope(scope),
                input_refs=[
                    ArtifactRef(type="DataProfile", id=data_profile_id),
                    ArtifactRef(type="PriorObjectSet", id=prior_set_artifact),
                    ArtifactRef(type="CanonicalPhysicsState", id=canonical_artifact),
                ],
            )
        ident_artifact = self._persist_artifact(
            bus.run_id,
            "IdentifiabilityReport",
            identifiability.model_dump(mode="json"),
            input_refs=[
                {"type": "DataProfile", "id": data_profile_id},
                {"type": "PriorObjectSet", "id": prior_set_artifact},
            ],
            schema_version=identifiability.schema_version,
        )
        calibration = calibration.model_copy(
            update={
                "input_refs": [
                    ArtifactRef(type="IdentifiabilityReport", id=ident_artifact),
                    ArtifactRef(type="PriorObjectSet", id=prior_set_artifact),
                    ArtifactRef(type="DataProfile", id=data_profile_id),
                    ArtifactRef(type="CanonicalPhysicsState", id=canonical_artifact),
                ]
            }
        )
        calibration_artifact = self._persist_artifact(
            bus.run_id,
            "CalibrationResult",
            calibration.model_dump(mode="json"),
            input_refs=[
                {"type": "IdentifiabilityReport", "id": ident_artifact},
                {"type": "PriorObjectSet", "id": prior_set_artifact},
                {"type": "DataProfile", "id": data_profile_id},
                {"type": "CanonicalPhysicsState", "id": canonical_artifact},
            ],
            schema_version=calibration.schema_version,
        )
        trace.operation_completed(
            "parameter-identification-v1",
            f"参数辨识完成（{calibration_artifact}）",
            output_refs=[
                {"type": "IdentifiabilityReport", "id": ident_artifact},
                {"type": "CalibrationResult", "id": calibration_artifact},
            ],
            counts={
                "parameters": len(calibration.parameters),
                "identifiable": sum(
                    1
                    for item in calibration.parameters
                    if str(item.identifiability) == "IDENTIFIABLE"
                ),
                "not_identifiable": sum(
                    1
                    for item in calibration.parameters
                    if str(item.identifiability) == "NOT_IDENTIFIABLE"
                ),
            },
        )
        trace.artifact_created("IdentifiabilityReport", ident_artifact)
        trace.artifact_created(
            "CalibrationResult",
            calibration_artifact,
            input_refs=[
                {"type": "IdentifiabilityReport", "id": ident_artifact},
                {"type": "PriorObjectSet", "id": prior_set_artifact},
            ],
        )
        return {
            "meta": {
                "prior_set_artifact_id": prior_set_artifact,
                "canonical_physics_artifact_id": canonical_artifact,
                "identifiability_artifact_id": ident_artifact,
                "calibration_artifact_id": calibration_artifact,
            },
            "content": {
                "prior_object_set": prior_set.model_dump(mode="json"),
                "canonical_physics_state": canonical.model_dump(mode="json"),
                "identifiability_report": identifiability.model_dump(mode="json"),
                "calibration_result": calibration.model_dump(mode="json"),
            },
        }

    def _stage_establish_process_model(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Calibration/Priors -> one canonical LocalRemovalModel."""
        trace = ScientificTrace(bus, "establish_process_model")
        calibration_artifact = self._latest_artifact_id(bus, "CalibrationResult")
        prior_set_artifact = self._latest_artifact_id(bus, "PriorObjectSet")
        calibration_payload = self._latest_artifact_content(bus, "CalibrationResult")
        prior_payload = self._latest_artifact_content(bus, "PriorObjectSet")
        if not calibration_payload or not prior_payload:
            raise ValueError("calibration and PriorObjectSet are required before process model")
        calibration = CalibrationResult.model_validate(calibration_payload)
        prior_set = PriorObjectSet.model_validate(prior_payload)
        parameter_priors = [item for item in prior_set.priors if isinstance(item, ParameterPrior)]
        mechanism_priors = [item for item in prior_set.priors if isinstance(item, MechanismModelPrior)]
        refs = [
            ArtifactRef(type="CalibrationResult", id=calibration_artifact),
            ArtifactRef(type="PriorObjectSet", id=prior_set_artifact),
        ]
        mode = RemovalModelMode(str(task_spec.get("local_removal_mode") or "RECONSTRUCTED"))
        factory = LocalRemovalModelFactory()
        trace.operation_started(
            "local-removal-initialization",
            f"LocalRemovalModel {mode.value} 初始化",
            input_refs=[item.model_dump(mode="json") for item in refs],
        )
        if mode == RemovalModelMode.EMPIRICAL:
            kernel_payload = task_spec.get("empirical_kernel")
            if not kernel_payload:
                raise ValueError("EMPIRICAL mode requires empirical_kernel")
            model = factory.empirical(
                kernel=RemovalKernel.model_validate(kernel_payload),
                threshold_J_cm2=float(task_spec.get("threshold_J_cm2") or 1.0),
                incubation_S=float(task_spec.get("incubation_S") or 1.0),
                input_refs=refs,
            )
        elif mode == RemovalModelMode.HYBRID:
            kernel_payload = task_spec.get("empirical_kernel")
            if not kernel_payload:
                raise ValueError("HYBRID mode requires empirical_kernel")
            model = factory.hybrid(
                empirical_kernel=RemovalKernel.model_validate(kernel_payload),
                calibration=calibration,
                parameter_priors=parameter_priors,
                mechanism_priors=mechanism_priors,
                input_refs=refs,
            )
        else:
            machine = {
                **dict(scope.device_properties or {}),
                **dict(task_spec.get("machine_profile") or {}),
            }
            model = factory.reconstructed(
                calibration=calibration,
                parameter_priors=parameter_priors,
                mechanism_priors=mechanism_priors,
                beam_radius_um=machine.get("beam_radius_um") or machine.get("spot_radius_um"),
                grid_spacing_um=float((task_spec.get("target_geometry") or {}).get("grid_spacing_um") or 2.0),
                input_refs=refs,
            )
        model_artifact = self._persist_artifact(
            bus.run_id,
            "LocalRemovalModel",
            model.model_dump(mode="json"),
            input_refs=[item.model_dump(mode="json") for item in refs],
            schema_version=model.schema_version,
        )
        physical_state = PhysicalModelState(
            state_id=f"physical-state-{canonical_hash({'run': bus.run_id, 'model': model_artifact})[:16]}",
            input_refs=[*refs, ArtifactRef(type="LocalRemovalModel", id=model_artifact)],
            canonical_physics_status=ScientificStatus.PARTIAL,
            active_mechanism_models=[
                item.model_family for item in mechanism_priors
            ] or ["POWER_LAW_INCUBATION_PROVISIONAL"],
            calibrated_parameter_refs=[ArtifactRef(type="CalibrationResult", id=calibration_artifact)],
            local_removal_model_ref=ArtifactRef(type="LocalRemovalModel", id=model_artifact),
            simulator_fidelity=SimulationFidelity.F2_DEFOCUS_RECURSION,
            uncertainty_status=ScientificStatus.PARTIAL,
            assumptions=list(model.assumptions),
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="LocalRemovalModelFactory:v1",
                    role="physical_model_state",
                )
            ],
        )
        physical_state_artifact = self._persist_artifact(
            bus.run_id,
            "PhysicalModelState",
            physical_state.model_dump(mode="json"),
            input_refs=[
                {"type": "CalibrationResult", "id": calibration_artifact},
                {"type": "PriorObjectSet", "id": prior_set_artifact},
                {"type": "LocalRemovalModel", "id": model_artifact},
            ],
            schema_version=physical_state.schema_version,
        )
        trace.operation_completed(
            "local-removal-initialization",
            f"局部去除模型建立（{model_artifact}）",
            output_refs=[
                {"type": "LocalRemovalModel", "id": model_artifact},
                {"type": "PhysicalModelState", "id": physical_state_artifact},
            ],
            counts={"parameter_count": len(model.parameter_semantics)},
            reason_codes=[f"mode={mode.value}", "effective_parameters_are_not_physical_constants"],
        )
        trace.artifact_created("LocalRemovalModel", model_artifact)
        trace.artifact_created(
            "PhysicalModelState",
            physical_state_artifact,
            input_refs=[{"type": "LocalRemovalModel", "id": model_artifact}],
        )
        return {
            "meta": {
                "local_removal_model_artifact_id": model_artifact,
                "physical_model_state_artifact_id": physical_state_artifact,
                "mode": mode.value,
            },
            "content": {
                "local_removal_model": model.model_dump(mode="json"),
                "physical_model_state": physical_state.model_dump(mode="json"),
            },
        }

    def _stage_plan_process(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """TargetGeometry -> candidate paths -> Simulator -> ToolpathPlan."""
        trace = ScientificTrace(bus, "plan_process")
        model_artifact = self._latest_artifact_id(bus, "LocalRemovalModel")
        model_payload = self._latest_artifact_content(bus, "LocalRemovalModel")
        if not model_payload:
            raise ValueError("LocalRemovalModel is required before planning")
        model = LocalRemovalModel.model_validate(model_payload)
        canonical_artifact = self._latest_artifact_id(bus, "CanonicalPhysicsState")
        canonical_payload = self._latest_artifact_content(bus, "CanonicalPhysicsState") or {}
        canonical_peak_fluence = (
            (canonical_payload.get("quantities") or {}).get("peak_fluence") or {}
        ).get("value")
        rows = self.topic2._rows_for_scope(scope)
        observed_depths = [float(row["depth_um"]) for row in rows if row.get("depth_um") is not None]
        geometry_payload = dict(task_spec.get("target_geometry") or {})
        geometry = TargetGeometry(
            geometry_type="RECTANGULAR_POCKET",
            width_um=float(geometry_payload.get("width_um") or 40.0),
            height_um=float(geometry_payload.get("height_um") or geometry_payload.get("length_um") or 40.0),
            target_depth_um=float(
                geometry_payload.get("target_depth_um")
                or task_spec.get("target_depth_um")
                or (sorted(observed_depths)[len(observed_depths) // 2] if observed_depths else 5.0)
            ),
            grid_spacing_um=float(geometry_payload.get("grid_spacing_um") or model.kernel.grid_spacing_um),
        )
        def median(name: str, default: float) -> float:
            values = sorted(float(row[name]) for row in rows if row.get(name) is not None)
            return values[len(values) // 2] if values else default

        laser = {
            "frequency_kHz": float((task_spec.get("laser_parameters") or {}).get("frequency_kHz") or median("frequency_kHz", 100.0)),
            "scan_speed_mm_s": float((task_spec.get("laser_parameters") or {}).get("scan_speed_mm_s") or median("scan_speed_mm_s", 100.0)),
            "peak_fluence_J_cm2": float(
                (task_spec.get("laser_parameters") or {}).get("peak_fluence_J_cm2")
                or canonical_peak_fluence
                or model.threshold_J_cm2 * 2.0
            ),
        }
        units = {
            "pulse_width_ps": "ps",
            "frequency_kHz": "kHz",
            "hatch_spacing_um": "um",
            "passes": "count",
            "scan_speed_mm_s": "mm/s",
        }
        machine_constraints = [
            ConstraintValue(name=name, lower=value["lower"], upper=value["upper"], unit=units[name])
            for name, value in self._machine_bounds(scope, rows).items()
        ]
        prior_payload = self._latest_artifact_content(bus, "PriorObjectSet") or {}
        prior_set = PriorObjectSet.model_validate(prior_payload)
        planning_priors = [item for item in prior_set.priors if isinstance(item, PlanningPreferencePrior)]
        trace.operation_started(
            "simulator-driven-toolpath-planning",
            "参数化路径候选的形貌仿真评估",
            input_refs=[
                {"type": "LocalRemovalModel", "id": model_artifact},
                {"type": "CanonicalPhysicsState", "id": canonical_artifact},
                {"type": "PriorObjectSet", "id": self._latest_artifact_id(bus, "PriorObjectSet")},
            ],
        )
        planner = ToolpathPlanner()
        plan, simulation = planner.plan(
            target=geometry,
            model=model,
            laser_parameters=laser,
            machine_constraints=machine_constraints,
            planning_priors=planning_priors,
            path_families=(PathFamily.RASTER, PathFamily.CROSS_HATCH),
            fidelity=SimulationFidelity.F2_DEFOCUS_RECURSION,
            deterministic_seed=random_seed,
            input_refs=[
                ArtifactRef(type="LocalRemovalModel", id=model_artifact),
                ArtifactRef(type="CanonicalPhysicsState", id=canonical_artifact),
            ],
        )
        simulation_artifact = self._persist_artifact(
            bus.run_id,
            "MorphologySimulationResult",
            simulation.model_dump(mode="json"),
            input_refs=[
                {"type": "LocalRemovalModel", "id": model_artifact},
                {"type": "CanonicalPhysicsState", "id": canonical_artifact},
            ],
            schema_version=simulation.schema_version,
        )
        plan = plan.model_copy(
            update={
                "simulation_ref": ArtifactRef(
                    type="MorphologySimulationResult", id=simulation_artifact
                ),
                "input_refs": [
                    ArtifactRef(type="MorphologySimulationResult", id=simulation_artifact),
                    ArtifactRef(type="LocalRemovalModel", id=model_artifact),
                    ArtifactRef(type="CanonicalPhysicsState", id=canonical_artifact),
                    ArtifactRef(
                        type="PriorObjectSet",
                        id=self._latest_artifact_id(bus, "PriorObjectSet"),
                    ),
                ],
            }
        )
        plan_artifact = self._persist_artifact(
            bus.run_id,
            "ToolpathPlan",
            plan.model_dump(mode="json"),
            input_refs=[
                {"type": "MorphologySimulationResult", "id": simulation_artifact},
                {"type": "LocalRemovalModel", "id": model_artifact},
                {"type": "CanonicalPhysicsState", "id": canonical_artifact},
                {"type": "PriorObjectSet", "id": self._latest_artifact_id(bus, "PriorObjectSet")},
            ],
            schema_version=plan.schema_version,
        )
        baseline_ref = ArtifactRef(
            type="ModelTrainingResult",
            id=self._latest_artifact_id(bus, "ModelTrainingResult"),
        )
        correction = ProcessCorrectionInterface(
            interface_id=(
                f"process-correction-{canonical_hash({'run': bus.run_id, 'simulation': simulation_artifact})[:16]}"
            ),
            input_refs=[
                baseline_ref,
                ArtifactRef(
                    type="MorphologySimulationResult", id=simulation_artifact
                ),
            ],
            raw_baseline_ref=baseline_ref,
            physics_prediction_ref=ArtifactRef(
                type="MorphologySimulationResult", id=simulation_artifact
            ),
            residual_model_ref=None,
            status=ScientificStatus.PARTIAL,
            assumptions=[
                "HYBRID residual interface is available; no field residual model is claimed trained in V1"
            ],
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="ProcessCorrectionInterface:v1",
                    role="raw_physics_hybrid_boundary",
                )
            ],
        )
        correction_artifact = self._persist_artifact(
            bus.run_id,
            "ProcessCorrectionInterface",
            correction.model_dump(mode="json"),
            input_refs=[item.model_dump(mode="json") for item in correction.input_refs],
            schema_version=correction.schema_version,
        )
        trace.operation_completed(
            "simulator-driven-toolpath-planning",
            f"路径规划完成（{plan_artifact}）",
            output_refs=[
                {"type": "MorphologySimulationResult", "id": simulation_artifact},
                {"type": "ToolpathPlan", "id": plan_artifact},
                {"type": "ProcessCorrectionInterface", "id": correction_artifact},
            ],
            counts={"candidates": len(plan.candidate_summary), "pulses": simulation.pulse_count},
            reason_codes=["selected_by_morphology_error_plus_machining_time"],
        )
        trace.artifact_created(
            "MorphologySimulationResult",
            simulation_artifact,
            input_refs=[
                {"type": "LocalRemovalModel", "id": model_artifact},
                {"type": "CanonicalPhysicsState", "id": canonical_artifact},
            ],
        )
        trace.artifact_created(
            "ToolpathPlan",
            plan_artifact,
            input_refs=[
                {"type": "MorphologySimulationResult", "id": simulation_artifact},
                {"type": "LocalRemovalModel", "id": model_artifact},
                {"type": "CanonicalPhysicsState", "id": canonical_artifact},
                {
                    "type": "PriorObjectSet",
                    "id": self._latest_artifact_id(bus, "PriorObjectSet"),
                },
            ],
        )
        trace.artifact_created(
            "ProcessCorrectionInterface",
            correction_artifact,
            input_refs=[
                {"type": "MorphologySimulationResult", "id": simulation_artifact},
                {"type": "ModelTrainingResult", "id": baseline_ref.id},
            ],
        )
        # B0 compatibility: keep the proven BO comparison as a secondary
        # diagnostic inside the canonical planning stage. ToolpathPlan remains
        # the final planning artifact.
        legacy_optimization = self._stage_optimization(
            task_spec, scope, bus, random_seed
        )["content"]
        return {
            "meta": {
                "simulation_artifact_id": simulation_artifact,
                "toolpath_plan_artifact_id": plan_artifact,
                "canonical_physics_artifact_id": canonical_artifact,
                "path_family": plan.path_family.value,
            },
            "content": {
                "target_geometry": geometry.model_dump(mode="json"),
                "morphology_simulation": simulation.model_dump(mode="json"),
                "toolpath_plan": plan.model_dump(mode="json"),
                "process_correction": correction.model_dump(mode="json"),
                "legacy_optimization": legacy_optimization,
            },
        }

    def _stage_evaluate_observation(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Persist an observation and explicit update intents without claiming validation."""
        payload = task_spec.get("observation")
        if not isinstance(payload, dict):
            raise ValueError("evaluate_observation requires task_spec.observation")
        origin_raw = payload.get("origin")
        if not origin_raw:
            raise ValueError("observation.origin is required")
        origin = EvidenceOrigin(str(origin_raw))
        measurements = [
            ObservationMeasurement.model_validate(item)
            for item in (payload.get("measurements") or [])
        ]
        if not measurements:
            raise ValueError("observation.measurements is required")
        refs = [
            ArtifactRef(
                type="ToolpathPlan",
                id=self._latest_artifact_id(bus, "ToolpathPlan"),
            ),
            ArtifactRef(
                type="CalibrationResult",
                id=self._latest_artifact_id(bus, "CalibrationResult"),
            ),
            ArtifactRef(
                type="LocalRemovalModel",
                id=self._latest_artifact_id(bus, "LocalRemovalModel"),
            ),
        ]
        morphology_ref_payload = payload.get("morphology_payload_ref")
        morphology_ref = (
            ArtifactRef.model_validate(morphology_ref_payload)
            if isinstance(morphology_ref_payload, dict)
            else None
        )
        observation = ObservationResult(
            observation_id=f"observation-{canonical_hash({'run': bus.run_id, 'payload': payload})[:16]}",
            input_refs=refs,
            origin=origin,
            measurements=measurements,
            morphology_payload_ref=morphology_ref,
            status=ScientificStatus.PARTIAL,
            update_triggers=[
                "DATA_STATE",
                "CALIBRATION",
                "PROCESS_MODEL",
                "E2P_TRUST",
            ],
            independent_validation=bool(payload.get("independent_validation", False)),
            assumptions=[
                "update triggers are persisted intents; no automatic trust promotion occurs in V1"
            ],
            provenance=[
                ProvenanceRecord(
                    source_type=origin.value,
                    source_ref=str(payload.get("source_ref") or "task_spec.observation"),
                    role="closed_loop_observation",
                )
            ],
        )
        artifact_id = self._persist_artifact(
            bus.run_id,
            "ObservationResult",
            observation.model_dump(mode="json"),
            input_refs=[item.model_dump(mode="json") for item in refs],
            schema_version=observation.schema_version,
        )
        trace = ScientificTrace(bus, "evaluate_observation")
        trace.artifact_created(
            "ObservationResult",
            artifact_id,
            input_refs=[item.model_dump(mode="json") for item in refs],
            counts={"measurements": len(measurements), "update_triggers": 4},
        )
        trace.validation(
            "Observation 已登记；等待显式 calibration/model/trust 更新",
            counts={"measurements": len(measurements)},
            reason_codes=[
                "synthetic_fixture_not_validation"
                if origin == EvidenceOrigin.SYNTHETIC_TEST_FIXTURE
                else "observation_pending_update"
            ],
        )
        return {
            "meta": {"artifact_id": artifact_id, "origin": origin.value},
            "content": {"observation_result": observation.model_dump(mode="json")},
        }

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
        evidence_artifact_id = self._latest_artifact_id(bus, "EvidenceCompileResult")
        knowledge_state_id = self._latest_artifact_id(bus, "KnowledgeState")
        trace = ScientificTrace(bus, "apply_knowledge")
        trace.operation_started(
            "apply-governed-prior",
            "受治理先验编译",
            input_refs=[
                {"type": "TaskScope", "id": scope.task_context_id or "task"},
                {"type": "EvidenceCompileResult", "id": evidence_artifact_id},
                {"type": "KnowledgeState", "id": knowledge_state_id},
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
                input_refs=[
                    {"type": "EvidenceCompileResult", "id": evidence_artifact_id},
                    {"type": "KnowledgeState", "id": knowledge_state_id},
                ],
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
        planning = result.get("plan_process") or {}
        bo = planning.get("legacy_optimization") or {}
        calibration_stage = result.get("calibrate_physics") or {}
        process_model_stage = result.get("establish_process_model") or {}
        capability = result.get("assess_capability") or {}
        assess = result.get("assess_data") or {}
        cfa = assess.get("cfa") or {}
        prepare = result.get("prepare_knowledge") or {}
        bundle = prepare.get("bundle") or {}
        gap = (
            result.get("analyze_knowledge_requirements")
            or result.get("analyze_knowledge_gaps")
            or {}
        )
        satisfy = result.get("satisfy_requirements") or {}
        knowledge_state = satisfy.get("knowledge_state") or {}
        typed_prior_set = calibration_stage.get("prior_object_set") or {}
        canonical_physics = calibration_stage.get("canonical_physics_state") or {}
        local_removal = process_model_stage.get("local_removal_model") or {}
        physical_state = process_model_stage.get("physical_model_state") or {}
        toolpath_plan = planning.get("toolpath_plan")
        morphology_simulation = planning.get("morphology_simulation")
        process_correction = planning.get("process_correction")
        observation_result = (
            result.get("evaluate_observation") or {}
        ).get("observation_result")
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
                "governedEvidenceCount": len(typed_prior_set.get("input_refs") or []),
                "typedPriorCount": len(typed_prior_set.get("priors") or []),
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
            "physicsToPlanning": {
                "capability": capability or None,
                "priorObjectSet": typed_prior_set or None,
                "canonicalPhysicsState": canonical_physics or None,
                "identifiabilityReport": calibration_stage.get("identifiability_report"),
                "calibrationResult": calibration_stage.get("calibration_result"),
                "physicalModelState": physical_state or None,
                "localRemovalModel": local_removal or None,
                "morphologySimulation": morphology_simulation,
                "toolpathPlan": toolpath_plan,
                "processCorrection": process_correction,
                "observationResult": observation_result,
            },
            "audit": {
                "evidenceIds": [
                    ref.get("id")
                    for ref in typed_prior_set.get("input_refs") or []
                    if isinstance(ref, dict)
                ],
                "priorContentHash": typed_prior_set.get("prior_set_id"),
                "boRunIds": [
                    (bo.get("vanilla") or {}).get("run_id"),
                    (bo.get("evidence_assisted") or {}).get("run_id"),
                ],
                "modelVersion": modeling.get("model_version"),
                "replayable": False,
                "artifactLineage": {
                    "ScientificCapabilityReport": self._latest_artifact_id_for_run(run_id, "ScientificCapabilityReport"),
                    "KnowledgeRequirementSet": self._latest_artifact_id_for_run(run_id, "KnowledgeRequirementSet"),
                    "EvidenceIRSet": self._latest_artifact_id_for_run(run_id, "EvidenceIRSet"),
                    "PriorObjectSet": self._latest_artifact_id_for_run(run_id, "PriorObjectSet"),
                    "CanonicalPhysicsState": self._latest_artifact_id_for_run(
                        run_id, "CanonicalPhysicsState"
                    ),
                    "CalibrationResult": self._latest_artifact_id_for_run(run_id, "CalibrationResult"),
                    "LocalRemovalModel": self._latest_artifact_id_for_run(run_id, "LocalRemovalModel"),
                    "MorphologySimulationResult": self._latest_artifact_id_for_run(run_id, "MorphologySimulationResult"),
                    "ToolpathPlan": self._latest_artifact_id_for_run(run_id, "ToolpathPlan"),
                    "ProcessCorrectionInterface": self._latest_artifact_id_for_run(
                        run_id, "ProcessCorrectionInterface"
                    ),
                    "ObservationResult": self._latest_artifact_id_for_run(
                        run_id, "ObservationResult"
                    ),
                },
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
