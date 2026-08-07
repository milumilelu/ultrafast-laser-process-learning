"""E2P Knowledge Router（文档 §23-24、§41）。

把经过治理的 ScientificKnowledgeCandidate 编译为可执行科学对象：
    Formula            → FeatureSpec
    Threshold          → FeatureSpec（normalized_fluence 的 required_property）
    MaterialProperty   → FeatureSpec required_properties
    ParameterEffect    → ModelPolicy / PriorSpec
    ReportedOptimum    → SearchPrior（软偏好，绝不缩硬边界）
    ValidatedRule      → ConstraintSpec（hard，唯一允许的硬约束来源）
    HistoricalModel    → ModelPolicy 候选

原则（文档 §3）：approval = permission；hard constraint 与 soft prior 完全分离。
位于 Knowledge 层（依赖 e2p 域对象；e2p 保持 leaf 契约）。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from ultrafast_e2p.application.prior_artifact import (
    REPOSITORY_VERIFIED,
    GovernedPriorArtifact,
    compute_prior_content_hash,
)
from ultrafast_e2p.application.soft_prior import PRIOR_SPEC_VERSION
from ultrafast_e2p.domain.specs import (
    ConstraintSpec,
    E2PDecision,
    FeatureSpec,
    ModelPolicySpec,
)
from ultrafast_knowledge.scientific.schemas import (
    CandidateType,
    ScientificKnowledgeCandidate,
)
from ultrafast_shared.units import convert

# 公式候选 → FeatureSpec 的公式 id 映射（与 ultrafast_physics 注册表一致）
FORMULA_TO_FEATURE: dict[str, str] = {
    "pulse_energy": "pulse_energy",
    "pulse_interval": "pulse_interval",
    "pulse_spacing": "pulse_spacing",
    "line_energy": "line_energy",
    "areal_energy": "areal_energy",
    "gaussian_peak_fluence": "peak_fluence",
    "peak_fluence": "peak_fluence",
    "pulse_overlap": "pulse_overlap",
    "hatch_overlap": "hatch_overlap",
    "pulses_per_spot": "pulses_per_spot",
    "effective_pulses_per_spot": "pulses_per_spot",
    "normalized_fluence": "normalized_fluence",
    "thermal_accumulation_number": "thermal_accumulation_number",
}

THRESHOLD_TO_PROPERTY: dict[str, str] = {
    "ablation_threshold": "ablation_threshold_J_m2",
    "ablation_threshold_fluence": "ablation_threshold_J_m2",
}

MATERIAL_PROPERTY_TO_INPUT: dict[str, str] = {
    "thermal_diffusivity": "thermal_diffusivity_m2_s",
    "thermal_conductivity": "thermal_conductivity",
    "specific_heat": "specific_heat",
    "absorptance": "absorptance",
    "reflectivity": "reflectivity",
    "optical_penetration_depth": "optical_penetration_depth_m",
}

VALIDATED_SAFETY_CONSTRAINTS = frozenset(
    {"pulse_energy_max", "pulse_energy_min", "line_energy_max", "areal_energy_max"}
)

# 公式 → 必需输入（与 ultrafast_physics 注册表一致的规范输入名；此处内联声明，
# 保持 e2p 为 leaf 包，不依赖 physics）
FORMULA_REQUIRED_INPUTS: dict[str, list[str]] = {
    "pulse_energy": ["laser_power_W", "frequency_Hz"],
    "pulse_interval": ["frequency_Hz"],
    "pulse_spacing": ["scan_speed_m_s", "frequency_Hz"],
    "line_energy": ["laser_power_W", "scan_speed_m_s"],
    "areal_energy": ["laser_power_W", "passes", "scan_speed_m_s", "hatch_spacing_m"],
    "peak_fluence": ["pulse_energy_J", "beam_radius_m"],
    "pulse_overlap": ["pulse_spacing_m", "spot_diameter_m"],
    "hatch_overlap": ["hatch_spacing_m", "spot_diameter_m"],
    "pulses_per_spot": ["spot_diameter_m", "frequency_Hz", "scan_speed_m_s"],
    "normalized_fluence": ["peak_fluence_J_m2", "ablation_threshold_J_m2"],
    "thermal_accumulation_number": ["frequency_Hz", "beam_radius_m", "thermal_diffusivity_m2_s"],
}


class E2PKnowledgeRouter:
    """approved knowledge → E2PDecision（唯一编译入口）。

    治理门（审阅 P1）：默认只编译已审核批准的知识（approval_checker 注入时逐条
    校验 knowledge_candidate.review_status=approved）；未审核候选进入
    knowledge_rejected（reason: pending_review），绝不直接消费 LLM 输出。
    """

    def __init__(
        self,
        *,
        feature_version: str = "feature-spec-v1",
        approval_checker: Callable[[str], bool] | None = None,
    ):
        self.feature_version = feature_version
        self.approval_checker = approval_checker

    def route(
        self,
        candidates: list[ScientificKnowledgeCandidate],
        task_scope: dict[str, Any],
        data_profile: dict[str, Any] | None = None,
    ) -> E2PDecision:
        feature_specs: dict[str, FeatureSpec] = {}
        prior_preferences: list[dict[str, Any]] = []
        knowledge_used: list[str] = []
        knowledge_rejected: list[str] = []
        reasons: list[str] = []
        model_candidates: list[str] = []
        constraint_specs: list[ConstraintSpec] = []
        properties: dict[str, tuple[float, str]] = {}
        for candidate in candidates:
            if self.approval_checker is None:
                knowledge_rejected.append(candidate.candidate_id)
                reasons.append("approval_checker_unavailable: E2P compilation fails closed")
                continue
            try:
                approved = bool(self.approval_checker(candidate.candidate_id))
            except Exception:  # noqa: BLE001 - any approval backend failure closes gate
                approved = False
            if not approved:
                knowledge_rejected.append(candidate.candidate_id)
                reasons.append("pending_review: knowledge not approved for E2P compilation")
                continue
            candidate_type = candidate.type
            if candidate_type == CandidateType.FORMULA:
                feature_id = FORMULA_TO_FEATURE.get((candidate.name or "").lower())
                if feature_id is None:
                    knowledge_rejected.append(candidate.candidate_id)
                    reasons.append(f"unsupported_formula:{candidate.name}")
                    continue
                feature_specs.setdefault(
                    feature_id,
                    FeatureSpec(
                        feature_id=feature_id,
                        feature_name=feature_id,
                        formula_id=feature_id,
                        assumptions=list(candidate.assumptions),
                        source_knowledge_ids=[],
                        version=self.feature_version,
                    ),
                )
                feature_specs[feature_id].source_knowledge_ids.append(candidate.candidate_id)
                knowledge_used.append(candidate.candidate_id)
            elif candidate_type in {
                CandidateType.THRESHOLD,
                CandidateType.MATERIAL_PROPERTY,
                CandidateType.OPTICAL_PROPERTY,
            }:
                property_input = THRESHOLD_TO_PROPERTY.get(candidate.property or "") or MATERIAL_PROPERTY_TO_INPUT.get(candidate.property or "")
                if property_input is None or candidate.value is None or candidate.unit is None:
                    knowledge_rejected.append(candidate.candidate_id)
                    reasons.append(f"unsupported_property:{candidate.property}")
                    continue
                converted = convert(candidate.value, candidate.unit)
                if converted is None:
                    knowledge_rejected.append(candidate.candidate_id)
                    reasons.append(f"property_unit_not_normalizable:{candidate.unit}")
                    continue
                properties[property_input] = (converted, candidate.unit)
                # threshold → normalized_fluence 依赖；material property → 特征输入
                if property_input == "ablation_threshold_J_m2":
                    spec = feature_specs.setdefault(
                        "normalized_fluence",
                        FeatureSpec(
                            feature_id="normalized_fluence",
                            feature_name="normalized_fluence",
                            formula_id="normalized_fluence",
                            required_inputs=["peak_fluence_J_m2"],
                            required_properties=[],
                            assumptions=["governed_threshold_required"],
                            source_knowledge_ids=[],
                            version=self.feature_version,
                        ),
                    )
                    if property_input not in spec.required_properties:
                        spec.required_properties.append(property_input)
                    spec.source_knowledge_ids.append(candidate.candidate_id)
                    knowledge_used.append(candidate.candidate_id)
                elif property_input:
                    feature = next(
                        (item for item in feature_specs.values() if property_input in item.required_properties),
                        None,
                    )
                    if feature is None and property_input.startswith("thermal_"):
                        spec = feature_specs.setdefault(
                            "thermal_accumulation_number",
                            FeatureSpec(
                                feature_id="thermal_accumulation_number",
                                feature_name="thermal_accumulation_number",
                                formula_id="thermal_accumulation_number",
                                required_inputs=["frequency_Hz", "beam_radius_m"],
                                required_properties=[],
                                assumptions=["engineering_descriptor_not_full_thermal_model"],
                                source_knowledge_ids=[],
                                version=self.feature_version,
                            ),
                        )
                        if property_input not in spec.required_properties:
                            spec.required_properties.append(property_input)
                        spec.source_knowledge_ids.append(candidate.candidate_id)
                        knowledge_used.append(candidate.candidate_id)
                    else:
                        knowledge_used.append(candidate.candidate_id)
            elif candidate_type == CandidateType.PARAMETER_EFFECT:
                # 参数效应 → ModelPolicy 证据 + 方向性 prior（关系先验）
                knowledge_used.append(candidate.candidate_id)
                if candidate.parameter:
                    prior_preferences.append(
                        {
                            "claim_id": candidate.candidate_id,
                            "parameter": candidate.parameter,
                            "relation": candidate.relation,
                            "semantic_role": "observed_relation",
                            "source_knowledge_ids": [candidate.candidate_id],
                        }
                    )
            elif candidate_type == CandidateType.REPORTED_OPTIMUM:
                if candidate.parameter and candidate.lower is not None and candidate.upper is not None and candidate.unit:
                    converted_lower = convert(candidate.lower, candidate.unit)
                    converted_upper = convert(candidate.upper, candidate.unit)
                    if converted_lower is not None and converted_upper is not None:
                        prior_preferences.append(
                            {
                                "claim_id": candidate.candidate_id,
                                "parameter": candidate.parameter,
                                "lower": converted_lower,
                                "upper": converted_upper,
                                "semantic_role": "reported_optimum",
                                "source_knowledge_ids": [candidate.candidate_id],
                            }
                        )
                        knowledge_used.append(candidate.candidate_id)
                    else:
                        knowledge_rejected.append(candidate.candidate_id)
                        reasons.append(f"optimum_unit_not_normalizable:{candidate.unit}")
                else:
                    knowledge_rejected.append(candidate.candidate_id)
                    reasons.append("reported_optimum_missing_range")
            elif candidate_type == CandidateType.HISTORICAL_MODEL:
                model_candidates.append("GPR")
                knowledge_used.append(candidate.candidate_id)
            elif candidate_type == CandidateType.PARAMETER_VALUE:
                knowledge_rejected.append(candidate.candidate_id)
                reasons.append("parameter_value_needs_validation_before_e2p")
            elif candidate_type == CandidateType.MECHANISM:
                knowledge_used.append(candidate.candidate_id)
            else:
                knowledge_rejected.append(candidate.candidate_id)
                reasons.append(f"unroutable_candidate_type:{candidate_type.value}")
        for spec in feature_specs.values():
            spec.required_inputs = _resolve_required_inputs(spec)
        prior_artifact = self._compile_prior_artifact(prior_preferences, task_scope)
        model_policy = None
        if model_candidates:
            model_policy = ModelPolicySpec(
                candidate_models=model_candidates,
                requirements={"uncertainty_required": True},
                source_knowledge_ids=knowledge_used,
            )
        return E2PDecision(
            e2p_run_id=f"e2p_{uuid.uuid4().hex[:12]}",
            task_scope=task_scope,
            feature_specs=list(feature_specs.values()),
            prior_specs=[prior_artifact.to_dict()] if prior_artifact.prior_spec.get("range_preferences") else [],
            model_policy=model_policy,
            constraint_specs=constraint_specs,
            knowledge_used=list(dict.fromkeys(knowledge_used)),
            knowledge_rejected=list(dict.fromkeys(knowledge_rejected)),
            reason_codes=reasons,
            missing_inputs=self._missing_inputs(list(feature_specs.values()), properties),
        )

    @staticmethod
    def _missing_inputs(
        feature_specs: list[FeatureSpec],
        available_properties: dict[str, tuple[float, str]],
    ) -> list[str]:
        """E2P 主动请求知识（审阅 §5）：FeatureSpec 的必需输入中当前不可得者。"""
        missing: list[str] = []
        for spec in feature_specs:
            for name in [*spec.required_inputs, *spec.required_properties]:
                if name not in available_properties and name not in missing:
                    missing.append(name)
        return missing

    def _compile_prior_artifact(
        self, preferences: list[dict[str, Any]], task_scope: dict[str, Any]
    ) -> GovernedPriorArtifact:
        """SearchPrior 以治理容器形式编译（P0：BO 只消费 artifact）。"""
        range_preferences = [
            {
                "claim_id": item["claim_id"],
                "parameter": item["parameter"],
                "lower": float(item["lower"]),
                "upper": float(item["upper"]),
                "strength": "medium",
                "fixed_weight": 0.5,
                "semantic_role": item.get("semantic_role", "reported_optimum"),
            }
            for item in preferences
            if "lower" in item and "upper" in item
        ]
        prior_spec = {
            "prior_spec_version": PRIOR_SPEC_VERSION,
            "range_preferences": range_preferences,
        }
        approval_ids = [item["claim_id"] for item in preferences]
        content_hash = compute_prior_content_hash(
            prior_spec, approval_ids, task_scope, PRIOR_SPEC_VERSION
        )
        return GovernedPriorArtifact(
            prior_spec=prior_spec,
            approval_ids=tuple(dict.fromkeys(approval_ids)),
            evidence_ids=tuple(dict.fromkeys(approval_ids)),
            compiler_version=PRIOR_SPEC_VERSION,
            scope=task_scope,
            content_hash=content_hash,
            verification=REPOSITORY_VERIFIED,
        )


def _resolve_required_inputs(spec: FeatureSpec) -> list[str]:
    """按公式补全 required_inputs（内联声明，保持 e2p 为 leaf 包）。"""
    extra = FORMULA_REQUIRED_INPUTS.get(spec.formula_id or "", [])
    return list(dict.fromkeys([*spec.required_inputs, *extra]))
