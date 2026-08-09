"""Evidence-governed Physics-to-Planning ApplicationRun orchestrator.

DEMO_FIXTURE, RESEARCH and SANDBOX share the same ordered stage graph and
artifact contracts.  Modes only change resource resolution and fail-closed
policy; there is no parallel demo pipeline.
"""

from __future__ import annotations

import json
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from apps.topic2_backend.application.equipment import (
    effective_execution_mode,
    resolve_machine_snapshot,
)
from apps.topic2_backend.application.events import (
    ERROR,
    RUN_BLOCKED,
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
from apps.topic2_backend.application.gates import (
    STAGE_PHASES,
    GateResult,
    StageBlockedError,
    active_mechanism_required,
    knowledge_gate,
    physical_model_gate,
    planning_gate,
    resource_gate,
    run_control_state,
)
from apps.topic2_backend.application.requirement_resolution import (
    resolve_requirement_chain,
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
from packages.process_contracts.knowledge import KnowledgeState
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
    ParameterObservation,
    PathFamily,
    PhysicalModelState,
    ProcessCorrectionInterface,
    ProvenanceRecord,
    RemovalKernel,
    RemovalModelMode,
    ScientificCapabilityReport,
    ScientificStatus,
    SimulationFidelity,
    TargetGeometry,
    ToolpathPlan,
)
from packages.scientific_computation.identification import ParameterIdentificationEngine
from packages.scientific_computation.local_removal import LocalRemovalModelFactory
from packages.scientific_computation.needs import (
    ScientificNeedType,
    classify_requirement,
    compile_scientific_needs,
)
from packages.scientific_computation.planning import ToolpathPlanner
from packages.scientific_retrieval.planner import plan_retrieval

WORKFLOW_VERSION = "physics-to-planning-application-v1"
DEMO_SCENARIO_01 = {
    "material": "SiC",
    "laser_type": "fs",
    "process_type": "fs_laser_processing",
    "geometry_type": "rectangular_groove",
    "objective_metric": "depth_um",
    "dataset_ref": "topic2-fixture-v1",
    "dataset_equipment_scope_id": "DEMO-FS-LASER-01",
    "equipment_profile_id": "DEMO-FS-LASER-01",
    "execution_equipment_ref": {
        "equipment_profile_id": "DEMO-FS-LASER-01",
        "revision_id": "rev-1",
    },
    "calibration_observation_set_ref": "golden-sic-calibration-v1",
    "prior_set_ref": "golden-sic-priors-v1",
    "execution_mode": "DEMO_FIXTURE",
    "target_geometry": {
        "width_um": 30.0,
        "height_um": 24.0,
        "target_depth_um": 20.0,
        "grid_spacing_um": 2.0,
    },
    "random_seed": 42,
    "knowledge_gate_decision": {"status": "allowed"},
}

# Physics-to-Planning V1 canonical ApplicationRun.
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
    "simulate_morphology",
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
    "simulate_morphology": "候选路径形貌仿真",
    "plan_process": "仿真结果驱动的路径规划",
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

class Topic2ApplicationService:
    def __init__(
        self,
        topic2: Topic2Service,
        *,
        approval_verifier: Callable[[str], bool] | None = None,
        agent_proxy_target: str | None = None,
        workflow_version: str = WORKFLOW_VERSION,
        resolution_llm_client: Any | None = None,
        resolution_model: str = "scientific-reading-v1",
    ):
        self.topic2 = topic2
        self.repository = topic2.repository
        self.settings = topic2.settings
        self.approval_verifier = approval_verifier
        self.agent_proxy_target = agent_proxy_target
        self.workflow_version = workflow_version
        self.resolution_llm_client = resolution_llm_client
        self.resolution_model = resolution_model

    # --------------------------------------------------------------- scoping

    def _scope(self, payload: dict[str, Any]) -> TaskScope:
        if isinstance(payload, TaskScope):
            return payload
        if "equipment_id" in payload and "target" in payload:
            return TaskScope.model_validate(payload)
        material = payload.get("material")
        laser_type = payload.get("laser_type")
        geometry_type = payload.get("geometry_type")
        target = payload.get("objective_metric")
        missing = [
            key
            for key, value in (
                ("material", material),
                ("laser_type", laser_type),
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
        equipment_id = self.repository.resolve_real_equipment_scope(
            material=str(material),
            laser_type=str(laser_type),
            geometry_type=str(geometry_type),
            target=str(target),
        )
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

    @staticmethod
    def _execution_equipment_ref(
        task_spec: dict[str, Any], scope: TaskScope
    ) -> tuple[str, str | None]:
        """Return the immutable execution-profile identity selected by Task."""
        raw = task_spec.get("execution_equipment_ref")
        if isinstance(raw, dict):
            profile_id = str(raw.get("equipment_profile_id") or "").strip()
            revision_id = str(raw.get("revision_id") or "").strip() or None
            return profile_id, revision_id
        if isinstance(raw, str) and raw.strip():
            return raw.strip(), str(task_spec.get("equipment_revision_id") or "").strip() or None
        if effective_execution_mode("research", task_spec) == "SANDBOX":
            return str(task_spec.get("equipment_profile_id") or scope.equipment_id), None
        return "UNRESOLVED-EQUIPMENT", None

    @staticmethod
    def _validate_task_inputs(mode: str, task_spec: dict[str, Any]) -> None:
        execution_mode = effective_execution_mode(mode, task_spec)
        injected = [
            key
            for key in ("machine_profile", "evidence_ir", "calibration_observations")
            if task_spec.get(key) is not None
        ]
        if execution_mode != "SANDBOX" and injected:
            raise ValueError(
                "direct scientific input injection is SANDBOX-only: "
                + ", ".join(injected)
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
        self._validate_task_inputs(mode, task_spec)
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
            summary, stage_results = self._run_research(
                task_spec, scope, requested_stages, bus, effective_seed
            )
            if mode == "demo":
                summary.setdefault("audit", {})["replayable"] = True
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
        except StageBlockedError as exc:
            bus.emit(
                RUN_BLOCKED,
                f"应用运行被 Gate {exc.gate} 阻止：{'；'.join(exc.reasons)}",
                stage="application",
                details={
                    "gate": exc.gate,
                    "phase": exc.phase,
                    "reasons": exc.reasons,
                    "next_actions": exc.next_actions,
                },
            )
            partial_summary = self._research_summary(
                exc.stage_results,
                scope,
                task_spec,
                effective_seed,
                run_id,
            )
            partial_summary["runControlState"] = exc.run_control_state
            self.repository.save_application_run(
                {
                    "application_run_id": run_id,
                    "client_request_id": client_request_id,
                    "task_context_ref": task_ref,
                    "mode": mode,
                    "workflow_version": self.workflow_version,
                    "status": "blocked",
                    "stage_status": {
                        stage: {"status": "completed"}
                        for stage in requested_stages
                        if stage
                        in ((exc.run_control_state or {}).get("completed_stages") or [])
                    },
                    "result": partial_summary
                    if exc.run_control_state
                    else {
                        "runControlState": {
                            "schema_version": "run-control-state-v1",
                            "execution_mode": effective_execution_mode(
                                mode, task_spec
                            ),
                            "current_phase": exc.phase,
                            "phase_status": "BLOCKED",
                            "blocking_reasons": exc.reasons,
                            "next_actions": exc.next_actions,
                            "completed_stages": [],
                        },
                    },
                    "task_spec": task_spec,
                    "stage_results": exc.stage_results,
                    "completed_at": timestamp(),
                }
            )
            return self._run_summary(self.repository.application_run(run_id) or {})
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
        "simulate_morphology",
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
                "result": run.get("result"),
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
        except StageBlockedError as exc:
            bus.emit(
                RUN_BLOCKED,
                f"应用运行续跑被 Gate {exc.gate} 阻止：{'；'.join(exc.reasons)}",
                stage="application",
                details={
                    "gate": exc.gate,
                    "phase": exc.phase,
                    "reasons": exc.reasons,
                    "next_actions": exc.next_actions,
                },
            )
            completed = set((exc.run_control_state or {}).get("completed_stages") or [])
            partial_stage_results = {
                **dict(run.get("stage_results") or {}),
                **dict(exc.stage_results or {}),
            }
            partial_summary = self._research_summary(
                partial_stage_results,
                scope,
                task_spec,
                effective_seed,
                run_id,
            )
            partial_summary["runControlState"] = exc.run_control_state
            self.repository.save_application_run(
                {
                    "application_run_id": run_id,
                    "client_request_id": client_request_id,
                    "task_context_ref": run["task_context_ref"],
                    "mode": "research",
                    "workflow_version": self.workflow_version,
                    "status": "blocked",
                    "stage_status": {
                        **{
                            stage: {"status": "completed"}
                            for stage in (run.get("stage_status") or {})
                        },
                        **{
                            stage: {"status": "completed"}
                            for stage in completed
                        },
                    },
                    "result": partial_summary
                    if exc.run_control_state
                    else {
                        "runControlState": {
                            "schema_version": "run-control-state-v1",
                            "current_phase": exc.phase,
                            "phase_status": "BLOCKED",
                            "blocking_reasons": exc.reasons,
                            "next_actions": exc.next_actions,
                            "completed_stages": [],
                        },
                    },
                    "task_spec": task_spec,
                    "stage_results": partial_stage_results,
                    "completed_at": timestamp(),
                }
            )
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
        """Execute stages over an (optional) existing result; return (summary, stage_results).

        M4: canonical gates are evaluated before their phase - a BLOCKED gate
        stops the run (fail closed) unless execution mode is SANDBOX.
        """
        result: dict[str, Any] = dict(existing_result or {})
        execution_mode = effective_execution_mode("research", task_spec)
        stored_run = self.repository.application_run(bus.run_id) or {}
        stored_status = stored_run.get("stage_status") or {}
        completed: list[str] = [
            stage
            for stage in (*ALL_STAGES, *OPTIONAL_STAGES)
            if (stored_status.get(stage) or {}).get("status") == "completed"
        ]
        gate_results: list[GateResult] = self._previous_gate_results(bus)
        for stage in stages:
            gates = self._gates_before_stage(
                stage, scope, bus, execution_mode, task_spec=task_spec
            )
            for gate in gates:
                gate_results.append(gate)
                if gate.status == "BLOCKED":
                    control = run_control_state(
                        gates=gate_results,
                        execution_mode=execution_mode,
                        current_phase=STAGE_PHASES.get(stage, "UNKNOWN"),
                        phase_status="BLOCKED",
                        completed_stages=completed,
                    )
                    bus.emit(
                        VALIDATION,
                        f"Gate {gate.name} BLOCKED: {'; '.join(gate.reasons)}",
                        stage=stage,
                        details=gate.to_dict(),
                    )
                    raise StageBlockedError(
                        gate.name,
                        reasons=gate.reasons,
                        next_actions=gate.next_actions,
                        phase=STAGE_PHASES.get(stage, "UNKNOWN"),
                        run_control_state=control,
                        stage_results=result,
                    )
            bus.emit(STAGE_STARTED, STAGE_LABELS[stage], stage=stage)
            handler = getattr(self, f"_stage_{stage}")
            stage_result = handler(task_spec, scope, bus, random_seed=random_seed)
            result[stage] = stage_result["content"]
            completed.append(stage)
            bus.emit(
                STAGE_COMPLETED,
                f"{STAGE_LABELS[stage]} 完成",
                stage=stage,
                details=stage_result["meta"],
            )
        last_phase = STAGE_PHASES.get(completed[-1] if completed else stages[0], "UNKNOWN")
        final_status = "COMPLETED" if last_phase == "PLANNING" else "READY"
        control = run_control_state(
            gates=gate_results,
            execution_mode=execution_mode,
            current_phase=last_phase,
            phase_status=final_status,
            completed_stages=completed,
        )
        summary = self._research_summary(result, scope, task_spec, random_seed, bus.run_id)
        summary["runControlState"] = control
        return summary, result

    def _previous_gate_results(self, bus: WorkflowEventBus) -> list[GateResult]:
        """Gates evaluated in earlier checkpoint segments (same run).

        RunControlState lives in the run result (手册 §15), not as an artifact.
        """
        run = self.repository.application_run(bus.run_id) or {}
        payload = ((run.get("result") or {}).get("runControlState")) or {}
        return [
            GateResult(
                name=str(item.get("gate") or name),
                status=str(item.get("status") or "BLOCKED"),
                reasons=list(item.get("reasons") or []),
                next_actions=list(item.get("next_actions") or []),
            )
            for name, item in (payload.get("gates") or {}).items()
            if isinstance(item, dict)
        ]

    def _gates_before_stage(
        self,
        stage: str,
        scope: TaskScope,
        bus: WorkflowEventBus,
        execution_mode: str,
        task_spec: dict[str, Any] | None = None,
    ) -> list[GateResult]:
        """Canonical gates that guard `stage` (fail closed)."""
        try:
            if stage == "assess_capability":
                data_state = self._data_state(
                    scope,
                    task_spec,
                    execution_mode=execution_mode,
                )
                return [
                    resource_gate(
                        self._machine_snapshot(bus),
                        data_state,
                        self._target_geometry_from_task(task_spec, scope, bus),
                        self._execution_context(bus),
                        execution_mode=execution_mode,
                    )
                ]
            if stage == "calibrate_physics":
                capability = (
                    self._latest_artifact_content(bus, "ScientificCapabilityReport")
                    or {}
                )
                required = active_mechanism_required(
                    list(
                        capability.get("mechanism_parameter_requirements") or []
                    )
                )
                prior_set = self._latest_artifact_content(bus, "PriorObjectSet") or {}
                return [
                    knowledge_gate(
                        mechanism_required=required,
                        parameter_priors={
                            str(item.get("parameter"))
                            for item in (prior_set.get("priors") or [])
                            if item.get("prior_type") == "ParameterPrior"
                            and item.get("parameter") is not None
                        },
                        mechanism_model_priors={
                            str(item.get("model_family"))
                            for item in (prior_set.get("priors") or [])
                            if item.get("prior_type") == "MechanismModelPrior"
                            and item.get("model_family") is not None
                        },
                        observation_capabilities=self._observation_capabilities(
                            scope, task_spec, bus
                        ),
                        machine_fields=set(self._machine_fields(bus)),
                        knowledge_state=self._latest_artifact_content(
                            bus, "KnowledgeState"
                        ),
                        execution_mode=execution_mode,
                    )
                ]
            if stage == "simulate_morphology":
                model_payload = self._latest_artifact_content(bus, "LocalRemovalModel")
                gate_c = physical_model_gate(
                    self._latest_artifact_content(bus, "CalibrationResult"),
                    model_payload,
                    execution_mode=execution_mode,
                )
                return [gate_c]
            if stage == "plan_process":
                model_payload = self._latest_artifact_content(bus, "LocalRemovalModel")
                rows = self.topic2._rows_for_scope(scope)
                bounds = self._machine_bounds(
                    scope,
                    rows,
                    snapshot_bounds=(
                        (self._machine_snapshot(bus) or {}).get("machine_bounds")
                    ),
                )
                gate_d = planning_gate(
                    model_available=bool(model_payload),
                    simulation_available=bool(
                        self._latest_artifact_content(bus, "MorphologySimulationResult")
                    ),
                    machine_bounds=bounds,
                    candidate_plan=self._latest_artifact_content(
                        bus, "ToolpathCandidateSet"
                    ),
                    execution_mode=execution_mode,
                )
                return [gate_d]
        except Exception as exc:  # noqa: BLE001 - gate evaluation must fail closed
            return [GateResult(stage, "BLOCKED", [f"gate evaluation failed: {exc}"])]
        return []

    def _data_state(
        self,
        scope: TaskScope,
        task_spec: dict[str, Any] | None = None,
        *,
        execution_mode: str = "RESEARCH",
    ) -> dict[str, Any]:
        """Typed DataState for Gate A (阶段二 T1)."""
        task_spec = task_spec or {}
        dataset_ref = str(task_spec.get("dataset_ref") or "").strip()
        if not dataset_ref and execution_mode != "SANDBOX":
            return {
                "status": "INVALID",
                "reason": "Task 缺少 dataset_ref",
                "dataset_ref": None,
                "n_samples": 0,
                "n_unique_designs": 0,
            }
        dataset = (
            self.repository.dataset(dataset_ref, real_only=True)
            if dataset_ref
            else self.repository.latest_dataset(real_only=True)
        )
        if dataset is None:
            return {
                "status": "INVALID",
                "reason": f"dataset_ref 不存在: {dataset_ref or 'missing'}",
                "dataset_ref": dataset_ref or None,
                "n_samples": 0,
                "n_unique_designs": 0,
            }
        latest = self.repository.latest_dataset(real_only=True)
        if (
            execution_mode != "SANDBOX"
            and latest is not None
            and dataset["dataset_version"] != latest["dataset_version"]
        ):
            return {
                "status": "INVALID",
                "reason": "当前仓库不能物化所选历史 dataset snapshot",
                "dataset_ref": dataset_ref,
                "n_samples": 0,
                "n_unique_designs": 0,
            }
        try:
            rows = self.topic2._rows_for_scope(scope)
        except Exception as exc:  # noqa: BLE001 - no comparable rows
            return {
                "status": "INVALID",
                "reason": str(exc),
                "dataset_ref": dataset.get("dataset_version"),
                "n_samples": 0,
                "n_unique_designs": 0,
            }
        profile = build_data_profile(rows)
        if profile.n_samples == 0 or profile.n_unique_designs == 0:
            return {
                "status": "INVALID",
                "reason": "scope 内无有效样本",
                "dataset_ref": dataset.get("dataset_version"),
                "n_samples": profile.n_samples,
                "n_unique_designs": profile.n_unique_designs,
            }
        return {
            "status": "READY",
            "reason": None,
            "dataset_ref": dataset.get("dataset_version"),
            "dataset_hash": dataset.get("dataset_hash"),
            "n_samples": profile.n_samples,
            "n_unique_designs": profile.n_unique_designs,
        }

    def _target_geometry_from_task(
        self,
        task_spec: dict[str, Any] | None,
        scope: TaskScope,
        bus: WorkflowEventBus,
    ) -> dict[str, Any] | None:
        """TaskSpec target_geometry with geometry_type filled from the scope."""
        task_spec = task_spec or {}
        geometry = dict(task_spec.get("target_geometry") or {})
        if not geometry:
            return None
        geometry.setdefault("geometry_type", scope.geometry_type)
        return geometry

    def _observation_capabilities(
        self,
        scope: TaskScope,
        task_spec: dict[str, Any] | None,
        bus: WorkflowEventBus,
    ) -> set[str]:
        """Parameters identifiable from INDEPENDENT calibration observations.

        Macro dataset rows do NOT count (阶段二 T5): only explicit
        single/multi-pulse observations with absolute fluence qualify.
        """
        observations = self._parameter_observations(bus)
        if not observations:
            return set()
        has_absolute_fluence = any(
            item.get("peak_fluence_J_cm2") is not None for item in observations
        )
        pulse_counts = {
            int(item["pulse_count"])
            for item in observations
            if item.get("pulse_count") is not None
        }
        capabilities: set[str] = set()
        if has_absolute_fluence:
            capabilities.add("F_th_eff")
            capabilities.add("delta_eff")
        if len(pulse_counts) >= 2:
            capabilities.add("incubation_S")
        return capabilities

    def _evidence_prior_parameters(self, bus: WorkflowEventBus) -> set[str]:
        """Parameters with numeric ranges in the current EvidenceIRSet."""
        payload = self._latest_artifact_content(bus, "EvidenceIRSet") or {}
        parameters: set[str] = set()
        for item in payload.get("items") or []:
            claim = dict(item.get("claim") or {})
            lower, upper = claim.get("lower"), claim.get("upper")
            parameter = item.get("parameter") or claim.get("parameter")
            if (
                isinstance(lower, (int, float))
                and isinstance(upper, (int, float))
                and float(lower) < float(upper)
                and parameter
            ):
                parameters.add(str(parameter))
        return parameters

    def _demo_task_spec(self, random_seed: int) -> dict[str, Any]:
        spec = dict(DEMO_SCENARIO_01)
        spec["random_seed"] = random_seed
        return spec

    # ---------------------------------------------------------- research stages

    def _stage_prepare_task(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Stage 1: canonical task + equipment snapshot + scope capability."""
        execution_mode = effective_execution_mode(
            "research", task_spec
        )
        execution_profile_id, execution_revision_id = self._execution_equipment_ref(
            task_spec, scope
        )
        snapshot = resolve_machine_snapshot(
            equipment_profile_id=execution_profile_id,
            equipment_revision_id=execution_revision_id,
            run_mode="research",
            task_spec=task_spec,
            agent_proxy_target=self.agent_proxy_target,
            fixture_profiles=self.settings.equipment_profiles,
        )
        snapshot_payload = snapshot.model_dump(mode="json")
        data_state = self._data_state(
            scope,
            task_spec,
            execution_mode=execution_mode,
        )
        dataset_artifact = self._persist_artifact(
            bus.run_id,
            "DatasetRef",
            {
                "schema_version": "dataset-ref-v1",
                "dataset_ref": task_spec.get("dataset_ref"),
                "equipment_scope_id": scope.equipment_id,
                **data_state,
            },
            input_refs=[
                {
                    "type": "DatasetResource",
                    "id": str(task_spec.get("dataset_ref") or "unresolved"),
                }
            ],
            schema_version="dataset-ref-v1",
        )
        snapshot_artifact = self._persist_artifact(
            bus.run_id,
            "MachineProfileSnapshot",
            snapshot_payload,
            input_refs=[{"type": "TaskScope", "id": scope.task_context_id or "task"}],
            schema_version=snapshot.schema_version,
        )
        execution_context = self._build_execution_context(
            task_spec,
            snapshot_payload,
        )
        execution_context_artifact = self._persist_artifact(
            bus.run_id,
            "ExecutionContext",
            execution_context,
            input_refs=[
                {"type": "MachineProfileSnapshot", "id": snapshot_artifact},
                {"type": "TaskScope", "id": scope.task_context_id or "task"},
            ],
            schema_version="execution-context-v1",
        )
        observation_set_artifact, observation_artifacts = (
            self._persist_task_observations(
                task_spec,
                scope,
                bus,
                execution_mode=execution_mode,
            )
        )
        bus.emit(
            VALIDATION,
            (
                f"设备快照：{snapshot.resource_status}（{snapshot.source_quality}）"
                + (f"，缺失：{', '.join(snapshot.missing_required)}" if snapshot.missing_required else "")
            ),
            stage="prepare_task",
            details={
                "resource_status": snapshot.resource_status,
                "source_quality": snapshot.source_quality,
                "missing_required": snapshot.missing_required,
                "execution_mode": execution_mode,
            },
        )
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
            "machine_snapshot_artifact_id": snapshot_artifact,
            "dataset_artifact_id": dataset_artifact,
            "execution_context_artifact_id": execution_context_artifact,
            "observation_set_artifact_id": observation_set_artifact,
            "observation_count": len(observation_artifacts),
            "resource_status": snapshot.resource_status,
            "execution_context_status": execution_context["status"],
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
            "machine_profile_snapshot": snapshot_payload,
            "execution_context": execution_context,
            "dataset_ref": {
                "artifact_id": dataset_artifact,
                "dataset_version": data_state.get("dataset_ref"),
                "equipment_scope_id": scope.equipment_id,
                "status": data_state.get("status"),
            },
            "execution_equipment_ref": {
                "equipment_profile_id": execution_profile_id,
                "revision_id": execution_revision_id,
            },
            "calibration_observation_set_ref": observation_set_artifact,
            "calibration_observation_refs": observation_artifacts,
            "execution_mode": execution_mode,
            "random_seed": random_seed,
            "capability_summary": capability,
        }
        artifact_id = self._persist_artifact(
            bus.run_id,
            "TaskState",
            task_state,
            input_refs=[
                {"type": "TaskScope", "id": scope.task_context_id or "task"},
                {"type": "MachineProfileSnapshot", "id": snapshot_artifact},
                {"type": "DatasetRef", "id": dataset_artifact},
                {"type": "ExecutionContext", "id": execution_context_artifact},
                *(
                    [{"type": "CalibrationObservationSet", "id": observation_set_artifact}]
                    if observation_set_artifact
                    else []
                ),
            ],
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
            machine_profile=self._machine_capability_fields(bus),
            knowledge_state={},
            input_refs=[
                ArtifactRef(type="TaskState", id=task_state_id),
                ArtifactRef(
                    type="MachineProfileSnapshot",
                    id=self._latest_artifact_id(bus, "MachineProfileSnapshot"),
                ),
            ],
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
        dataset = self.repository.dataset(
            str(task_spec.get("dataset_ref") or ""), real_only=True
        )
        if dataset is None and effective_execution_mode("research", task_spec) == "SANDBOX":
            dataset = self.repository.latest_dataset(real_only=True)
        summary = {
            "n_samples": profile.n_samples,
            "n_unique_designs": profile.n_unique_designs,
            "dataset_version": (dataset or {}).get("dataset_version"),
            "dataset_hash": (dataset or {}).get("dataset_hash"),
            "dataset_ref_artifact_id": self._latest_artifact_id(bus, "DatasetRef"),
        }
        trace = ScientificTrace(bus, "assess_data")
        dataset_artifact = self._persist_artifact(
            bus.run_id,
            "DataProfile",
            summary,
            input_refs=[
                {"type": "TaskScope", "id": scope.task_context_id or "task"},
                {"type": "DatasetRef", "id": self._latest_artifact_id(bus, "DatasetRef")},
            ],
        )
        trace.artifact_created(
            "DataProfile",
            dataset_artifact,
            name=f"数据状态快照（{dataset_artifact}）",
            counts={"n_samples": summary["n_samples"]},
        )
        snapshot_spot = self._machine_fields(bus).get("beam_radius_um")
        readiness = self._target_readiness(
            rows,
            scope,
            spot_diameter_um=float(snapshot_spot) * 2.0 if snapshot_spot else None,
        )
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
        """Capability/computation gaps -> ScientificNeedSet -> KnowledgeRequirementSet.

        M2: RESOURCE_INPUT needs (task execution setpoints or equipment
        fields) are classified in the ScientificNeedSet and never become
        literature requirements. Only SCIENTIFIC_KNOWLEDGE /
        CALIBRATION_OBSERVATION needs enter the KnowledgeRequirementSet
        consumed by retrieval.
        """
        trace = ScientificTrace(bus, "analyze_knowledge_requirements")
        capability_ref = self._latest_artifact_id(bus, "ScientificCapabilityReport")
        capability = self._latest_artifact_content(bus, "ScientificCapabilityReport") or {}
        capability_report = ScientificCapabilityReport.model_validate(capability)
        trace.operation_started(
            "requirement-compilation",
            "计算缺口驱动的科学需求编译（四类 Need）",
            input_refs=[
                {"type": "ScientificCapabilityReport", "id": capability_ref},
                {
                    "type": "MachineProfileSnapshot",
                    "id": self._latest_artifact_id(bus, "MachineProfileSnapshot"),
                },
            ],
        )
        capability_requirements = list(capability.get("recommended_requirements") or [])
        requirements: list[dict[str, Any]] = []
        for item in capability_requirements:
            if classify_requirement(item) == ScientificNeedType.RESOURCE_INPUT:
                continue
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
            if item["type"] in ("physics_dependency", "PHYSICS_DEPENDENCY"):
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
                            "id": capability_ref,
                        }
                    ],
                }
            )
        rows = self.topic2._rows_for_scope(scope)
        need_set = compile_scientific_needs(
            capability_report,
            machine_snapshot=self._machine_snapshot(bus),
            data_rows=rows,
            requirements=requirements,
            input_refs=[
                ArtifactRef(type="ScientificCapabilityReport", id=capability_ref),
                ArtifactRef(
                    type="MachineProfileSnapshot",
                    id=self._latest_artifact_id(bus, "MachineProfileSnapshot"),
                ),
            ],
        )
        need_set_artifact = self._persist_artifact(
            bus.run_id,
            "ScientificNeedSet",
            need_set.model_dump(mode="json"),
            input_refs=[
                {"type": "ScientificCapabilityReport", "id": capability_ref},
                {
                    "type": "MachineProfileSnapshot",
                    "id": self._latest_artifact_id(bus, "MachineProfileSnapshot"),
                },
            ],
            schema_version=need_set.schema_version,
        )
        need_counts = {
            str(need_type): len(need_set.needs_of(need_type))
            for need_type in ScientificNeedType
        }
        trace.validation(
            (
                f"科学需求：{len(need_set.needs)} 条"
                f"（资源 {need_counts[ScientificNeedType.RESOURCE_INPUT]} /"
                f" 文献 {need_counts[ScientificNeedType.SCIENTIFIC_KNOWLEDGE]} /"
                f" 观测 {need_counts[ScientificNeedType.CALIBRATION_OBSERVATION]} /"
                f" 数据 {need_counts[ScientificNeedType.TARGET_DATA]}）"
            ),
            counts=need_counts,
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
        artifact_id = self._persist_artifact(
            bus.run_id,
            "KnowledgeRequirementSet",
            {"requirements": requirements, "diagnostics": diagnostics},
            input_refs=[
                {"type": "ScientificCapabilityReport", "id": capability_ref},
                {"type": "DataProfile", "id": self._latest_artifact_id(bus, "DataProfile")},
                {"type": "ScientificNeedSet", "id": need_set_artifact},
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
            f"科学需求清单生成（{need_set_artifact}）",
            output_refs=[
                {"type": "ScientificNeedSet", "id": need_set_artifact},
                {"type": "KnowledgeRequirementSet", "id": artifact_id},
            ],
            counts={"needs": len(need_set.needs), "requirements": len(requirements)},
        )
        trace.artifact_created(
            "ScientificNeedSet",
            need_set_artifact,
            input_refs=[{"type": "ScientificCapabilityReport", "id": capability_ref}],
            counts=need_counts,
        )
        trace.artifact_created(
            "KnowledgeRequirementSet",
            artifact_id,
            input_refs=[{"type": "ScientificCapabilityReport", "id": capability_ref}],
        )
        return {
            "meta": {
                "artifact_id": artifact_id,
                "need_set_artifact_id": need_set_artifact,
                "compatibility_artifact_id": legacy_artifact_id,
                "requirement_count": len(requirements),
                "need_counts": need_counts,
            },
            "content": {
                "requirements": requirements,
                "diagnostics": diagnostics,
                "scientific_needs": need_set.model_dump(mode="json"),
            },
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
        """Stage 5: knowledge preparation with the canonical resolution chain.

        M3: KnowledgeRequirement -> QueryPlan -> Corpus -> LLM reading
        (cache-first) -> validation -> EvidenceIR -> applicability.  The old
        agent RAG evidence route is removed from the primary path.
        """
        trace = ScientificTrace(bus, "prepare_knowledge")
        requirements = self._latest_requirements(bus)
        query_plans = [
            plan_retrieval(requirement, scope.model_dump(mode="json")).model_dump(mode="json")
            for requirement in requirements
        ]
        query_plan_artifact = self._persist_artifact(
            bus.run_id,
            "RequirementRetrievalPlan",
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
            "RequirementRetrievalPlan",
            query_plan_artifact,
            counts={"requirements": len(requirements), "query_plans": len(query_plans)},
        )
        execution_mode = effective_execution_mode("research", task_spec)
        resolution: dict[str, Any] | None = None
        if execution_mode in ("RESEARCH", "DEMO_FIXTURE"):
            trace.operation_started(
                "requirement-resolution",
                "需求解析（语料构建 → LLM 精读 → 验证 → 条件链 → EvidenceIR）",
                input_refs=[
                    {
                        "type": "RequirementRetrievalPlan",
                        "id": query_plan_artifact,
                    }
                ],
            )
            try:
                resolution = resolve_requirement_chain(
                    scope.model_dump(mode="json"),
                    requirements,
                    execution_mode=execution_mode,
                    llm_client=self.resolution_llm_client,
                    model=self.resolution_model,
                    progress_callback=self._resolution_progress(bus),
                ).to_dict()
            except Exception as exc:  # noqa: BLE001 - fail closed with honest warning
                bus.emit(
                    WARNING,
                    f"需求解析失败（fail closed）：{exc}",
                    stage="prepare_knowledge",
                )
                trace.warning(f"需求解析失败：{exc}")
            if resolution:
                # 阶段一 · 手册 §9: 五个独立冻结 artifact，Artifact → Service → Artifact
                corpus_mapping = resolution.get("mapping_report") or {}
                corpus_from_cache = int(corpus_mapping.get("from_cache") or 0)
                corpus_completed = int(corpus_mapping.get("completed") or 0)
                corpus_sources = len(
                    (resolution.get("corpus_pack") or {}).get("sources") or []
                )
                if corpus_sources == 0:
                    analysis_method = "NO_CORPUS"
                elif corpus_completed == 0 and corpus_from_cache == 0:
                    analysis_method = "PENDING_LLM"
                elif corpus_completed == corpus_from_cache:
                    analysis_method = "LLM_CACHED"
                else:
                    analysis_method = "LLM_LIVE"
                corpus_pack_artifact = self._persist_artifact(
                    bus.run_id,
                    "ScientificCorpusPack",
                    {
                        "schema_version": "evidence-corpus-pack-v1",
                        "corpus_pack": resolution.get("corpus_pack") or {},
                        "analysis_mapping": corpus_mapping,
                        "analysis_model": self.resolution_model,
                        "analysis_method": analysis_method,
                    },
                    input_refs=[
                        {
                            "type": "RequirementRetrievalPlan",
                            "id": query_plan_artifact,
                        }
                    ],
                )
                ledger_artifact = self._persist_artifact(
                    bus.run_id,
                    "CandidateLedger",
                    resolution.get("candidate_ledger") or {},
                    input_refs=[
                        {
                            "type": "ScientificCorpusPack",
                            "id": corpus_pack_artifact,
                        }
                    ],
                    schema_version="candidate-ledger-v0.1",
                )
                conditions_artifact = self._persist_artifact(
                    bus.run_id,
                    "SourceConditionSet",
                    {
                        "schema_version": "source-condition-set-v1",
                        "conditions": resolution.get("source_conditions") or [],
                    },
                    input_refs=[
                        {"type": "CandidateLedger", "id": ledger_artifact},
                        {"type": "ScientificCorpusPack", "id": corpus_pack_artifact},
                    ],
                )
                reconstructibility_artifact = self._persist_artifact(
                    bus.run_id,
                    "ReconstructibilityReportSet",
                    {
                        "schema_version": "reconstructibility-report-set-v1",
                        "reports": resolution.get("reconstructibility_reports") or [],
                    },
                    input_refs=[
                        {"type": "SourceConditionSet", "id": conditions_artifact}
                    ],
                )
                applicability_artifact = self._persist_artifact(
                    bus.run_id,
                    "ApplicabilityReportSet",
                    {
                        "schema_version": "applicability-report-set-v1",
                        "items": resolution.get("applicability") or [],
                    },
                    input_refs=[
                        {
                            "type": "ReconstructibilityReportSet",
                            "id": reconstructibility_artifact,
                        }
                    ],
                )
                trace.artifact_created(
                    "ScientificCorpusPack",
                    corpus_pack_artifact,
                    counts={
                        "sources": len(
                            (resolution.get("corpus_pack") or {}).get("sources") or []
                        ),
                        "candidates": len(
                            (resolution.get("knowledge_pack") or {}).get("candidates")
                            or []
                        ),
                    },
                )
                trace.artifact_created(
                    "CandidateLedger",
                    ledger_artifact,
                    counts={
                        "candidates": len(
                            (resolution.get("candidate_ledger") or {}).get(
                                "candidates"
                            )
                            or []
                        )
                    },
                )
                trace.artifact_created(
                    "SourceConditionSet",
                    conditions_artifact,
                    counts={
                        "conditions": len(resolution.get("source_conditions") or [])
                    },
                )
                trace.artifact_created(
                    "ReconstructibilityReportSet",
                    reconstructibility_artifact,
                    counts={
                        "reports": len(
                            resolution.get("reconstructibility_reports") or []
                        )
                    },
                )
                trace.artifact_created(
                    "ApplicabilityReportSet",
                    applicability_artifact,
                    counts={
                        "items": len(resolution.get("applicability") or [])
                    },
                )
                trace.operation_completed(
                    "requirement-resolution",
                    (
                        f"需求解析完成：{len(resolution['evidence_ir'])} 条 Evidence"
                        f"（{resolution['mapping_report'].get('from_cache', 0)} 条来自预录缓存）"
                        if resolution.get("evidence_ir")
                        else "需求解析完成：0 条 Evidence（语料/验证无产出）"
                    ),
                    output_refs=[
                        {"type": "ScientificCorpusPack", "id": corpus_pack_artifact},
                        {"type": "CandidateLedger", "id": ledger_artifact},
                        {"type": "SourceConditionSet", "id": conditions_artifact},
                        {
                            "type": "ReconstructibilityReportSet",
                            "id": reconstructibility_artifact,
                        },
                    ],
                    counts={
                        "evidence": len(resolution.get("evidence_ir") or []),
                        "candidates": len(
                            (resolution.get("knowledge_pack") or {}).get("candidates")
                            or []
                        ),
                        "conditions": len(resolution.get("source_conditions") or []),
                        "reports": len(
                            resolution.get("reconstructibility_reports") or []
                        ),
                        "rejected": len(
                            (resolution.get("validation") or {}).get(
                                "rejected_candidates"
                            )
                            or []
                        ),
                    },
                )
        # sub-operation 1: existing knowledge check (persisted evidence only)
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
        # sub-operation 2: literature retrieval (resolution chain)
        trace.operation_started(
            "prepare-literature-retrieval",
            "文献检索（RequirementResolutionService）",
            input_refs=[
                {
                    "type": "RequirementRetrievalPlan",
                    "id": query_plan_artifact,
                }
            ],
        )
        resolution_evidence = list((resolution or {}).get("evidence_ir") or [])
        trace.operation_completed(
            "prepare-literature-retrieval",
            f"文献证据：{len(resolution_evidence)} 条",
            counts={"retrieved": len(resolution_evidence)},
            reason_codes=(
                ["requirement_resolution_chain"]
                if resolution_evidence
                else ["no_sources_or_no_validated_candidates"]
            ),
        )
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
        # Canonical EvidenceIR is produced only by RequirementResolution.
        # Legacy repository evidence stays visible in ExistingKnowledgeSummary
        # but never bypasses Candidate -> Condition -> Applicability.
        evidence_ir = list(resolution_evidence)
        if execution_mode == "SANDBOX":
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
                "ledger_ref": (
                    self._latest_artifact_id(bus, "CandidateLedger")
                    if resolution
                    else None
                ),
                "condition_set_ref": (
                    self._latest_artifact_id(bus, "SourceConditionSet")
                    if resolution
                    else None
                ),
                "reconstructibility_set_ref": (
                    self._latest_artifact_id(bus, "ReconstructibilityReportSet")
                    if resolution
                    else None
                ),
            },
            input_refs=[
                {"type": "RequirementRetrievalPlan", "id": query_plan_artifact},
                {"type": "EvidenceCompileResult", "id": artifact_id},
                *(
                    [
                        {
                            "type": "CandidateLedger",
                            "id": self._latest_artifact_id(bus, "CandidateLedger"),
                        },
                        {
                            "type": "SourceConditionSet",
                            "id": self._latest_artifact_id(bus, "SourceConditionSet"),
                        },
                        {
                            "type": "ReconstructibilityReportSet",
                            "id": self._latest_artifact_id(
                                bus, "ReconstructibilityReportSet"
                            ),
                        },
                    ]
                    if resolution
                    else []
                ),
            ],
            schema_version="evidence-ir-set-v1",
        )
        trace.artifact_created(
            "EvidenceIRSet",
            evidence_ir_artifact,
            input_refs=[
                {"type": "RequirementRetrievalPlan", "id": query_plan_artifact}
            ],
            counts={"evidence": len(evidence_ir)},
        )
        # typed PriorObjectSet compiled here (阶段二 T5): Gate B consumes it
        # before calibrate_physics, so priors must exist by the end of
        # prepare_knowledge — not inside calibrate_physics.
        trace.operation_started(
            "compile-typed-priors",
            "EvidenceIR 编译为 typed PriorObject",
            input_refs=[{"type": "EvidenceIRSet", "id": evidence_ir_artifact}],
        )
        bus.emit(
            VALIDATION,
            f"先验编译: {len(evidence_ir)} 条证据",
            stage="prepare_knowledge",
            details={"phase": "compiling_prior", "evidence": len(evidence_ir)},
        )
        applicability_refs = {
            str(item.get("evidence_id")): str(item.get("applicability_report_id"))
            for item in ((resolution or {}).get("applicability") or [])
            if item.get("evidence_id") and item.get("applicability_report_id")
        }
        prior_set = compile_typed_priors(
            evidence_ir,
            applicability_refs=applicability_refs,
        )
        prior_set = self._merge_demo_fixture_priors(
            prior_set,
            execution_mode=execution_mode,
            task_spec=task_spec,
            scope=scope,
        )
        prior_set_artifact = self._persist_artifact(
            bus.run_id,
            "PriorObjectSet",
            prior_set.model_dump(mode="json"),
            input_refs=[
                {"type": "EvidenceIRSet", "id": evidence_ir_artifact},
                *(
                    [
                        {
                            "type": "ApplicabilityReportSet",
                            "id": self._latest_artifact_id(bus, "ApplicabilityReportSet"),
                        }
                    ]
                    if resolution
                    else []
                ),
            ],
            schema_version=prior_set.schema_version,
        )
        trace.operation_completed(
            "compile-typed-priors",
            f"typed Prior 编译完成（{prior_set_artifact}）",
            output_refs=[{"type": "PriorObjectSet", "id": prior_set_artifact}],
            counts={
                "priors": len(prior_set.priors),
                "conflicts": len(prior_set.conflicts),
            },
        )
        trace.artifact_created(
            "PriorObjectSet",
            prior_set_artifact,
            input_refs=[{"type": "EvidenceIRSet", "id": evidence_ir_artifact}],
        )
        return {
            "meta": {
                "artifact_id": artifact_id,
                "query_plan_artifact_id": query_plan_artifact,
                "evidence_ir_artifact_id": evidence_ir_artifact,
                "prior_set_artifact_id": prior_set_artifact,
                "evidence_count": accepted_count,
            },
            "content": {
                "bundle": bundle,
                "query_plans": query_plans,
                "evidence_ir": evidence_ir,
                "evidence_count": len(evidence),
                "existing_knowledge": existing,
                "resolution": resolution,
            },
        }

    def _resolution_progress(
        self, bus: WorkflowEventBus
    ) -> Callable[[str, dict[str, Any]], None]:
        """Map resolution chain progress to requirement-scoped workflow events
        (阶段三 T3): retrieving / selecting / reading / validating /
        compiling_ledger / compiling_conditions / assessing_reconstructibility /
        assessing_applicability — every event carries requirement_ids."""

        def emit_phase(stage: str, label: str, detail: dict[str, Any]) -> None:
            bus.emit(
                VALIDATION,
                label,
                stage="prepare_knowledge",
                details={"phase": stage, **detail},
            )

        def on_progress(stage: str, detail: dict[str, Any]) -> None:
            requirement_ids = [
                str(item) for item in (detail.get("requirement_ids") or [])
            ]
            if stage == "retrieving":
                emit_phase(
                    stage,
                    f"检索: {detail.get('hits', 0)} 命中 / {detail.get('papers', 0)} 篇候选",
                    {"requirement_ids": requirement_ids, **detail},
                )
            elif stage == "selecting":
                emit_phase(
                    stage,
                    f"选文: {detail.get('sources', 0)} 篇进入语料包",
                    {"requirement_ids": requirement_ids, **detail},
                )
            elif stage == "mapping":
                current = detail.get("current") or 0
                total = detail.get("total") or 0
                cached = bool(detail.get("cached"))
                emit_phase(
                    stage,
                    f"LLM 精读 {current}/{total}" + ("（预录缓存）" if cached else ""),
                    {
                        "requirement_ids": requirement_ids,
                        "current": current,
                        "total": total,
                        "cached": cached,
                    },
                )
            elif stage == "validating":
                emit_phase(
                    stage,
                    f"确定性验证：{detail.get('validated', 0)} 通过 / {detail.get('rejected', 0)} 拒绝",
                    {"requirement_ids": requirement_ids, **detail},
                )
            elif stage == "compiling_ledger":
                emit_phase(
                    stage,
                    f"候选账本: {detail.get('candidates', 0)} 条",
                    {"requirement_ids": requirement_ids, **detail},
                )
            elif stage == "compiling_conditions":
                emit_phase(
                    stage,
                    f"条件编译: {detail.get('candidates', 0)} 条候选",
                    {"requirement_ids": requirement_ids, **detail},
                )
            elif stage == "assessing_reconstructibility":
                emit_phase(
                    stage,
                    f"可重建性评估: {detail.get('conditions', 0)} 组条件",
                    {"requirement_ids": requirement_ids, **detail},
                )
            elif stage == "assessing_applicability":
                emit_phase(
                    stage,
                    f"适用性评估: {detail.get('evidence', 0)} 条证据",
                    {"requirement_ids": requirement_ids, **detail},
                )

        return on_progress

    def _stage_satisfy_requirements(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """EvidenceIRSet + PriorObjectSet -> authoritative KnowledgeState."""
        requirements = self._latest_requirements(bus)
        evidence_set = self._latest_artifact_content(bus, "EvidenceIRSet") or {}
        evidence_items = [
            dict(item)
            for item in evidence_set.get("items") or []
            if isinstance(item, dict)
        ]
        prior_set = self._latest_artifact_content(bus, "PriorObjectSet") or {}
        priors = [
            dict(item)
            for item in prior_set.get("priors") or []
            if isinstance(item, dict)
        ]
        conflict_prior_ids = {
            str(ref.get("id"))
            for conflict in prior_set.get("conflicts") or []
            for ref in conflict.get("prior_refs") or []
            if isinstance(ref, dict) and ref.get("id")
        }
        prior_by_evidence: dict[str, list[dict[str, Any]]] = {}
        for prior in priors:
            for ref in prior.get("evidence_refs") or []:
                if isinstance(ref, dict) and ref.get("id"):
                    prior_by_evidence.setdefault(str(ref["id"]), []).append(prior)
        bus.emit(
            VALIDATION,
            f"需求满足评估: {len(requirements)} 条需求",
            stage="satisfy_requirements",
            details={"phase": "evaluating_satisfaction", "requirements": len(requirements)},
        )
        accepted_reviews = {
            "approved",
            "accepted",
            "accepted_as_literature_evidence",
            "governed",
        }
        observation_ids = [
            artifact_id for artifact_id, _ in self._artifact_contents(bus, "Observation")
        ]
        observation_capabilities = self._observation_capabilities(
            scope, task_spec, bus
        )
        satisfactions: list[dict[str, Any]] = []
        resolved_requirements: list[dict[str, Any]] = []
        for requirement in requirements:
            requirement_id = str(requirement["requirement_id"])
            roles = {
                str(role) for role in requirement.get("required_evidence_roles") or []
            }
            matching = [
                item
                for item in evidence_items
                if str(item.get("review_status") or "").lower() in accepted_reviews
                and (
                    requirement_id
                    in {str(value) for value in item.get("requirement_ids") or []}
                    or (
                        not item.get("requirement_ids")
                        and str(item.get("claim_type") or "") in roles
                    )
                )
            ]
            evidence_ids = {
                str(item.get("evidence_id"))
                for item in matching
                if item.get("evidence_id")
            }
            matching_priors = [
                prior
                for evidence_id in evidence_ids
                for prior in prior_by_evidence.get(evidence_id, [])
            ]
            prior_ids = {
                str(prior.get("prior_id"))
                for prior in matching_priors
                if prior.get("prior_id")
            }
            basis = sorted({*evidence_ids, *prior_ids})
            reasons: list[str] = []
            if not roles:
                reasons.append("该需求不由文献或 PriorObject 满足")
                status = "UNSATISFIED"
            elif (
                str(requirement.get("type") or "") == "PARAMETER_PRIOR"
                and "F_th_eff" in observation_capabilities
            ):
                status = "SATISFIED"
                basis = sorted({*basis, *observation_ids})
            elif prior_ids.intersection(conflict_prior_ids):
                status = "SATISFIED_WITH_CONFLICT"
                reasons.append("匹配先验存在未解决冲突；禁止静默平均")
            elif matching_priors:
                status = "SATISFIED"
            elif matching:
                status = "PARTIALLY_SATISFIED"
                reasons.append("匹配 EvidenceIR 尚未编译成可消费 PriorObject")
            else:
                status = "UNSATISFIED"
                reasons.append(
                    f"无匹配 EvidenceIR（需要 claim_type ∈ {sorted(roles)}）"
                )
            satisfactions.append(
                {
                    "requirement_id": requirement_id,
                    "status": status,
                    "assessment_method": "DETERMINISTIC_PROVISIONAL",
                    "assessment_version": "satisfaction-v1",
                    "basis_refs": basis,
                    "unresolved_reasons": reasons,
                }
            )
            resolved_requirements.append(
                {
                    **dict(requirement),
                    "status": {
                        "SATISFIED": "KNOWN",
                        "PARTIALLY_SATISFIED": "PARTIAL",
                        "SATISFIED_WITH_CONFLICT": "MISMATCH",
                        "UNSATISFIED": "UNKNOWN",
                    }[status],
                }
            )
        missing_topics = [
            requirement["requirement_id"]
            for requirement, satisfaction in zip(resolved_requirements, satisfactions)
            if satisfaction["status"] == "UNSATISFIED"
        ]
        corpus = self._latest_artifact_content(bus, "ScientificCorpusPack") or {}
        ledger = self._latest_artifact_content(bus, "CandidateLedger") or {}
        accepted_types = {
            str(item.get("claim_type"))
            for item in evidence_items
            if item.get("claim_type")
        }
        knowledge_state = {
            "requirements": resolved_requirements,
            "satisfactions": satisfactions,
            "existing_knowledge": {
                "evidence_count": len(evidence_items),
                "governed_evidence_count": len(prior_by_evidence),
                "candidate_count": len(ledger.get("candidates") or []),
                "paper_count": len(
                    (corpus.get("corpus_pack") or {}).get("sources") or []
                ),
                "topics": sorted(accepted_types),
            },
            "missing_topics": missing_topics,
            "assessment_version": "knowledge-state-v1",
        }
        knowledge_state = KnowledgeState.model_validate(knowledge_state).model_dump(
            mode="json"
        )
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
                    "type": "EvidenceIRSet",
                    "id": self._latest_artifact_id(bus, "EvidenceIRSet"),
                },
                {
                    "type": "PriorObjectSet",
                    "id": self._latest_artifact_id(bus, "PriorObjectSet"),
                },
                {
                    "type": "ApplicabilityReportSet",
                    "id": self._latest_artifact_id(bus, "ApplicabilityReportSet"),
                },
                *(
                    {"type": "Observation", "id": artifact_id}
                    for artifact_id in observation_ids
                ),
            ],
            schema_version="knowledge-state-v1",
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

    def _artifact_contents(
        self, bus: WorkflowEventBus, artifact_type: str
    ) -> list[tuple[str, dict[str, Any]]]:
        items: list[tuple[str, dict[str, Any]]] = []
        for artifact in self.repository.list_application_artifacts(bus.run_id):
            if artifact["artifact_type"] != artifact_type:
                continue
            stored = self.repository.application_artifact(artifact["artifact_id"])
            snapshot = (stored or {}).get("content") or {}
            content = snapshot.get("content")
            if isinstance(content, dict):
                items.append((str(artifact["artifact_id"]), dict(content)))
        return items

    def _machine_snapshot(self, bus: WorkflowEventBus) -> dict[str, Any]:
        """Canonical MachineProfileSnapshot artifact for this run."""
        return self._latest_artifact_content(bus, "MachineProfileSnapshot") or {}

    def _execution_context(self, bus: WorkflowEventBus) -> dict[str, Any]:
        """Verified task setpoints, kept separate from equipment capability."""
        return self._latest_artifact_content(bus, "ExecutionContext") or {}

    @staticmethod
    def _build_execution_context(
        task_spec: dict[str, Any], machine_snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        process = task_spec.get("process_parameters") or {}
        raw_value = process.get("laser_power_W")
        location = str(process.get("laser_power_location") or "")
        bound = (machine_snapshot.get("machine_bounds") or {}).get("laser_power_W") or {}
        lower, upper = bound.get("lower"), bound.get("upper")
        reasons: list[str] = []
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = None
        if value is None or value <= 0:
            reasons.append("laser_power_W 缺失或不是正数")
        if location != "WORKPIECE_SURFACE_INCIDENT":
            reasons.append("laser_power_location 必须为 WORKPIECE_SURFACE_INCIDENT")
        if lower is None or upper is None:
            reasons.append("设备版本缺少材料表面入射平均功率边界")
        elif value is not None and not (float(lower) <= value <= float(upper)):
            reasons.append(
                f"laser_power_W={value:g} W 超出设备实测边界 [{float(lower):g}, {float(upper):g}] W"
            )
        if machine_snapshot.get("resource_status") != "READY":
            reasons.append("设备版本尚未达到 READY")
        return {
            "schema_version": "execution-context-v1",
            "status": "READY" if not reasons else "BLOCKED",
            "setpoints": {
                "laser_power_W": {
                    "value": value,
                    "unit": "W",
                    "location": "WORKPIECE_SURFACE_INCIDENT",
                    "status": "VERIFIED" if not reasons else "UNVERIFIED",
                    "source": "task_spec.process_parameters.laser_power_W",
                }
            },
            "bounds": (
                {"laser_power_W": {"lower": float(lower), "upper": float(upper)}}
                if lower is not None and upper is not None
                else {}
            ),
            "reasons": reasons,
            "equipment_profile_id": machine_snapshot.get("equipment_profile_id"),
            "revision_id": machine_snapshot.get("revision_id"),
        }

    def _machine_fields(self, bus: WorkflowEventBus) -> dict[str, Any]:
        """Verified machine facts for physics - snapshot only, never task_spec."""
        snapshot = self._machine_snapshot(bus)
        fields = snapshot.get("fields") or {}
        values = {
            str(state.get("parameter")): state["value"]
            for state in fields.values()
            if isinstance(state, dict)
            and state.get("value") is not None
            and state.get("status") in ("VERIFIED", "DERIVED")
        }
        execution = self._execution_context(bus)
        power = ((execution.get("setpoints") or {}).get("laser_power_W") or {})
        if execution.get("status") == "READY" and power.get("status") == "VERIFIED":
            values["actual_power_W"] = power.get("value")
            values["laser_power_W"] = power.get("value")
        return values

    def _machine_capability_fields(self, bus: WorkflowEventBus) -> dict[str, Any]:
        """Verified values plus explicit verification flags for preflight.

        ScientificCapabilityAnalyzer deliberately treats a bare numeric machine
        value as UNVERIFIED.  Preserve the MachineProfileSnapshot decision when
        adapting the artifact into that analyzer instead of silently dropping
        its field status.
        """
        snapshot = self._machine_snapshot(bus)
        fields = snapshot.get("fields") or {}
        values: dict[str, Any] = {}
        for state in fields.values():
            if not isinstance(state, dict):
                continue
            parameter = str(state.get("parameter") or "")
            value = state.get("value")
            if (
                not parameter
                or value is None
                or state.get("status") not in ("VERIFIED", "DERIVED")
            ):
                continue
            values[parameter] = value
            values[f"{parameter}_verified"] = True
        execution = self._execution_context(bus)
        power = ((execution.get("setpoints") or {}).get("laser_power_W") or {})
        if execution.get("status") == "READY" and power.get("status") == "VERIFIED":
            values["actual_power_W"] = power.get("value")
            values["actual_power_W_verified"] = True
            values["laser_power_W"] = power.get("value")
            values["laser_power_W_verified"] = True
        return values

    def _merge_demo_fixture_priors(
        self,
        prior_set: PriorObjectSet,
        *,
        execution_mode: str,
        task_spec: dict[str, Any],
        scope: TaskScope,
    ) -> PriorObjectSet:
        """DEMO_FIXTURE only: merge explicit fixture priors (阶段二 T4).

        Fixture priors carry a DemoFixturePrior provenance ref so downstream
        bindings can distinguish DEMO_FIXTURE from LITERATURE_PRIOR.  Never
        merged in RESEARCH mode - missing priors stay missing.
        """
        if execution_mode != "DEMO_FIXTURE":
            return prior_set
        requested_ref = str(task_spec.get("prior_set_ref") or "").strip()
        if not requested_ref:
            return prior_set
        fixture_path = self.settings.prior_fixture_path
        if fixture_path is None or not Path(fixture_path).exists():
            return prior_set
        try:
            payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return prior_set
        execution_profile_id, _ = self._execution_equipment_ref(task_spec, scope)
        if (
            str(payload.get("prior_set_id") or "") != requested_ref
            or str(payload.get("equipment_profile_id") or "")
            != execution_profile_id
            or str(payload.get("material") or "") != scope.material
        ):
            return prior_set
        existing = {
            str(item.parameter)
            for item in prior_set.priors
            if isinstance(item, ParameterPrior)
        }
        added: list[ParameterPrior] = []
        for item in payload.get("priors") or []:
            parameter = str(item.get("parameter") or "")
            if not parameter or parameter in existing:
                continue
            from packages.e2p.domain.prior_objects import (
                PriorRef,
                PriorStatus,
                PriorUncertainty,
            )

            prior_ref = PriorRef(
                type="DemoFixturePrior",
                id=str(item.get("prior_id") or f"demo-fixture-{parameter}"),
            )
            added.append(
                ParameterPrior(
                    prior_id=f"demo-fixture-prior-{parameter}",
                    parameter=parameter,
                    lower=float(item["lower"]),
                    upper=float(item["upper"]),
                    unit=str(item.get("unit") or ""),
                    parameter_semantics=str(
                        item.get("parameter_semantics") or "PROVISIONAL"
                    ),
                    assumptions=[
                        "DEMO_FIXTURE fixture prior - explicit, not hardcoded"
                    ],
                    input_refs=[prior_ref],
                    evidence_refs=[prior_ref],
                    provenance=[prior_ref],
                    uncertainty=PriorUncertainty.LOW,
                    status=PriorStatus.EXTERNAL_PRIOR,
                )
            )
        if not added:
            return prior_set
        return prior_set.model_copy(
            update={"priors": [*prior_set.priors, *added]}
        )

    def _calibration_fixture_payload(self) -> dict[str, Any]:
        """Read the declared DEMO observation resource; never infer its identity."""
        fixture_path = self.settings.calibration_fixture_path
        if fixture_path is None or not Path(fixture_path).exists():
            return {}
        try:
            payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _resolve_task_observations(
        self,
        task_spec: dict[str, Any],
        scope: TaskScope,
        *,
        execution_mode: str,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        if execution_mode == "SANDBOX" and task_spec.get("calibration_observations"):
            return "sandbox-task-observations", [
                dict(item) for item in task_spec.get("calibration_observations") or []
            ]
        resource_ref = str(
            task_spec.get("calibration_observation_set_ref") or ""
        ).strip()
        if not resource_ref:
            return None, []
        if execution_mode != "DEMO_FIXTURE":
            # Research observations must eventually resolve through a research
            # repository.  A local demo fixture is never a research fallback.
            return None, []
        payload = self._calibration_fixture_payload()
        if str(payload.get("observation_set_id") or "") != resource_ref:
            return None, []
        execution_profile_id, _ = self._execution_equipment_ref(task_spec, scope)
        if str(payload.get("equipment_profile_id") or "") != execution_profile_id:
            return None, []
        if str(payload.get("material") or "") != scope.material:
            return None, []
        return resource_ref, [dict(item) for item in payload.get("observations") or []]

    def _persist_task_observations(
        self,
        task_spec: dict[str, Any],
        scope: TaskScope,
        bus: WorkflowEventBus,
        *,
        execution_mode: str,
    ) -> tuple[str | None, list[str]]:
        resource_ref, raw_items = self._resolve_task_observations(
            task_spec,
            scope,
            execution_mode=execution_mode,
        )
        if not raw_items:
            return None, []
        validated = [ParameterObservation.model_validate(item) for item in raw_items]
        set_artifact = self._persist_artifact(
            bus.run_id,
            "CalibrationObservationSet",
            {
                "schema_version": "calibration-observations-v1",
                "observation_set_id": resource_ref,
                "source_quality": (
                    "SYNTHETIC_TEST_FIXTURE"
                    if execution_mode != "SANDBOX"
                    else "SANDBOX_TASK_OVERRIDE"
                ),
                "count": len(validated),
            },
            input_refs=[
                {"type": "CalibrationObservationResource", "id": resource_ref or "sandbox"}
            ],
            schema_version="calibration-observations-v1",
        )
        artifact_ids: list[str] = []
        for observation in validated:
            original_ref = observation.data_ref
            content = {
                "schema_version": "parameter-observation-v1",
                **observation.model_dump(mode="json"),
                "source_data_ref": original_ref,
                "observation_set_ref": set_artifact,
            }
            artifact_id = self._persist_artifact(
                bus.run_id,
                "Observation",
                content,
                input_refs=[
                    {"type": "CalibrationObservationSet", "id": set_artifact}
                ],
                schema_version="parameter-observation-v1",
            )
            artifact_ids.append(artifact_id)
        return set_artifact, artifact_ids

    def _parameter_observations(
        self, bus: WorkflowEventBus
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for artifact_id, content in self._artifact_contents(bus, "Observation"):
            raw = {
                key: content.get(key)
                for key in ParameterObservation.model_fields
            }
            raw["data_ref"] = artifact_id
            observations.append(
                ParameterObservation.model_validate(raw).model_dump(mode="json")
            )
        return observations

    def _evidence_for_scope(self, scope: TaskScope) -> list[Evidence]:
        """Existing (persisted) evidence only - canonical literature evidence
        enters via the RequirementResolutionService chain in prepare_knowledge."""
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
            except Exception:  # noqa: BLE001,S112 - malformed evidence row skipped
                continue
            seen.add(item.evidence_id)
            items.append(item)
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
        self,
        rows: list[dict[str, Any]],
        scope: TaskScope,
        *,
        spot_diameter_um: float | None = None,
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
        except Exception as exc:  # noqa: BLE001 - readiness must fail closed
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
            if spot_diameter_um is None:
                spot_diameter_um = self._agent_spot_diameter_um()
            spec = build_target_condition_spec(
                tmp_path,
                equipment_profile={
                    "spot_radius_um": (spot_diameter_um / 2.0, "um", False),
                    "spot_diameter_um": (spot_diameter_um, "um", False),
                }
                if spot_diameter_um
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
        except Exception as exc:  # noqa: BLE001 - readiness must fail closed
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
        except Exception:  # noqa: BLE001 - optional agent lookup
            return None
        diameter = bounds.get("spot_diameter_um")
        if isinstance(diameter, (list, tuple)) and len(diameter) == 2:
            return float(diameter[0])
        return None

    def _stage_calibrate_physics(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Independent parameter ID over the typed Priors compiled in
        prepare_knowledge (PriorObjectSet artifact)."""
        trace = ScientificTrace(bus, "calibrate_physics")
        rows = self.topic2._rows_for_scope(scope)
        machine = self._machine_fields(bus)

        def median(name: str) -> float | None:
            values = sorted(float(row[name]) for row in rows if row.get(name) is not None)
            return values[len(values) // 2] if values else None

        canonical_inputs: dict[str, float | int | None] = {
            "average_power_W": machine.get("actual_power_W"),
            "frequency_kHz": median("frequency_kHz"),
            "pulse_width_ps": median("pulse_width_ps"),
            "scan_speed_mm_s": median("scan_speed_mm_s"),
            "hatch_spacing_um": median("hatch_spacing_um"),
            "beam_radius_um": machine.get("beam_radius_um"),
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
                or name in ("average_power_W", "beam_radius_um")
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
        prior_set_artifact = self._latest_artifact_id(bus, "PriorObjectSet")
        prior_payload = self._latest_artifact_content(bus, "PriorObjectSet") or {}
        prior_set = PriorObjectSet.model_validate(prior_payload)

        parameter_priors = [item for item in prior_set.priors if isinstance(item, ParameterPrior)]
        data_profile_id = self._latest_artifact_id(bus, "DataProfile")
        observation_artifact_ids = [
            artifact_id for artifact_id, _ in self._artifact_contents(bus, "Observation")
        ]
        observation_refs = [
            {"type": "Observation", "id": artifact_id}
            for artifact_id in observation_artifact_ids
        ]
        trace.operation_started(
            "parameter-identification-v1",
            "有界多起点参数辨识与可辨识性审计",
            input_refs=[
                {"type": "DataProfile", "id": data_profile_id},
                {"type": "PriorObjectSet", "id": prior_set_artifact},
                {"type": "CanonicalPhysicsState", "id": canonical_artifact},
                *observation_refs,
            ],
        )
        engine = ParameterIdentificationEngine()
        observations = self._parameter_observations(bus)
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
                    *(
                        ArtifactRef(type="Observation", id=artifact_id)
                        for artifact_id in observation_artifact_ids
                    ),
                ],
            )
        else:
            identifiability, calibration = engine.identify_from_macro_rows(
                self.topic2._rows_for_scope(scope),
                input_refs=[
                    ArtifactRef(type="DataProfile", id=data_profile_id),
                    ArtifactRef(type="PriorObjectSet", id=prior_set_artifact),
                    ArtifactRef(type="CanonicalPhysicsState", id=canonical_artifact),
                    *(
                        ArtifactRef(type="Observation", id=artifact_id)
                        for artifact_id in observation_artifact_ids
                    ),
                ],
            )
        ident_artifact = self._persist_artifact(
            bus.run_id,
            "IdentifiabilityReport",
            identifiability.model_dump(mode="json"),
            input_refs=[
                {"type": "DataProfile", "id": data_profile_id},
                {"type": "PriorObjectSet", "id": prior_set_artifact},
                *observation_refs,
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
                    *(
                        ArtifactRef(type="Observation", id=artifact_id)
                        for artifact_id in observation_artifact_ids
                    ),
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
                *observation_refs,
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
            machine = self._machine_fields(bus)
            model = factory.reconstructed(
                calibration=calibration,
                parameter_priors=parameter_priors,
                mechanism_priors=mechanism_priors,
                beam_radius_um=machine.get("beam_radius_um"),
                grid_spacing_um=float((task_spec.get("target_geometry") or {}).get("grid_spacing_um") or 2.0),
                allow_computational_defaults=(
                    effective_execution_mode("research", task_spec) == "SANDBOX"
                ),
                input_refs=refs,
            )
        model_artifact = self._persist_artifact(
            bus.run_id,
            "LocalRemovalModel",
            model.model_dump(mode="json"),
            input_refs=[item.model_dump(mode="json") for item in refs],
            schema_version=model.schema_version,
        )
        inactive = {
            str(item.get("mechanism"))
            for item in model.inactive_mechanisms
        }
        runnable_fidelity = (
            SimulationFidelity.F1_INCUBATION
            if "DEFOCUS_RECURSION" in inactive
            else SimulationFidelity.F2_DEFOCUS_RECURSION
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
            simulator_fidelity=runnable_fidelity,
            uncertainty_status=ScientificStatus.PARTIAL,
            assumptions=[
                *list(model.assumptions),
                *(
                    f"fidelity downgraded to {runnable_fidelity.value}: "
                    f"DEFOCUS_RECURSION inactive ({item.get('reason')})"
                    for item in model.inactive_mechanisms
                    if item.get("mechanism") == "DEFOCUS_RECURSION"
                ),
            ],
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

    def _stage_simulate_morphology(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """TargetGeometry -> parameterized candidates -> morphology simulation.

        This stage deliberately does not issue ToolpathPlan.  Gate D consumes
        its MorphologySimulationResult before the planning stage is allowed.
        """
        trace = ScientificTrace(bus, "simulate_morphology")
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
        sandbox = effective_execution_mode("research", task_spec) == "SANDBOX"
        target_depth = geometry_payload.get("target_depth_um") or task_spec.get(
            "target_depth_um"
        )
        if target_depth is None:
            if not sandbox:
                raise ValueError(
                    "target_depth_um is required in TargetGeometry "
                    "(Gate A enforces TargetGeometry in RESEARCH/DEMO_FIXTURE)"
                )
            target_depth = (
                sorted(observed_depths)[len(observed_depths) // 2]
                if observed_depths
                else 5.0
            )
        width = geometry_payload.get("width_um") or (40.0 if sandbox else None)
        height = (
            geometry_payload.get("height_um")
            or geometry_payload.get("length_um")
            or (40.0 if sandbox else None)
        )
        if not sandbox and (width is None or height is None):
            raise ValueError(
                "width_um / height_um are required in TargetGeometry "
                "(Gate A enforces TargetGeometry in RESEARCH/DEMO_FIXTURE)"
            )
        geometry = TargetGeometry(
            geometry_type="RECTANGULAR_POCKET",
            width_um=float(width),
            height_um=float(height),
            target_depth_um=float(target_depth),
            grid_spacing_um=float(geometry_payload.get("grid_spacing_um") or model.kernel.grid_spacing_um),
        )
        def median(name: str, default: float) -> float:
            values = sorted(float(row[name]) for row in rows if row.get(name) is not None)
            return values[len(values) // 2] if values else default

        peak_fluence = (
            (task_spec.get("laser_parameters") or {}).get("peak_fluence_J_cm2")
            or canonical_peak_fluence
        )
        if peak_fluence is None:
            if not sandbox:
                raise ValueError(
                    "peak_fluence_J_cm2 unresolved: explicit value or canonical "
                    "peak fluence is required (no threshold*2 fallback outside SANDBOX)"
                )
            peak_fluence = model.threshold_J_cm2 * 2.0
        planning_bounds = self._machine_bounds(
            scope,
            rows,
            snapshot_bounds=(self._machine_snapshot(bus) or {}).get(
                "machine_bounds"
            ),
        )
        requested_laser = task_spec.get("laser_parameters") or {}

        def feasible_laser_value(name: str, fallback: float) -> float:
            explicit = requested_laser.get(name)
            value = float(explicit if explicit is not None else fallback)
            bound = planning_bounds.get(name) or {}
            lower = bound.get("lower")
            upper = bound.get("upper")
            if explicit is not None:
                return value  # ToolpathPlanner validates explicit requests.
            if lower is not None:
                value = max(value, float(lower))
            if upper is not None:
                value = min(value, float(upper))
            return value

        laser = {
            "frequency_kHz": feasible_laser_value(
                "frequency_kHz", median("frequency_kHz", 100.0)
            ),
            "scan_speed_mm_s": feasible_laser_value(
                "scan_speed_mm_s", median("scan_speed_mm_s", 100.0)
            ),
            "pulse_width_ps": feasible_laser_value(
                "pulse_width_ps", median("pulse_width_ps", 0.3)
            ),
            "peak_fluence_J_cm2": float(peak_fluence),
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
            for name, value in planning_bounds.items()
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
        inactive_mechanisms = {
            str(item.get("mechanism"))
            for item in model.inactive_mechanisms
        }
        runnable_fidelity = (
            SimulationFidelity.F1_INCUBATION
            if "DEFOCUS_RECURSION" in inactive_mechanisms
            else SimulationFidelity.F2_DEFOCUS_RECURSION
        )
        plan, simulation = planner.plan(
            target=geometry,
            model=model,
            laser_parameters=laser,
            machine_constraints=machine_constraints,
            planning_priors=planning_priors,
            path_families=(PathFamily.RASTER, PathFamily.CROSS_HATCH),
            fidelity=runnable_fidelity,
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
                "status": self._plan_status_for(
                    model.model_dump(mode="json"),
                    execution_mode=effective_execution_mode("research", task_spec),
                ),
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
        candidate_set_artifact = self._persist_artifact(
            bus.run_id,
            "ToolpathCandidateSet",
            plan.model_dump(mode="json"),
            input_refs=[
                {"type": "MorphologySimulationResult", "id": simulation_artifact},
                {"type": "LocalRemovalModel", "id": model_artifact},
                {"type": "CanonicalPhysicsState", "id": canonical_artifact},
                {"type": "PriorObjectSet", "id": self._latest_artifact_id(bus, "PriorObjectSet")},
            ],
            schema_version="toolpath-candidate-set-v1",
        )
        trace.operation_completed(
            "simulator-driven-toolpath-planning",
            f"候选路径仿真完成（{simulation_artifact}）",
            output_refs=[
                {"type": "MorphologySimulationResult", "id": simulation_artifact},
                {"type": "ToolpathCandidateSet", "id": candidate_set_artifact},
            ],
            counts={"candidates": len(plan.candidate_summary), "pulses": simulation.pulse_count},
            reason_codes=["candidate_comparison_only_gate_d_pending"],
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
            "ToolpathCandidateSet",
            candidate_set_artifact,
            input_refs=[
                {"type": "MorphologySimulationResult", "id": simulation_artifact},
                {"type": "LocalRemovalModel", "id": model_artifact},
                {
                    "type": "PriorObjectSet",
                    "id": self._latest_artifact_id(bus, "PriorObjectSet"),
                },
            ],
        )
        return {
            "meta": {
                "simulation_artifact_id": simulation_artifact,
                "candidate_set_artifact_id": candidate_set_artifact,
                "canonical_physics_artifact_id": canonical_artifact,
                "candidate_count": len(plan.candidate_summary),
            },
            "content": {
                "target_geometry": geometry.model_dump(mode="json"),
                "morphology_simulation": simulation.model_dump(mode="json"),
                "toolpath_candidate_set": plan.model_dump(mode="json"),
            },
        }

    def _stage_plan_process(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Issue ToolpathPlan only after Gate D validated simulation+bounds."""
        trace = ScientificTrace(bus, "plan_process")
        candidate_set_artifact = self._latest_artifact_id(bus, "ToolpathCandidateSet")
        candidate_payload = self._latest_artifact_content(bus, "ToolpathCandidateSet")
        simulation_artifact = self._latest_artifact_id(bus, "MorphologySimulationResult")
        simulation_payload = self._latest_artifact_content(
            bus, "MorphologySimulationResult"
        )
        if (
            not candidate_payload
            or not simulation_payload
            or simulation_artifact.endswith("-unavailable")
        ):
            raise ValueError("ToolpathCandidateSet and MorphologySimulationResult are required")
        prior_payload = self._latest_artifact_content(bus, "PriorObjectSet") or {}
        evidence_payload = self._latest_artifact_content(bus, "EvidenceIRSet") or {}
        evidence_ids = {
            str(ref.get("id"))
            for prior in prior_payload.get("priors") or []
            for ref in prior.get("evidence_refs") or []
            if isinstance(ref, dict) and ref.get("id")
        }
        evidence_items = [
            item
            for item in evidence_payload.get("items") or []
            if str(item.get("evidence_id") or "") in evidence_ids
        ]
        paper_ids = {
            str(ref.get("id"))
            for item in evidence_items
            for ref in item.get("source_refs") or []
            if isinstance(ref, dict)
            and ref.get("type") == "Paper"
            and ref.get("id")
        }
        plan = ToolpathPlan.model_validate(candidate_payload).model_copy(
            update={
                "input_refs": [
                    ArtifactRef(type="ToolpathCandidateSet", id=candidate_set_artifact),
                    ArtifactRef(type="MorphologySimulationResult", id=simulation_artifact),
                    ArtifactRef(
                        type="LocalRemovalModel",
                        id=self._latest_artifact_id(bus, "LocalRemovalModel"),
                    ),
                    ArtifactRef(
                        type="CanonicalPhysicsState",
                        id=self._latest_artifact_id(bus, "CanonicalPhysicsState"),
                    ),
                    ArtifactRef(
                        type="PriorObjectSet",
                        id=self._latest_artifact_id(bus, "PriorObjectSet"),
                    ),
                    ArtifactRef(
                        type="EvidenceIRSet",
                        id=self._latest_artifact_id(bus, "EvidenceIRSet"),
                    ),
                ],
                "evidence_refs": [
                    ArtifactRef(type="EvidenceIR", id=evidence_id)
                    for evidence_id in sorted(evidence_ids)
                ],
                "paper_refs": [
                    ArtifactRef(type="Paper", id=paper_id)
                    for paper_id in sorted(paper_ids)
                ],
            }
        )
        trace.operation_started(
            "issue-toolpath-plan",
            "Gate D 通过后签发 ToolpathPlan",
            input_refs=[item.model_dump(mode="json") for item in plan.input_refs],
        )
        plan_artifact = self._persist_artifact(
            bus.run_id,
            "ToolpathPlan",
            plan.model_dump(mode="json"),
            input_refs=[item.model_dump(mode="json") for item in plan.input_refs],
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
            "issue-toolpath-plan",
            f"路径规划完成（{plan_artifact}）",
            output_refs=[
                {"type": "MorphologySimulationResult", "id": simulation_artifact},
                {"type": "ToolpathPlan", "id": plan_artifact},
                {"type": "ProcessCorrectionInterface", "id": correction_artifact},
            ],
            counts={
                "candidates": len(plan.candidate_summary),
                "pulses": int(simulation_payload.get("pulse_count") or 0),
            },
            reason_codes=["selected_by_morphology_error_plus_machining_time"],
        )
        trace.artifact_created(
            "ToolpathPlan",
            plan_artifact,
            input_refs=[item.model_dump(mode="json") for item in plan.input_refs],
        )
        trace.artifact_created(
            "ProcessCorrectionInterface",
            correction_artifact,
            input_refs=[
                {"type": "MorphologySimulationResult", "id": simulation_artifact},
                {"type": "ModelTrainingResult", "id": baseline_ref.id},
            ],
        )
        return {
            "meta": {
                "simulation_artifact_id": simulation_artifact,
                "toolpath_plan_artifact_id": plan_artifact,
                "candidate_set_artifact_id": candidate_set_artifact,
                "path_family": plan.path_family.value,
            },
            "content": {
                "target_geometry": dict(task_spec.get("target_geometry") or {}),
                "morphology_simulation": simulation_payload,
                "toolpath_plan": plan.model_dump(mode="json"),
                "process_correction": correction.model_dump(mode="json"),
            },
        }

    def _stage_evaluate_observation(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        """Persist an observation and explicit update intents without claiming validation."""
        payload = task_spec.get("observation")
        if not isinstance(payload, dict):
            raise TypeError("evaluate_observation requires task_spec.observation")
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
            except Exception as exc:  # noqa: BLE001 - governed prior fails closed
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
        self,
        scope: TaskScope,
        rows: list[dict[str, Any]],
        *,
        snapshot_bounds: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Data-supported bounds intersected with canonical machine bounds.

        Canonical snapshot bounds (MachineProfileSnapshot) are preferred over
        the active agent bounds - every physics consumer reads the snapshot.
        Fixed machine settings (lower == upper) remain fixed; a disjoint data /
        machine range fails closed instead of emitting an unexecutable plan.
        """
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
        agent: dict[str, tuple[float, float]] | None = None
        if snapshot_bounds:
            agent = {
                name: (float(value["lower"]), float(value["upper"]))
                for name, value in snapshot_bounds.items()
                if isinstance(value, dict)
                and value.get("lower") is not None
                and value.get("upper") is not None
            }
        if not agent:
            agent = self._agent_machine_bounds()
        if agent:
            for name in CORE_PARAMETER_NAMES:
                if name not in agent:
                    continue
                lo, hi = agent[name]
                if lo > hi:
                    raise ValueError(f"invalid machine bound for {name}: {lo} > {hi}")
                if hi < data[name][0] or lo > data[name][1]:
                    raise ValueError(
                        f"dataset range and execution machine bound do not overlap for {name}: "
                        f"data={data[name]}, machine={[lo, hi]}"
                    )
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
        except Exception:  # noqa: BLE001 - optional agent lookup
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

    def _plan_status_for(
        self,
        model_payload: dict[str, Any],
        *,
        execution_mode: str,
    ) -> str:
        """ToolpathPlan status semantics (阶段二 T6).

        COMPUTATIONAL_DEFAULT bindings (or SANDBOX) -> PROVISIONAL_SIMULATION_ONLY;
        otherwise DEMO_FIXTURE -> DEMO_CANDIDATE, RESEARCH -> RESEARCH_CANDIDATE.
        """
        from packages.scientific_computation.contracts import PlanStatus

        if execution_mode == "SANDBOX":
            return PlanStatus.PROVISIONAL_SIMULATION_ONLY
        has_computational_default = any(
            str(binding.get("source_type")) == "COMPUTATIONAL_DEFAULT"
            for binding in (model_payload.get("parameter_bindings") or [])
            if isinstance(binding, dict)
        )
        if has_computational_default:
            return PlanStatus.PROVISIONAL_SIMULATION_ONLY
        return (
            PlanStatus.DEMO_CANDIDATE
            if execution_mode == "DEMO_FIXTURE"
            else PlanStatus.RESEARCH_CANDIDATE
        )

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
        simulation_stage = result.get("simulate_morphology") or {}
        planning = result.get("plan_process") or {}
        bo: dict[str, Any] = {}
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
        morphology_simulation = simulation_stage.get("morphology_simulation")
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
        execution_profile_id, execution_revision_id = self._execution_equipment_ref(
            task_spec, scope
        )
        existing_knowledge = knowledge_state.get("existing_knowledge") or {}
        canonical_evidence = list(prepare.get("evidence_ir") or [])
        return {
            "runId": run_id,
            "workflowVersion": self.workflow_version,
            "targetTask": {
                "material": scope.material,
                "laserType": scope.laser_type,
                "geometry": scope.geometry_type,
                "datasetRef": task_spec.get("dataset_ref"),
                "datasetEquipmentScope": scope.equipment_id,
                "executionEquipmentRef": {
                    "equipmentProfileId": execution_profile_id,
                    "revisionId": execution_revision_id,
                },
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
                "paperCount": existing_knowledge.get("paper_count", 0),
                "candidateCount": existing_knowledge.get(
                    "candidate_count", len(bundle.get("candidates") or [])
                ),
                "evidenceCount": len(canonical_evidence),
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
                    "DatasetRef": self._latest_artifact_id_for_run(run_id, "DatasetRef"),
                    "MachineProfileSnapshot": self._latest_artifact_id_for_run(
                        run_id, "MachineProfileSnapshot"
                    ),
                    "CalibrationObservationSet": self._latest_artifact_id_for_run(
                        run_id, "CalibrationObservationSet"
                    ),
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
        return self.repository.application_workflow_events(
            run_id, after_sequence=after_sequence
        )

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
