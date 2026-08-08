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
    ENTITY_CREATED,
    ERROR,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    STAGE_COMPLETED,
    STAGE_STARTED,
    TOOL_COMPLETED,
    TOOL_STARTED,
    VALIDATION,
    WARNING,
    WorkflowEventBus,
)
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

ALL_STAGES = (
    "task_validation",
    "dataset_audit",
    "process_learning",
    "scientific_evidence",
    "cfa",
    "governed_prior",
    "optimization",
)

STAGE_LABELS = {
    "task_validation": "任务校验",
    "dataset_audit": "数据集审计",
    "process_learning": "过程学习（辨识 + 建模）",
    "scientific_evidence": "科学证据",
    "cfa": "CFA 适用性审计",
    "governed_prior": "受治理先验",
    "optimization": "Vanilla / Assisted BO",
}

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
            else:
                summary = self._run_research(
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
                    "completed_at": timestamp(),
                }
            )
            bus.emit(RUN_FAILED, f"应用运行失败：{exc}", stage="application")
            raise

    def _run_research(
        self,
        task_spec: dict[str, Any],
        scope: TaskScope,
        stages: list[str],
        bus: WorkflowEventBus,
        random_seed: int,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
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
        return self._research_summary(result, scope, task_spec, random_seed, bus.run_id)

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

    def _stage_task_validation(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
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
            f"任务校验：{capability['n_samples']} 样本 / {capability['n_unique_designs']} 独立设计",
            stage="task_validation",
            details=meta,
        )
        return {"meta": meta, "content": capability}

    def _stage_dataset_audit(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
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
        artifact_id = self._persist_artifact(bus.run_id, "DatasetAudit", summary)
        bus.emit(
            ARTIFACT_CREATED,
            f"数据集审计完成（{artifact_id}）",
            stage="dataset_audit",
            artifact_refs=[{"type": "DatasetAudit", "id": artifact_id}],
        )
        return {"meta": {"artifact_id": artifact_id}, "content": summary}

    def _stage_process_learning(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        bus.emit(TOOL_STARTED, "参数辨识开始", stage="process_learning")
        identification = self.topic2.parameter_identification(
            ParameterIdentificationRequest(
                scope=scope,
                methods=["rsm_effect", "permutation_importance"],
                random_seed=random_seed,
            )
        )
        bus.emit(
            TOOL_COMPLETED,
            f"参数辨识完成（{identification['run_id']}）",
            stage="process_learning",
        )
        self._persist_artifact(bus.run_id, "ProcessLearningResult", identification)
        bus.emit(TOOL_STARTED, "模型训练与比较开始", stage="process_learning")
        training = self.topic2.train_model(
            ModelTrainRequest(scope=scope, random_seed=random_seed), persist=True
        )
        bus.emit(
            TOOL_COMPLETED,
            f"模型训练完成（{training['run_id']}）",
            stage="process_learning",
        )
        self._persist_artifact(bus.run_id, "ModelTrainingResult", training)
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

    def _stage_scientific_evidence(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        evidence = self._evidence_for_scope(scope)
        bundle = self.topic2.compile_evidence(
            EvidenceCompileRequest(scope=scope, evidence=evidence)
        )
        for item in bundle.get("candidates", []):
            bus.emit(
                ENTITY_CREATED,
                f"证据 {item.get('evidence_id')} 已进入证据篮",
                stage="scientific_evidence",
                entity_refs=[{"type": "Evidence", "id": item.get("evidence_id")}],
            )
        artifact_id = self._persist_artifact(bus.run_id, "EvidenceCompileResult", bundle)
        return {
            "meta": {
                "artifact_id": artifact_id,
                "evidence_count": len(bundle.get("accepted", [])),
            },
            "content": {"bundle": bundle, "evidence_count": len(evidence)},
        }

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

    def _stage_cfa(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        report = self._cfa_report(scope)
        artifact_id = self._persist_artifact(bus.run_id, "CFAReport", report)
        bus.emit(
            ARTIFACT_CREATED,
            "CFA 审计报告生成（NOT_YET_CALIBRATED）",
            stage="cfa",
            artifact_refs=[{"type": "CFAReport", "id": artifact_id}],
        )
        return {
            "meta": {
                "artifact_id": artifact_id,
                "calibration_status": "NOT_YET_CALIBRATED",
            },
            "content": report,
        }

    def _cfa_report(self, scope: TaskScope) -> dict[str, Any]:
        """Uncalibrated CFA audit: real target readiness, honest facets.

        Facets are KNOWN/PARTIAL/UNKNOWN/MISMATCH only - never probabilities.
        Without ingested source literature states, evidence facets stay UNKNOWN
        and a warning is recorded (unknown is not mismatch).
        """
        rows = self.topic2._rows_for_scope(scope)
        readiness = self._target_readiness(rows, scope)
        warnings: list[str] = []
        coordinates = self._readiness_coordinates(readiness)
        any_ready = any(
            str(c.get("status")) in {"AVAILABLE", "UNVERIFIED"} for c in coordinates
        )
        facet_summary = {
            "Material": "KNOWN" if scope.material else "UNKNOWN",
            "Task": (
                "PARTIAL" if scope.geometry_type and scope.target else "UNKNOWN"
            ),
            "InteractionState": "PARTIAL" if any_ready else "UNKNOWN",
            "Reconstructibility": "UNKNOWN",
            "Reachability": "UNKNOWN",
        }
        if not coordinates:
            warnings.append(
                "目标侧 canonical 坐标不可用（依赖设备光斑/功率等输入），InteractionState 保持 UNKNOWN（未知≠不匹配）"
            )
        warnings.append(
            "source evidence 未完成文献侧 canonical state 重建；未校准 CFA 仅作审计，不改变 prior 权重"
        )
        return {
            "version": "uncalibrated-cfa-v0.1",
            "calibration_status": "NOT_YET_CALIBRATED",
            "target_physics_readiness": readiness,
            "coordinates": coordinates,
            "facet_summary": facet_summary,
            "warnings": warnings,
        }

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

    def _stage_governed_prior(
        self, task_spec: dict[str, Any], scope: TaskScope, bus: WorkflowEventBus, random_seed: int
    ) -> dict[str, Any]:
        evidence = self._evidence_for_scope(scope)
        prior_artifact = None
        warnings: list[str] = []
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
            self._persist_artifact(bus.run_id, "GovernedPriorArtifact", prior_artifact)
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
                return stored["content"] if stored else None
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
        learning = result.get("process_learning") or {}
        modeling = learning.get("modeling") or {}
        identification = learning.get("identification") or {}
        bo = result.get("optimization") or {}
        prior = result.get("governed_prior") or {}
        cfa = result.get("cfa") or {}
        evidence = result.get("scientific_evidence") or {}
        bundle = evidence.get("bundle") or {}
        prior_artifact = prior.get("governed_prior_artifact")
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
                "sampleCount": (result.get("dataset_audit") or {}).get("n_samples"),
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
        self, run_id: str, artifact_type: str, content: dict[str, Any]
    ) -> str:
        artifact_id = (
            f"{artifact_type}-"
            f"{canonical_hash({'run': run_id, 'type': artifact_type, 'content': content})[:16]}"
        )
        self.repository.save_application_artifact(
            {
                "artifact_id": artifact_id,
                "application_run_id": run_id,
                "artifact_type": artifact_type,
                "content": content,
            }
        )
        return artifact_id
