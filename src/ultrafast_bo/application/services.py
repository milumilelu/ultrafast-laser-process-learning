from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ultrafast_bo.domain.models import BOModelStatus, BORecommendation, BOSample
from ultrafast_e2p.application.soft_prior import (
    decayed_evidence_weight,
    log_prior_score,
)

if TYPE_CHECKING:
    from ultrafast_e2p.application.prior_artifact import GovernedPriorArtifact

INTEGER_PARAMETERS = {"passes"}
LOWER_IS_BETTER = {"Sa_um", "Sa_nm", "Ra_um", "Ra_nm", "form_error_um", "graphitization_score", "defect_score"}
TARGET_PRIORITY = (
    "quality_score",
    "objective_score",
    "removal_rate_um3_s",
    "depth_um",
    "Sa_um",
    "Sa_nm",
    "Ra_um",
    "Ra_nm",
)


class BOBlockedError(ValueError):
    pass


class DatasetValidationService:
    def validate(self, samples: Iterable[BOSample | dict[str, Any]]) -> dict[str, Any]:
        accepted: list[BOSample] = []
        rejected: list[dict[str, str]] = []
        for index, raw in enumerate(samples):
            try:
                sample = raw if isinstance(raw, BOSample) else self._coerce(raw, index)
            except (TypeError, ValueError) as exc:
                rejected.append({"sample": str(index), "reason": str(exc)})
                continue
            if not sample.valid_for_training:
                rejected.append({"sample": sample.sample_id, "reason": "valid_for_training=false"})
                continue
            if not sample.x_parameters:
                rejected.append({"sample": sample.sample_id, "reason": "missing numeric x_parameters"})
                continue
            if not sample.y_metrics:
                rejected.append({"sample": sample.sample_id, "reason": "missing numeric y_metrics"})
                continue
            accepted.append(sample)
        return {"valid_samples": accepted, "rejected": rejected, "valid_count": len(accepted)}

    def _coerce(self, raw: dict[str, Any], index: int) -> BOSample:
        x = _numeric_mapping(raw.get("x_parameters") or raw.get("x_parameters_json") or {})
        y = _numeric_mapping(raw.get("y_metrics") or raw.get("y_metrics_json") or {})
        return BOSample(
            sample_id=str(raw.get("sample_id") or f"sample-{index}"),
            x_parameters=x,
            y_metrics=y,
            valid_for_training=_as_bool(raw.get("valid_for_training", True)),
            material=raw.get("material"),
            process_type=raw.get("process_type"),
        )


class BOStatusService:
    """运行模式判定。

    阈值（≤9 cold / 10–29 hybrid / ≥30 data-driven）是工程启发式
    （engineering heuristic），不是统计校准的就绪度标准；正式 readiness
    应基于 DataProfile（n_unique_designs / coverage / noise 等）逐步替代。
    """

    THRESHOLD_POLICY = "engineering_heuristic_v1"

    def __init__(self, cold_start_max_samples: int = 9, hybrid_max_samples: int = 29):
        self.cold_start_max_samples = cold_start_max_samples
        self.hybrid_max_samples = hybrid_max_samples

    def status_for_count(self, valid_sample_count: int) -> BOModelStatus:
        if valid_sample_count <= self.cold_start_max_samples:
            return BOModelStatus.RULE_BASED_COLD_START
        if valid_sample_count <= self.hybrid_max_samples:
            return BOModelStatus.HYBRID_RULE_BO
        return BOModelStatus.DATA_DRIVEN_BO

    def get_status(self, samples: Iterable[BOSample | dict[str, Any]]) -> dict[str, Any]:
        validation = DatasetValidationService().validate(samples)
        status = self.status_for_count(validation["valid_count"])
        return {
            "model_status": status.value,
            "valid_sample_count": validation["valid_count"],
            "rejected_sample_count": len(validation["rejected"]),
            "threshold_policy": self.THRESHOLD_POLICY,
        }


class OfflineModelingService:
    def fit_and_recommend(
        self,
        samples: list[BOSample],
        bounds: dict[str, list[float]],
        task_spec: dict[str, Any],
        model_status: BOModelStatus,
        candidate_count: int = 256,
        prior_spec: dict[str, Any] | None = None,
        outcome_constraints: list[dict[str, Any]] | None = None,
        point_predictor: Any | None = None,
    ) -> dict[str, Any]:
        target = self._select_target(samples, task_spec.get("objective_metric"))
        feature_names = self._select_features(samples, bounds, target)
        model_rows = [sample for sample in samples if target in sample.y_metrics and all(name in sample.x_parameters for name in feature_names)]
        if len(model_rows) < 5:
            raise BOBlockedError("at least 5 complete numeric rows are required for surrogate modeling")
        x = np.asarray([[sample.x_parameters[name] for name in feature_names] for sample in model_rows], dtype=float)
        raw_y = np.asarray([sample.y_metrics[target] for sample in model_rows], dtype=float)
        sign = -1.0 if target in LOWER_IS_BETTER else 1.0
        y = raw_y * sign
        kernel = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(
            length_scale=np.ones(len(feature_names)),
            length_scale_bounds=(1e-3, 1e3),
            nu=2.5,
        ) + WhiteKernel(
            noise_level=1e-5, noise_level_bounds=(1e-8, 1e0)
        )
        pipeline = Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "gpr",
                    GaussianProcessRegressor(
                        kernel=kernel,
                        normalize_y=True,
                        random_state=int(task_spec.get("random_seed", 42)),
                        n_restarts_optimizer=max(0, int(task_spec.get("optimizer_restarts", 2))),
                    ),
                ),
            ]
        )
        pipeline.fit(x, y)
        candidates = self._candidates(bounds, feature_names, candidate_count, int(task_spec.get("random_seed", 42)))
        # 点预测模型：Group-CV winner（P3）可覆盖 GPR 的均值，不确定性始终来自 GPR。
        if point_predictor is not None:
            point_mean = np.asarray(point_predictor.predict(candidates), dtype=float) * sign
        mean, std = pipeline.predict(candidates, return_std=True)
        if point_predictor is not None:
            mean = point_mean
        beta = 1.25 if model_status == BOModelStatus.HYBRID_RULE_BO else 2.0
        ucb = mean + beta * std
        if model_status == BOModelStatus.HYBRID_RULE_BO:
            center_penalty = np.mean(np.abs(_normalize_candidates(candidates, feature_names, bounds) - 0.5), axis=1)
            score = 0.8 * _normalize_vector(ucb) - 0.2 * center_penalty
        else:
            score = ucb
        # P2（第一层）：constrained acquisition —— 候选级乘性可行概率。
        # 仅当 outcome 约束的目标指标与本模型目标一致时才可计算（同一预测分布）；
        # 跨指标约束无联合模型，保守地不计入 acquisition（事后由第二层过滤）。
        outcome_constraints = (
            outcome_constraints
            if outcome_constraints is not None
            else task_spec.get("outcome_constraints")
        )
        feasibility = None
        feasibility_aware = False
        if outcome_constraints:
            same_target = [
                c for c in outcome_constraints
                if str(c.get("metric")) == target and isinstance(c.get("threshold"), (int, float))
            ]
            if same_target:
                probability = np.ones(len(candidates), dtype=float)
                for constraint in same_target:
                    with np.errstate(divide="ignore", invalid="ignore"):
                        z = (float(constraint["threshold"]) - mean) / np.maximum(std, 1e-12)
                    cdf = 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))
                    probability *= (
                        cdf
                        if constraint.get("operator", "max") == "max"
                        else 1.0 - cdf
                    )
                # 不可行候选（P≈0）直接淘汰；对数空间避免下溢
                safe = np.maximum(probability, 1e-12)
                score = score * safe
                feasibility = {
                    "mode": "multiplicative_acquisition",
                    "constraints": [
                        {
                            "metric": c.get("metric"),
                            "operator": c.get("operator", "max"),
                            "threshold": c.get("threshold"),
                        }
                        for c in same_target
                    ],
                    "candidate_feasibility_min": float(np.min(safe)),
                    "candidate_feasibility_mean": float(np.mean(safe)),
                }
                feasibility_aware = True
        search_prior = prior_spec or {}
        if search_prior.get("range_preferences"):
            # E2P soft search prior：文献只改变候选排序偏好，绝不删除合法机器空间。
            candidate_map = {
                name: candidates[:, idx] for idx, name in enumerate(feature_names)
            }
            # 惩罚尺度相对机器范围归一化（窄 prior 区间不再导致二次惩罚爆炸）
            prior_scale = {name: (float(bounds[name][0]), float(bounds[name][1])) for name in feature_names}
            prior_score = log_prior_score(candidate_map, search_prior, scale_by=prior_scale)
            # 数据衰减基于独立参数组合数（DataProfile.n_unique_designs），
            # 而不是有效行数：重复实验不增加参数空间的探索程度。
            n_unique_designs = len(
                {
                    tuple(sorted(sample.x_parameters.items()))
                    for sample in model_rows
                }
            )
            if task_spec.get("n_unique_designs") is not None:
                n_unique_designs = int(task_spec["n_unique_designs"])
            lambda_t = decayed_evidence_weight(
                float(task_spec.get("prior_lambda_0", 0.2)),
                float(task_spec.get("prior_alpha", 0.1)),
                n_unique_designs,
            )
            # prior_score 归一化到 [-1, 0]（最优区间=0，最差=-1）：
            # 未归一化时 penalty 可达数百量级，λ_t 衰减无法压住错误先验的误导。
            score = _normalize_vector(score) + lambda_t * _normalize_prior_score(prior_score)
        selected_index = int(np.argmax(score))
        selected = {
            name: _parameter_value(name, float(candidates[selected_index, idx]))
            for idx, name in enumerate(feature_names)
        }
        predicted_raw = float(mean[selected_index] * sign)
        hybrid_used = model_status == BOModelStatus.HYBRID_RULE_BO
        prior_used = bool(search_prior.get("range_preferences"))
        result = {
            "parameters": selected,
            "target_metric": target,
            "predicted_mean": predicted_raw,
            "predicted_std": float(std[selected_index]),
            "acquisition_score": float(score[selected_index]),
            "feature_names": feature_names,
            "model_rows": len(model_rows),
            "model": (
                "GroupCV_winner"
                if point_predictor is not None
                else "GaussianProcessRegressor(Matern)"
            ),
            # 真实执行的 acquisition 溯源：执行什么就记录什么。
            "acquisition_info": {
                "family": "UCB",
                "implementation": "sklearn_gp_discrete_candidates",
                "version": "1.0",
                "parameters": {"beta": beta},
                "hybrid_center_penalty": hybrid_used,
                "prior_guidance": "e2p_soft_prior_v1" if prior_used else None,
                "acquisition_type": "hybrid_ucb" if hybrid_used else "ucb",
            },
        }
        if feasibility_aware:
            result["acquisition_info"]["feasibility_aware"] = feasibility
        if prior_used:
            result["prior_spec"] = search_prior
            result["search_prior_applied"] = True
        return result

    def _select_target(self, samples: list[BOSample], requested: str | None) -> str:
        candidates = [requested] if requested else list(TARGET_PRIORITY)
        all_names = sorted({name for sample in samples for name in sample.y_metrics})
        candidates.extend(name for name in all_names if name not in candidates)
        for name in candidates:
            if name and sum(name in sample.y_metrics for sample in samples) >= 5:
                return name
        raise BOBlockedError("no objective metric has at least 5 numeric observations")

    def _select_features(
        self,
        samples: list[BOSample],
        bounds: dict[str, list[float]],
        target: str,
    ) -> list[str]:
        eligible_rows = [sample for sample in samples if target in sample.y_metrics]
        features = [
            name
            for name in sorted(bounds)
            if all(name in sample.x_parameters for sample in eligible_rows)
        ]
        if not features:
            raise BOBlockedError("no common numeric features overlap machine bounds and training samples")
        return features

    def _candidates(
        self,
        bounds: dict[str, list[float]],
        feature_names: list[str],
        candidate_count: int,
        seed: int,
    ) -> np.ndarray:
        rng = np.random.default_rng(seed)
        count = max(32, min(int(candidate_count), 4096))
        matrix = np.empty((count, len(feature_names)), dtype=float)
        for index, name in enumerate(feature_names):
            lower, upper = bounds[name]
            if math.isclose(lower, upper):
                matrix[:, index] = lower
            else:
                matrix[:, index] = rng.uniform(lower, upper, size=count)
        return matrix


class _BOCoreEngine:
    def __init__(
        self,
        validation: DatasetValidationService | None = None,
        status: BOStatusService | None = None,
        modeling: OfflineModelingService | None = None,
    ):
        self.validation = validation or DatasetValidationService()
        self.status = status or BOStatusService()
        self.modeling = modeling or OfflineModelingService()

    def recommend(
        self,
        task_spec: dict[str, Any],
        samples: Iterable[BOSample | dict[str, Any]],
        machine_context: dict[str, Any],
        approved_priors: Iterable[dict[str, Any]] | None = None,
        governed_prior: GovernedPriorArtifact | None = None,
        model_policy: dict[str, Any] | None = None,
        approval_verifier: Any | None = None,
    ) -> dict[str, Any]:
        prior_items = list(approved_priors or [])
        # BO surrogate 选择：候选集与评价要求由 E2P ModelPolicy 提出；
        # 最终 winner 由真实数据 Group-CV（RMSE/MAE）决定（P3）。
        model_policy = model_policy or task_spec.get("model_policy")
        surrogate_choice = None
        if model_policy:
            candidates = model_policy.get("candidate_models") or []
            requirements = model_policy.get("requirements") or {}
            if requirements.get("uncertainty_required") and "GPR" not in candidates:
                return BORecommendation(
                    model_status=BOModelStatus.BLOCKED.value,
                    sample_count=0,
                    recommended_parameters={},
                    prediction={},
                    acquisition={"type": None, "score": None},
                    bo_invoked=False,
                    machine_bounds_revision=machine_context.get("revision_id"),
                    warnings=[
                        "E2P ModelPolicy excludes the only uncertainty-capable surrogate (GPR)"
                    ],
                    audit_trace=[
                        {
                            "step": "model_policy_surrogate_gate",
                            "status": "blocked",
                            "candidate_models": candidates,
                        }
                    ],
                ).to_dict()
            surrogate_choice = {
                "model": None,
                "basis": "group_cv_pending",
                "candidate_models": candidates,
                "model_policy_version": model_policy.get("model_policy_version"),
            }
        knowledge_gate = task_spec.get("knowledge_gate_decision") or {}
        gate_approval_ids = []
        reused_approval = knowledge_gate.get("reused_approval") or {}
        if reused_approval.get("approval_id"):
            gate_approval_ids.append(str(reused_approval["approval_id"]))
        machine_bounds = machine_context.get("machine_bounds") or {}
        if not machine_context.get("active") or not machine_bounds:
            return BORecommendation(
                model_status=BOModelStatus.BLOCKED.value,
                sample_count=0,
                recommended_parameters={},
                prediction={},
                acquisition={"type": None, "score": None},
                bo_invoked=False,
                machine_bounds_revision=machine_context.get("revision_id"),
                warnings=["active equipment bounds are required"],
                audit_trace=[{"step": "equipment_gate", "status": "blocked"}],
            ).to_dict()
        normalized_bounds = _numeric_bounds(machine_bounds)
        if not normalized_bounds:
            raise BOBlockedError("machine bounds contain no numeric ranges")
        # 治理链（P0）：知识影响 BO 的唯一合法路径是 governed_prior（或经
        # _compile_governed_prior 由 approved_priors 编译的 artifact）。裸
        # PriorSpec dict 在 BO 层没有应用路径 —— 结构上不可绕过。
        prior_artifact = governed_prior
        if prior_artifact is None and prior_items:
            prior_artifact = _compile_governed_prior(
                normalized_bounds, prior_items, task_spec, approval_verifier
            )
        literature_influences_bo = bool(
            task_spec.get("literature_parameters_used")
            or task_spec.get("knowledge_evidence_ids")
            or (prior_artifact is not None and bool(prior_artifact.approval_ids))
        )
        if literature_influences_bo and knowledge_gate.get("status") != "allowed":
            return BORecommendation(
                model_status=BOModelStatus.BLOCKED.value,
                sample_count=0,
                recommended_parameters={},
                prediction={},
                acquisition={"type": None, "score": None},
                bo_invoked=False,
                machine_bounds_revision=machine_context.get("revision_id"),
                warnings=["KnowledgeUseGate must allow literature-derived inputs before BO"],
                audit_trace=[
                    {"step": "knowledge_use_gate", "status": knowledge_gate.get("status") or "missing"},
                    {"step": "governed_prior", "status": "blocked_by_gate"},
                ],
            ).to_dict()
        # 机器边界永远是唯一硬约束；PriorSpec 由 E2P 唯一 authority 提供，
        # 以 GovernedPriorArtifact 形式携带完整 approval/provenance 链。
        bounded = {name: list(value) for name, value in normalized_bounds.items()}
        if prior_artifact is None:
            prior_spec: dict[str, Any] = {}
            prior_approval_ids: list[str] = []
            prior_trace: list[dict[str, Any]] = []
        else:
            prior_spec = prior_artifact.prior_spec
            prior_approval_ids = list(prior_artifact.approval_ids)
            prior_trace = [
                {
                    "step": "knowledge_prior",
                    "status": "applied_governed_artifact",
                    "content_hash": prior_artifact.content_hash,
                    "verification": prior_artifact.verification,
                    "approval_ids": prior_artifact.approval_ids,
                    "compiler_version": prior_artifact.compiler_version,
                },
                *prior_artifact.source_trace,
            ]
        approval_ids = list(dict.fromkeys([*gate_approval_ids, *prior_approval_ids]))
        validation = self.validation.validate(samples)
        valid_samples: list[BOSample] = validation["valid_samples"]
        governed_status = task_spec.get("_governed_model_status")
        try:
            model_status = BOModelStatus(governed_status) if governed_status else self.status.status_for_count(len(valid_samples))
        except ValueError as exc:
            raise BOBlockedError(f"unsupported governed model status: {governed_status}") from exc
        audit = [
            {
                "step": "dataset_validation",
                "status": "success",
                "valid_samples": len(valid_samples),
                "rejected_samples": len(validation["rejected"]),
            },
            *prior_trace,
        ]
        if model_status == BOModelStatus.BLOCKED:
            return BORecommendation(
                model_status=model_status.value, sample_count=len(valid_samples),
                recommended_parameters={}, prediction={}, acquisition={"type": None, "score": None},
                bo_invoked=False, machine_bounds_revision=machine_context.get("revision_id"),
                knowledge_approval_ids=approval_ids,
                governed_prior=_governed_prior_dict(prior_artifact),
                warnings=["BO readiness assessment blocked modeling"],
                audit_trace=[*audit, {"step": "bo_mode", "status": model_status.value}],
            ).to_dict()
        if model_status == BOModelStatus.RULE_BASED_COLD_START:
            parameters = _cold_start_candidate(bounded)
            return BORecommendation(
                model_status=model_status.value,
                sample_count=len(valid_samples),
                recommended_parameters=parameters,
                prediction={"objective": None, "uncertainty": None},
                acquisition={"type": "conservative_rule", "score": None},
                bo_invoked=False,
                machine_bounds_revision=machine_context.get("revision_id"),
                knowledge_approval_ids=approval_ids,
                governed_prior=_governed_prior_dict(prior_artifact),
                warnings=["insufficient validated samples for surrogate modeling"],
                audit_trace=[*audit, {"step": "bo_mode", "status": model_status.value}],
            ).to_dict()
        # P3：ModelPolicy 候选集 → Group-CV → winner（唯一执行链）。
        winner_estimator, selection_report = self._group_cv_selection(
            valid_samples, bounded, task_spec, model_policy, surrogate_choice
        )
        if surrogate_choice is not None and selection_report is not None:
            surrogate_choice["model"] = selection_report["selected_model"]
            surrogate_choice["basis"] = "group_cv_rmse_mae"
            surrogate_choice["cv_folds"] = selection_report["cv_folds"]
            surrogate_choice["metrics"] = selection_report["metrics"]
            audit.append(
                {
                    "step": "group_cv_model_selection",
                    "status": "success",
                    "selected": selection_report["selected_model"],
                    "cv_folds": selection_report["cv_folds"],
                    "rmse_by_model": {
                        name: round(float(info["RMSE"]), 4)
                        for name, info in selection_report["metrics"].items()
                    },
                }
            )
        try:
            model = self.modeling.fit_and_recommend(
                valid_samples,
                bounded,
                task_spec,
                model_status,
                int(task_spec.get("candidate_count", 256)),
                prior_spec=prior_spec,
                outcome_constraints=task_spec.get("outcome_constraints"),
                point_predictor=winner_estimator,
            )
        except BOBlockedError as exc:
            parameters = _cold_start_candidate(bounded)
            return BORecommendation(
                model_status=BOModelStatus.RULE_BASED_COLD_START.value,
                sample_count=len(valid_samples),
                recommended_parameters=parameters,
                prediction={"objective": None, "uncertainty": None},
                acquisition={"type": "conservative_rule", "score": None},
                bo_invoked=False,
                machine_bounds_revision=machine_context.get("revision_id"),
                knowledge_approval_ids=approval_ids,
                governed_prior=_governed_prior_dict(prior_artifact),
                warnings=[f"surrogate fallback: {exc}"],
                audit_trace=[*audit, {"step": "bo_model", "status": "fallback", "reason": str(exc)}],
            ).to_dict()
        return BORecommendation(
            model_status=model_status.value,
            sample_count=len(valid_samples),
            recommended_parameters=model["parameters"],
            prediction={
                "metric": model["target_metric"],
                "mean": model["predicted_mean"],
                "uncertainty": model["predicted_std"],
            },
            acquisition={
                "type": "hybrid_ucb" if model_status == BOModelStatus.HYBRID_RULE_BO else "ucb",
                "score": model["acquisition_score"],
                **model.get("acquisition_info", {}),
            },
            bo_invoked=True,
            machine_bounds_revision=machine_context.get("revision_id"),
            knowledge_approval_ids=approval_ids,
            governed_prior=_governed_prior_dict(prior_artifact),
            audit_trace=[
                *audit,
                {"step": "bo_mode", "status": model_status.value},
                {
                    "step": "surrogate_model",
                    "status": "success",
                    "model": model["model"],
                    "rows": model["model_rows"],
                    "policy_choice": surrogate_choice,
                },
            ],
        ).to_dict()

    def _group_cv_selection(
        self,
        valid_samples: list[BOSample],
        bounds: dict[str, list[float]],
        task_spec: dict[str, Any],
        model_policy: dict[str, Any] | None,
        surrogate_choice: dict[str, Any] | None,
    ) -> tuple[Any | None, dict[str, Any] | None]:
        """ModelPolicy 候选 → Group-CV（RMSE/MAE）→ winner estimator。

        返回 (winner_estimator, selection_report)。winner 非 GPR 时其点预测
        驱动推荐（不确定性仍由 GPR 提供）；GPR 胜出时返回 None（走默认路径）。
        无 model_policy 或数据不足（<2 独立设计）时返回 (None, None)。
        """
        if not model_policy:
            return None, None
        candidates = model_policy.get("candidate_models") or []
        if not candidates:
            return None, None
        try:
            target = self.modeling._select_target(valid_samples, task_spec.get("objective_metric"))
            features = self.modeling._select_features(valid_samples, bounds, target)
            if not features:
                return None, None
            rows = [
                sample
                for sample in valid_samples
                if target in sample.y_metrics
                and all(name in sample.x_parameters for name in features)
            ]
            if len(rows) < 5:
                return None, None
            frame = pd.DataFrame(
                {
                    **{name: [row.x_parameters[name] for row in rows] for name in features},
                    target: [row.y_metrics[target] for row in rows],
                }
            )
            groups = [
                str(sorted((name, row.x_parameters[name]) for name in features))
                for row in rows
            ]
            if len(set(groups)) < 2:
                return None, None
            from ultrafast_e2p.application.model_selection import select_model

            requirements = model_policy.get("requirements") or {}
            selection = select_model(
                frame[features],
                frame[target],
                groups,
                candidate_models=candidates,
                max_folds=5,
                random_seed=int(task_spec.get("random_seed", 42)),
                uncertainty_required=bool(requirements.get("uncertainty_required")),
            )
        except (ValueError, TypeError, KeyError):
            return None, None
        winner = selection.selected_model
        report = {
            "selected_model": winner,
            "cv_folds": selection.cv_folds,
            "metrics": selection.metrics_by_model,
        }
        if winner != "GPR":
            return selection.estimator, report
        return None, report


class FeedbackService:
    def build_training_sample(
        self,
        sample_id: str,
        parameters: dict[str, Any],
        measurements: dict[str, Any],
        *,
        material: str | None = None,
        process_type: str | None = None,
        quality_valid: bool = True,
    ) -> dict[str, Any]:
        sample = BOSample(
            sample_id=sample_id,
            x_parameters=_numeric_mapping(parameters),
            y_metrics=_numeric_mapping(measurements),
            valid_for_training=quality_valid,
            material=material,
            process_type=process_type,
        )
        validation = DatasetValidationService().validate([sample])
        return {
            "accepted": bool(validation["valid_samples"]),
            "sample": asdict(sample),
            "rejected": validation["rejected"],
        }


class RecommendationService:
    """Deprecated legacy facade; all behavior is delegated to BORecommendationService."""

    def recommend(
        self,
        task_spec: dict[str, Any],
        samples: Iterable[BOSample | dict[str, Any]],
        machine_context: dict[str, Any],
        approved_priors: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from ultrafast_bo.application.compatibility import LegacyBOCompatibilityAdapter

        return LegacyBOCompatibilityAdapter().recommend(
            task_spec, samples, machine_context, approved_priors
        )


def _numeric_mapping(value: Any) -> dict[str, float]:
    if isinstance(value, str):
        import json

        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON mapping") from exc
    if not isinstance(value, dict):
        raise TypeError("expected a mapping")
    result = {}
    for key, item in value.items():
        if isinstance(item, bool) or item is None:
            continue
        try:
            numeric = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            result[str(key)] = numeric
    return result


def _numeric_bounds(bounds: dict[str, Any]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for name, value in bounds.items():
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            continue
        try:
            lower, upper = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(lower) and math.isfinite(upper) and lower <= upper:
            result[name] = [lower, upper]
    return result


def _cold_start_candidate(bounds: dict[str, list[float]]) -> dict[str, float | int]:
    candidate = {}
    for name, (lower, upper) in bounds.items():
        value = lower if math.isclose(lower, upper) else lower + 0.35 * (upper - lower)
        candidate[name] = _parameter_value(name, value)
    return candidate


def _parameter_value(name: str, value: float) -> float | int:
    if name in INTEGER_PARAMETERS:
        return max(1, round(value))
    return float(value)


def _apply_approved_priors(
    bounds: dict[str, list[float]],
    priors: Iterable[dict[str, Any]],
) -> tuple[dict[str, list[float]], list[str], list[dict[str, Any]]]:
    """兼容占位：机器边界不受 prior 收缩，直接返回机器边界副本。"""
    return (
        {name: list(value) for name, value in bounds.items()},
        [],
        [],
    )


def _governed_prior_dict(artifact: Any) -> dict[str, Any] | None:
    """engine 结果中的治理容器摘要（完整链可经 to_dict 复现）。"""
    if artifact is None:
        return None
    from ultrafast_e2p.application.prior_artifact import GovernedPriorArtifact

    if isinstance(artifact, GovernedPriorArtifact):
        return {
            "content_hash": artifact.content_hash,
            "verification": artifact.verification,
            "compiler_version": artifact.compiler_version,
            "approval_ids": list(artifact.approval_ids),
            "evidence_ids": list(artifact.evidence_ids),
            "scope": artifact.scope,
            "applied_preferences": len(artifact.prior_spec.get("range_preferences") or []),
        }
    return None


def _compile_governed_prior(
    bounds: dict[str, list[float]],
    priors: Iterable[dict[str, Any]],
    task_spec: dict[str, Any],
    approval_verifier: Any | None,
) -> GovernedPriorArtifact:
    """委托 E2P 唯一 Prior authority 编译治理容器：本模块不自行编译知识。

    知识→先验（approved prior / EvidenceBundle / review_status）全部属于
    ultrafast_e2p；BO 只消费 GovernedPriorArtifact（含 approval/provenance 链）。
    """
    from ultrafast_e2p.application.prior_compiler import compile_from_approved_priors

    scope = {
        key: task_spec.get(key)
        for key in ("material", "laser_type", "process_type", "geometry_type", "target", "objective_metric")
        if task_spec.get(key)
    }
    return compile_from_approved_priors(
        bounds, list(priors), scope=scope, approval_verifier=approval_verifier
    )


def _normalize_vector(values: np.ndarray) -> np.ndarray:
    minimum = float(np.min(values))
    maximum = float(np.max(values))
    if math.isclose(minimum, maximum):
        return np.zeros_like(values)
    return (values - minimum) / (maximum - minimum)


def _normalize_prior_score(values: np.ndarray) -> np.ndarray:
    """prior score（≤0，值越大越偏好）归一化到 [-1, 0]。"""
    normalized = _normalize_vector(values)
    return normalized - 1.0


def _normalize_candidates(
    candidates: np.ndarray,
    feature_names: list[str],
    bounds: dict[str, list[float]],
) -> np.ndarray:
    result = np.zeros_like(candidates)
    for index, name in enumerate(feature_names):
        lower, upper = bounds[name]
        if math.isclose(lower, upper):
            result[:, index] = 0.5
        else:
            result[:, index] = (candidates[:, index] - lower) / (upper - lower)
    return result


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)
