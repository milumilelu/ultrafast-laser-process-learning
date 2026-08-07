"""Application orchestration separated from HTTP and mathematical cores."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from apps.topic2_backend.settings import ROOT, Settings
from packages.e2p.application.conflict import (
    apply_conflict_multiplier,
    compile_conflict_report,
)
from packages.e2p.application.evidence_compiler import compile_evidence
from packages.e2p.application.model_policy import (
    MODEL_POLICY_VERSION,
    decide_model_policy,
)
from packages.e2p.application.prior_artifact import (
    REPOSITORY_VERIFIED,
    GovernedPriorArtifact,
    compute_prior_content_hash,
)
from packages.e2p.application.soft_prior import PRIOR_SPEC_VERSION, compile_prior_spec
from packages.e2p.application.traceability import (
    environment_manifest,
    new_run_id,
    timestamp,
)
from packages.parameter_identification import identify_parameters
from packages.process_contracts.schemas import (
    CORE_PARAMETER_NAMES,
    E2PPrepareRequest,
    EvidenceCompileRequest,
    ExperimentImportRequest,
    ModelPolicyRequest,
    ModelTrainRequest,
    OptimizationRequest,
    ParameterIdentificationRequest,
    TaskScope,
)
from packages.process_data.profile import build_data_profile
from packages.process_data.repository import SCHEMA_VERSION, Topic2Repository
from packages.process_data.versioning import canonical_hash
from packages.process_modeling.model_selection import comparison_report, select_model
from packages.process_optimization import recommend_with_soft_prior

MODEL_CODE_VERSION = "topic2-model-core-v1"


class Topic2Service:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        approval_verifier: Callable[[str], bool] | None = None,
    ):
        self.settings = settings or Settings.from_env()
        self.approval_verifier = approval_verifier
        self.repository = Topic2Repository(self.settings.database_path)
        self.settings.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.settings.report_dir.mkdir(parents=True, exist_ok=True)
        if self.settings.auto_seed_fixture and not self.repository.list_experiments():
            self.repository.import_fixture(self.settings.fixture_path)
        self._export_json("database_statistics.json", self.repository.statistics())
        latest = self.repository.latest_dataset()
        if latest:
            self._export_json(
                "dataset_summary.json", {**latest, **self.repository.statistics()}
            )

    def _export_json(
        self, filename: str, payload: dict[str, Any], run_id: str | None = None
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        (self.settings.report_dir / filename).write_text(encoded, encoding="utf-8")
        if run_id:
            run_dir = self.settings.report_dir / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / filename).write_text(encoded, encoding="utf-8")

    @staticmethod
    def _task_id(scope: TaskScope) -> str:
        if scope.task_context_id:
            version = scope.task_context_version or 1
            return f"{scope.task_context_id}:v{version}"
        return f"task-{canonical_hash(scope.model_dump(mode='json'))[:12]}"

    @staticmethod
    def _scientific_scope(scope: TaskScope | dict[str, Any]) -> dict[str, Any]:
        payload = (
            scope.model_dump(mode="json")
            if isinstance(scope, TaskScope)
            else dict(scope)
        )
        payload.pop("task_context_id", None)
        payload.pop("task_context_version", None)
        return payload

    def save_task_context(
        self, task_context_id: str, version: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if version < 1:
            raise ValueError("TaskContext version must be >= 1")
        supplied_id = payload.get("task_context_id")
        supplied_version = payload.get("version")
        if supplied_id is not None and str(supplied_id) != task_context_id:
            raise ValueError("TaskContext id does not match the request path")
        if supplied_version is not None and int(supplied_version) != version:
            raise ValueError("TaskContext version does not match the request path")
        snapshot = {**payload, "task_context_id": task_context_id, "version": version}
        return self.repository.save_task_context(snapshot)

    def save_observation(self, payload: dict[str, Any]) -> dict[str, Any]:
        for field in ("observation_id", "task_id", "observation_type"):
            if not str(payload.get(field) or "").strip():
                raise ValueError(f"process observation requires {field}")
        if not isinstance(payload.get("facts"), dict) or not payload["facts"]:
            raise ValueError("process observation requires non-empty facts")
        return self.repository.save_observation(payload)

    def apply_workflow_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply one auditable process command in the Topic2-owned state machine."""
        workflow_id = str(payload.get("workflow_id") or "").strip()
        task_id = str(payload.get("task_id") or "").strip()
        phase = str(payload.get("phase") or "").strip()
        operation = str(payload.get("operation") or "").strip()
        if not workflow_id or not task_id:
            raise ValueError("workflow command requires workflow_id and task_id")
        if phase not in {"trial", "formal"}:
            raise ValueError("workflow phase must be trial or formal")

        current = self.repository.workflow(workflow_id)
        if current and (current["task_id"] != task_id or current["phase"] != phase):
            raise ValueError("workflow identity is immutable")
        current_state = str(current["state"] if current else "new")
        transitions = {
            "trial": {
                ("new", "create"): "prepared",
                ("prepared", "start"): "running",
                ("running", "record_result"): "observed",
                ("observed", "evaluate"): "reviewed",
                ("prepared", "close"): "closed",
                ("reviewed", "close"): "closed",
            },
            "formal": {
                ("new", "prepare"): "prepared",
                ("prepared", "start"): "running",
                ("running", "record_checkpoint"): "running",
                ("running", "record_result"): "observed",
                ("running", "complete"): "completed",
                ("observed", "complete"): "completed",
                ("prepared", "abort"): "aborted",
                ("running", "abort"): "aborted",
                ("observed", "abort"): "aborted",
            },
        }
        next_state = transitions[phase].get((current_state, operation))
        if next_state is None:
            raise ValueError(
                f"invalid {phase} workflow transition: {current_state} -> {operation}"
            )
        if operation == "start" and payload.get("human_approved") is not True:
            raise ValueError("starting physical execution requires scoped human approval")

        history = list((current or {}).get("payload", {}).get("history") or [])
        event = {
            "operation": operation,
            "from_state": current_state,
            "to_state": next_state,
            "data": dict(payload.get("data") or {}),
            "timestamp": timestamp(),
        }
        stored = self.repository.save_workflow(
            {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "phase": phase,
                "state": next_state,
                "operation": operation,
                "expected_version": payload.get("expected_version"),
                "history": [*history, event],
                "latest_event": event,
            }
        )
        return {**stored, "events": self.repository.workflow_events(workflow_id)}

    def _rows_for_scope(self, scope: TaskScope) -> list[dict[str, Any]]:
        rows = self.repository.list_experiments(
            material=scope.material,
            laser_type=scope.laser_type,
            equipment_id=scope.equipment_id,
            geometry_type=scope.geometry_type,
        )
        target = scope.target
        return [
            row for row in rows if row.get("valid_flag") and row.get(target) is not None
        ]

    def scope_capability(
        self,
        material: str | None = None,
        laser_type: str | None = None,
        equipment_id: str | None = None,
        geometry_type: str | None = None,
    ) -> dict[str, Any]:
        """当前组合的样本能力（按目标统计），并列出可选设备/几何供 UI 约束。"""
        rows = self.repository.list_experiments(
            material=material,
            laser_type=laser_type,
            equipment_id=equipment_id,
            geometry_type=geometry_type,
        )
        valid = [row for row in rows if row.get("valid_flag")]

        def counts(target: str) -> dict[str, int]:
            usable = [row for row in valid if row.get(target) is not None]
            return {
                "n_samples": len(usable),
                "n_unique_designs": len(
                    {row["parameter_combination_id"] for row in usable}
                ),
            }

        available_equipment = sorted(
            {row["equipment_id"] for row in self.repository.list_experiments(laser_type=laser_type)}
        )
        available_geometries = sorted(
            {
                row["geometry_type"]
                for row in self.repository.list_experiments(
                    material=material, laser_type=laser_type, equipment_id=equipment_id
                )
            }
        )
        equipment_samples: dict[str, int] = {}
        for name in available_equipment:
            rows_for = self.repository.list_experiments(
                material=material, laser_type=laser_type, equipment_id=name
            )
            equipment_samples[name] = len(
                [row for row in rows_for if row.get("valid_flag")]
            )
        return {
            "scope": {
                "material": material,
                "laser_type": laser_type,
                "equipment_id": equipment_id,
                "geometry_type": geometry_type,
            },
            "n_samples": len(valid),
            "n_unique_designs": len(
                {row["parameter_combination_id"] for row in valid}
            ),
            "targets": {
                "depth_um": counts("depth_um"),
                "roughness_um": counts("roughness_um"),
            },
            "available_equipment": available_equipment,
            "equipment_samples": equipment_samples,
            "available_geometries": available_geometries,
            "meets_identification": counts("depth_um")["n_samples"] >= 4
            and counts("depth_um")["n_unique_designs"] >= 2
            or counts("roughness_um")["n_samples"] >= 4
            and counts("roughness_um")["n_unique_designs"] >= 2,
            "meets_modeling": counts("depth_um")["n_unique_designs"] >= 2
            or counts("roughness_um")["n_unique_designs"] >= 2,
        }

    def _base_manifest(
        self,
        run_id: str,
        scope: TaskScope,
        rows: list[dict[str, Any]],
        random_seed: int,
        configuration: dict[str, Any],
    ) -> dict[str, Any]:
        profile = build_data_profile(rows)
        dataset = self.repository.latest_dataset() or {
            "dataset_version": "unknown",
            "dataset_hash": "unknown",
        }
        return {
            "run_id": run_id,
            "task_id": self._task_id(scope),
            "timestamp": timestamp(),
            "dataset_version": dataset["dataset_version"],
            "dataset_hash": dataset["dataset_hash"],
            "n_samples": profile.n_samples,
            "n_unique_designs": profile.n_unique_designs,
            "model_policy_version": MODEL_POLICY_VERSION,
            "candidate_models": [],
            "selected_model": None,
            "model_version": None,
            "evidence_candidates": [],
            "evidence_accepted": [],
            "evidence_rejected": [],
            "evidence_versions": [],
            "applicability_results": [],
            "prior_spec_version": PRIOR_SPEC_VERSION,
            "validation_metrics": {},
            "optimization_method": None,
            "optimization_config": {},
            "recommended_parameters": None,
            "observation_feedback": None,
            "database_schema_version": SCHEMA_VERSION,
            "scope": scope.model_dump(mode="json"),
            "runtime": environment_manifest(ROOT, random_seed, configuration),
        }

    def import_experiments(self, request: ExperimentImportRequest) -> dict[str, Any]:
        result = self.repository.import_experiments(
            request.records, request.dataset_version
        )
        statistics = self.repository.statistics()
        self._export_json("dataset_summary.json", {**result, **statistics})
        self._export_json("database_statistics.json", statistics)
        return {**result, "statistics": statistics}

    def parameter_identification(
        self, request: ParameterIdentificationRequest
    ) -> dict[str, Any]:
        rows = self._rows_for_scope(request.scope)
        if not rows:
            raise ValueError("no comparable experiments found for the requested scope")
        frame = pd.DataFrame(rows)
        random_seed = (
            request.random_seed
            if request.random_seed is not None
            else self.settings.random_seed
        )
        result = identify_parameters(
            frame,
            request.scope.target,
            frame["parameter_combination_id"],
            request.methods,
            random_seed,
            self.settings.cv_folds,
        )
        run_id = new_run_id("pi")
        configuration = {
            **request.model_dump(mode="json"),
            "effective_random_seed": random_seed,
        }
        manifest = self._base_manifest(
            run_id, request.scope, rows, random_seed, configuration
        )
        manifest["parameter_identification"] = result
        self.repository.save_run(
            run_id, manifest["task_id"], "parameter_identification", manifest
        )
        payload = {
            "run_id": run_id,
            "dataset_version": manifest["dataset_version"],
            **result,
        }
        self._export_json("parameter_identification.json", payload, run_id)
        self._export_json("run_manifest.json", manifest, run_id)
        return payload

    def compile_evidence(self, request: EvidenceCompileRequest) -> dict[str, Any]:
        bundle = compile_evidence(request.scope, request.evidence)
        for item in request.evidence:
            self.repository.save_evidence(item.model_dump(mode="json"))
        return bundle.as_dict()

    def model_policy(self, request: ModelPolicyRequest) -> dict[str, Any]:
        bundle = compile_evidence(request.scope, request.evidence)
        result = decide_model_policy(
            request.scope,
            request.data_profile,
            bundle,
            list(self.settings.candidate_models),
        )
        run_id = new_run_id("policy")
        rows = self._rows_for_scope(request.scope)
        manifest = self._base_manifest(
            run_id,
            request.scope,
            rows,
            self.settings.random_seed,
            request.model_dump(mode="json"),
        )
        manifest.update(
            {
                "candidate_models": result["candidate_models"],
                "evidence_candidates": [item.evidence_id for item in bundle.candidates],
                "evidence_accepted": [item.evidence_id for item in bundle.accepted],
                "evidence_rejected": bundle.rejected,
                "evidence_versions": [item.version for item in bundle.accepted],
                "applicability_results": bundle.applicability_results,
                "model_policy": result,
            }
        )
        self.repository.save_run(run_id, manifest["task_id"], "model_policy", manifest)
        payload = {"run_id": run_id, **result}
        self._export_json("e2p_model_policy.json", payload, run_id)
        self._export_json("run_manifest.json", manifest, run_id)
        return payload

    def e2p_prepare(self, request: E2PPrepareRequest) -> dict[str, Any]:
        """E2P 唯一入口：EvidenceBundle + Applicability + ModelPolicy + PriorSpec。

        Prepare → Execute → Observe → Update；本调用持久化 e2p_run 供追溯。
        """
        bundle = compile_evidence(request.scope, request.evidence)
        policy = decide_model_policy(
            request.scope,
            request.data_profile,
            bundle,
            list(self.settings.candidate_models),
        )
        run_id = new_run_id("e2p")
        prior_spec = compile_prior_spec(bundle)
        governed_prior_artifact = self._issue_governed_prior_artifact(
            run_id, request.scope, bundle.accepted, prior_spec
        )
        rows = self._rows_for_scope(request.scope)
        manifest = self._base_manifest(
            run_id,
            request.scope,
            rows,
            self.settings.random_seed,
            request.model_dump(mode="json"),
        )
        manifest.update(
            {
                "evidence_candidates": [item.evidence_id for item in bundle.candidates],
                "evidence_accepted": [item.evidence_id for item in bundle.accepted],
                "evidence_rejected": bundle.rejected,
                "evidence_versions": [item.version for item in bundle.accepted],
                "applicability_results": bundle.applicability_results,
                "model_policy": policy,
                "prior_spec": prior_spec,
                "governed_prior_artifact": governed_prior_artifact,
                "conflict_state": {"status": "no_observations"},
            }
        )
        self.repository.save_run(run_id, manifest["task_id"], "e2p_prepare", manifest)
        payload = {
            "e2p_run_id": run_id,
            "dataset_version": manifest["dataset_version"],
            "evidence": {
                "candidates": [item.evidence_id for item in bundle.candidates],
                "accepted": [item.evidence_id for item in bundle.accepted],
                "rejected": bundle.rejected,
            },
            "applicability": bundle.applicability_results,
            "model_policy": policy,
            "prior_spec": prior_spec,
            "governed_prior_artifact": governed_prior_artifact,
            "conflict_state": {"status": "no_observations"},
        }
        self._export_json("e2p_prepare.json", payload, run_id)
        self._export_json("run_manifest.json", manifest, run_id)
        return payload

    def _issue_governed_prior_artifact(
        self,
        artifact_id: str,
        scope: TaskScope,
        accepted_evidence: list[Any],
        prior_spec: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Issue an auditable artifact only after live approval verification."""
        if not prior_spec.get("range_preferences"):
            return None
        if self.approval_verifier is None:
            raise ValueError(
                "approval verifier unavailable; governed prior issuance fails closed"
            )
        review_ids: list[str] = []
        evidence_ids: list[str] = []
        trace: list[dict[str, Any]] = []
        for evidence in accepted_evidence:
            review_id = evidence.provenance.review_id
            if not review_id:
                raise ValueError(
                    f"approved evidence lacks review_id: {evidence.evidence_id}"
                )
            if not self.approval_verifier(review_id):
                raise ValueError(f"review is not currently approved: {review_id}")
            review_ids.append(review_id)
            evidence_ids.append(evidence.evidence_id)
            trace.append(
                {
                    "status": "verified",
                    "review_id": review_id,
                    "evidence_id": evidence.evidence_id,
                    "source_id": evidence.provenance.source_id,
                }
            )
        review_ids = list(dict.fromkeys(review_ids))
        evidence_ids = list(dict.fromkeys(evidence_ids))
        artifact_scope = scope.model_dump(mode="json", exclude_none=True)
        content_hash = compute_prior_content_hash(
            prior_spec, review_ids, artifact_scope, PRIOR_SPEC_VERSION
        )
        return {
            "artifact_id": artifact_id,
            "prior_spec": prior_spec,
            "review_ids": review_ids,
            "evidence_ids": evidence_ids,
            "approval_trace": trace,
            "compiler_version": PRIOR_SPEC_VERSION,
            "scope": artifact_scope,
            "content_hash": content_hash,
            "verification": REPOSITORY_VERIFIED,
        }

    def _verified_governed_prior(
        self, request: OptimizationRequest
    ) -> GovernedPriorArtifact | None:
        payload = request.governed_prior_artifact
        if payload is None:
            return None
        if self.approval_verifier is None:
            raise ValueError(
                "approval verifier unavailable; governed prior use fails closed"
            )
        if payload.compiler_version != PRIOR_SPEC_VERSION:
            raise ValueError("governed prior compiler version mismatch")
        expected_scope = request.scope.model_dump(mode="json", exclude_none=True)
        if payload.scope != expected_scope:
            raise ValueError("governed prior scope does not match optimization scope")
        expected_hash = compute_prior_content_hash(
            payload.prior_spec,
            payload.review_ids,
            payload.scope,
            payload.compiler_version,
        )
        if payload.content_hash != expected_hash:
            raise ValueError("governed prior content hash mismatch")
        issuance = self.repository.run(payload.artifact_id)
        stored = issuance and issuance.get("payload", {}).get(
            "governed_prior_artifact"
        )
        if issuance is None or issuance.get("run_type") != "e2p_prepare" or stored is None:
            raise ValueError("governed prior artifact was not issued by Topic2 E2P")
        if stored != payload.model_dump(mode="json"):
            raise ValueError("governed prior artifact differs from its issuance record")
        for review_id in payload.review_ids:
            if not self.approval_verifier(review_id):
                raise ValueError(f"review is no longer approved: {review_id}")
        return GovernedPriorArtifact(
            prior_spec=payload.prior_spec,
            approval_ids=tuple(payload.review_ids),
            evidence_ids=tuple(payload.evidence_ids),
            source_trace=tuple(payload.approval_trace),
            compiler_version=payload.compiler_version,
            scope=payload.scope,
            content_hash=payload.content_hash,
            verification=REPOSITORY_VERIFIED,
        )

    def train_model(
        self, request: ModelTrainRequest, persist: bool = True
    ) -> dict[str, Any]:
        policy_candidates: list[str] | None = None
        if request.model_policy_run_id:
            policy_run = self.repository.run(request.model_policy_run_id)
            if policy_run is None or policy_run["run_type"] != "model_policy":
                raise ValueError("model_policy_run_id does not identify a policy run")
            if self._scientific_scope(
                policy_run["payload"].get("scope") or {}
            ) != self._scientific_scope(request.scope):
                raise ValueError("model policy scope does not match training scope")
            policy_candidates = list(
                policy_run["payload"].get("candidate_models") or []
            )
            if request.candidate_models is not None and list(
                request.candidate_models
            ) != policy_candidates:
                raise ValueError("training candidates differ from the model policy")
        rows = self._rows_for_scope(request.scope)
        if not rows:
            raise ValueError("no comparable experiments found for the requested scope")
        frame = (
            pd.DataFrame(rows)
            .dropna(subset=[request.scope.target, *CORE_PARAMETER_NAMES])
            .reset_index(drop=True)
        )
        if frame["parameter_combination_id"].nunique() < 2:
            raise ValueError(
                "model training requires at least two independent parameter combinations"
            )
        random_seed = (
            request.random_seed
            if request.random_seed is not None
            else self.settings.random_seed
        )
        cv_folds = (
            request.cv_folds if request.cv_folds is not None else self.settings.cv_folds
        )
        candidates = policy_candidates or request.candidate_models or None
        if candidates:
            from packages.process_modeling.model_registry import ACCEPTANCE_MODELS

            unsupported = set(candidates).difference(ACCEPTANCE_MODELS)
            if unsupported:
                raise ValueError(
                    f"model policy contains unsupported candidates: {sorted(unsupported)}"
                )
        selection = select_model(
            frame[list(CORE_PARAMETER_NAMES)],
            frame[request.scope.target].astype(float),
            frame["parameter_combination_id"],
            candidates,
            cv_folds,
            random_seed,
            uncertainty_required=False,
        )
        # 先在内存中完成完整结果（含 RSM 基线比较），全部成功后才落盘，
        # 避免失败路径残留模型文件与数据库记录。
        comparison = comparison_report(selection)
        dataset = self.repository.latest_dataset() or {"dataset_version": "unknown"}
        model_version = (
            f"{MODEL_CODE_VERSION}-{canonical_hash(selection.metrics_by_model)[:10]}"
        )
        model_id = f"model-{canonical_hash({'dataset_version': dataset['dataset_version'], 'scope': request.scope.model_dump(mode='json'), 'model_version': model_version})[:16]}"
        artifact_path = self.settings.artifact_dir / f"topic2-{model_id}.joblib"
        if persist:
            joblib.dump(selection.estimator, artifact_path)
            self.repository.save_model(
                {
                    "model_id": model_id,
                    "model_version": model_version,
                    "dataset_version": dataset["dataset_version"],
                    "material": request.scope.material,
                    "target": request.scope.target,
                    "model_name": selection.selected_model,
                    "metrics": selection.metrics_by_model,
                    "artifact_path": str(artifact_path),
                    "scope": request.scope.model_dump(mode="json"),
                }
            )
        run_id = new_run_id("train")
        configuration = {
            **request.model_dump(mode="json"),
            "effective_random_seed": random_seed,
            "effective_cv_folds": cv_folds,
        }
        manifest = self._base_manifest(
            run_id, request.scope, rows, random_seed, configuration
        )
        manifest.update(
            {
                "candidate_models": list(selection.metrics_by_model),
                "selected_model": selection.selected_model,
                "model_version": model_version,
                "validation_metrics": selection.metrics_by_model,
            }
        )
        self.repository.save_run(
            run_id, manifest["task_id"], "model_training", manifest
        )
        payload = {
            "run_id": run_id,
            "model_id": model_id if persist else None,
            "model_version": model_version,
            "dataset_version": dataset["dataset_version"],
            "selected_model": selection.selected_model,
            "validation_metrics": selection.metrics_by_model,
            "comparison": comparison,
            "cv_strategy": "GroupKFold(parameter_combination_id)",
        }
        self._export_json("model_comparison.json", payload, run_id)
        self._export_json("run_manifest.json", manifest, run_id)
        return payload

    def _load_optimization_model(
        self, request: OptimizationRequest
    ) -> tuple[Any | None, dict[str, Any]]:
        """Load a requested persisted GPR; never silently ignore model identity."""
        if request.model_policy_run_id:
            policy_run = self.repository.run(request.model_policy_run_id)
            if policy_run is None or policy_run.get("run_type") != "model_policy":
                raise ValueError(
                    f"model policy run not found: {request.model_policy_run_id}"
                )
            policy_payload = policy_run["payload"]
            if self._scientific_scope(
                policy_payload.get("scope") or {}
            ) != self._scientific_scope(request.scope):
                raise ValueError("model policy scope does not match optimization scope")
            if request.model_id is not None and "GPR" not in policy_payload.get(
                "candidate_models", []
            ):
                raise ValueError("model policy does not permit GPR optimization")
        if request.model_id is None:
            return None, {
                "model_id": None,
                "model_name": "GPR",
                "model_version": MODEL_CODE_VERSION,
            }
        records = self.repository.models(request.model_id)
        if not records:
            raise ValueError(f"model not found: {request.model_id}")
        metadata = records[0]
        dataset = self.repository.latest_dataset()
        if dataset is None or metadata["dataset_version"] != dataset["dataset_version"]:
            raise ValueError("model dataset version is not current")
        if metadata["material"] != request.scope.material:
            raise ValueError("model material does not match optimization scope")
        if metadata["target"] != request.scope.target:
            raise ValueError("model target does not match optimization scope")
        if metadata.get("scope") and self._scientific_scope(
            metadata["scope"]
        ) != self._scientific_scope(request.scope):
            raise ValueError("model scope does not match optimization scope")
        if metadata["model_name"] != "GPR":
            raise ValueError(
                "optimization currently requires a persisted GPR with uncertainty; "
                f"received {metadata['model_name']}"
            )
        artifact_path = metadata.get("artifact_path")
        if not artifact_path or not Path(artifact_path).is_file():
            raise ValueError(f"model artifact is unavailable: {request.model_id}")
        return joblib.load(artifact_path), metadata

    def recommend(self, request: OptimizationRequest) -> dict[str, Any]:
        rows = self._rows_for_scope(request.scope)
        if not rows:
            raise ValueError("no comparable experiments found for the requested scope")
        frame = (
            pd.DataFrame(rows)
            .dropna(subset=[request.scope.target, *CORE_PARAMETER_NAMES])
            .reset_index(drop=True)
        )
        profile = build_data_profile(frame.to_dict("records"))
        optimization_model, model_metadata = self._load_optimization_model(request)
        governed_prior = self._verified_governed_prior(request)
        prior_spec = (
            governed_prior.prior_spec
            if governed_prior is not None
            else {"prior_spec_version": PRIOR_SPEC_VERSION, "range_preferences": []}
        )
        # Prior–Data Conflict：训练行即观测，检查证据是否被目标数据否定。
        conflict_report = compile_conflict_report(
            prior_spec,
            frame.to_dict("records"),
            request.scope.target,
            lower_is_better=request.scope.target == "roughness_um",
        )
        prior_spec = apply_conflict_multiplier(prior_spec, conflict_report)
        if governed_prior is not None:
            governed_prior = GovernedPriorArtifact(
                prior_spec=prior_spec,
                approval_ids=governed_prior.approval_ids,
                evidence_ids=governed_prior.evidence_ids,
                source_trace=(
                    *governed_prior.source_trace,
                    {"step": "prior_data_conflict", "report": conflict_report},
                ),
                compiler_version=governed_prior.compiler_version,
                scope=governed_prior.scope,
                content_hash=compute_prior_content_hash(
                    prior_spec,
                    list(governed_prior.approval_ids),
                    governed_prior.scope,
                    governed_prior.compiler_version,
                ),
                verification=governed_prior.verification,
            )
        random_seed = (
            request.random_seed
            if request.random_seed is not None
            else self.settings.random_seed
        )
        beta = request.beta if request.beta is not None else self.settings.bo_beta
        lambda_0 = (
            request.lambda_0 if request.lambda_0 is not None else self.settings.lambda_0
        )
        alpha = request.alpha if request.alpha is not None else self.settings.alpha
        n_candidates = (
            request.n_candidates
            if request.n_candidates is not None
            else self.settings.bo_candidate_count
        )
        optimization = recommend_with_soft_prior(
            frame,
            request.scope.target,
            request.machine_bounds,
            governed_prior,
            beta,
            lambda_0,
            alpha,
            profile.n_unique_designs,
            n_candidates,
            random_seed,
            model=optimization_model,
        )
        run_id = new_run_id("bo")
        recommendation_id = f"recommendation-{canonical_hash({'scope': request.scope.model_dump(mode='json'), 'dataset': self.repository.latest_dataset(), 'optimization': optimization})[:16]}"
        configuration = {
            **request.model_dump(mode="json"),
            "effective_beta": beta,
            "effective_lambda_0": lambda_0,
            "effective_alpha": alpha,
            "effective_n_candidates": n_candidates,
            "effective_random_seed": random_seed,
        }
        manifest = self._base_manifest(
            run_id, request.scope, rows, random_seed, configuration
        )
        manifest.update(
            {
                "candidate_models": [model_metadata["model_name"]],
                "selected_model": model_metadata["model_name"],
                "model_id": model_metadata.get("model_id"),
                "model_policy_run_id": request.model_policy_run_id,
                "model_version": model_metadata["model_version"],
                "evidence_candidates": list(
                    governed_prior.evidence_ids if governed_prior else ()
                ),
                "evidence_accepted": list(
                    governed_prior.evidence_ids if governed_prior else ()
                ),
                "evidence_rejected": [],
                "evidence_versions": [],
                "applicability_results": [],
                "governed_prior_artifact_id": (
                    request.governed_prior_artifact.artifact_id
                    if request.governed_prior_artifact
                    else None
                ),
                "conflict_report": conflict_report,
                "optimization_method": optimization["optimization_method"],
                "optimization_config": {
                    "beta": beta,
                    "lambda_0": lambda_0,
                    "alpha": alpha,
                    "n_candidates": n_candidates,
                    "random_seed": random_seed,
                },
                "recommended_parameters": optimization["recommended_parameters"],
            }
        )
        self.repository.save_run(run_id, manifest["task_id"], "optimization", manifest)
        payload = {
            "run_id": run_id,
            "recommendation_id": recommendation_id,
            "model_id": model_metadata.get("model_id"),
            "model_policy_run_id": request.model_policy_run_id,
            "conflict_report": conflict_report,
            "governed_prior_artifact": (
                request.governed_prior_artifact.model_dump(mode="json")
                if request.governed_prior_artifact
                else None
            ),
            **optimization,
        }
        self.repository.save_recommendation(
            recommendation_id, run_id, request.model_id, payload
        )
        self._export_json("optimization_result.json", payload, run_id)
        self._export_json("run_manifest.json", manifest, run_id)
        self._export_json("database_statistics.json", self.repository.statistics())
        return payload

    def export_experiments_csv(self, **filters: Any) -> str:
        rows = self.repository.list_experiments(**filters)
        if not rows:
            return ""
        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue()
