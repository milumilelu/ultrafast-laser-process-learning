"""Versioned API and domain contracts for the Topic2 acceptance backend."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CORE_PARAMETER_NAMES = (
    "pulse_width_ps",
    "frequency_kHz",
    "hatch_spacing_um",
    "passes",
    "scan_speed_mm_s",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskScope(StrictModel):
    task_context_id: str | None = None
    task_context_version: int | None = Field(default=None, ge=1)
    material: str = Field(min_length=1)
    material_grade: str | None = None
    laser_type: Literal["fs", "ps"]
    equipment_id: str = Field(min_length=1)
    laser_id: str | None = None
    machine_id: str | None = None
    geometry_type: str = Field(min_length=1)
    target: Literal["depth_um", "roughness_um"]
    process_parameters: dict[str, Any] = Field(default_factory=dict)
    device_properties: dict[str, Any] = Field(default_factory=dict)


class ProcessParameters(StrictModel):
    """The five parameters present in the repository's real source tables."""

    pulse_width_ps: float | None = Field(default=None, gt=0)
    frequency_kHz: float | None = Field(default=None, gt=0)
    hatch_spacing_um: float | None = Field(default=None, gt=0)
    passes: int | None = Field(default=None, ge=1)
    scan_speed_mm_s: float | None = Field(default=None, gt=0)


class ProcessQuality(StrictModel):
    depth_um: float | None = None
    roughness_um: float | None = None
    roughness_type: Literal["Sa", "Ra"] | None = None
    measurement_device_id: str | None = None
    measurement_method: str | None = None

    @model_validator(mode="after")
    def require_roughness_definition(self) -> ProcessQuality:
        if self.roughness_um is not None and self.roughness_type is None:
            raise ValueError("roughness_type is required when roughness_um is present")
        return self


class DataProfile(StrictModel):
    n_samples: int = Field(ge=0)
    n_unique_designs: int = Field(ge=0)
    n_features: int = Field(ge=0)
    replicate_ratio: float = Field(ge=0, le=1)
    missing_rate: float = Field(ge=0, le=1)
    batch_count: int = Field(ge=0)
    equipment_count: int = Field(ge=0)
    coverage_score: float | None = Field(default=None, ge=0, le=1)


class EvidenceClaimType(StrEnum):
    PARAMETER_DIRECTION = "parameter_direction"
    RANGE_PREFERENCE = "range_preference"
    RELATIVE_IMPORTANCE = "relative_importance"
    HISTORICAL_DATASET = "historical_dataset"
    HISTORICAL_MODEL = "historical_model"
    FUNCTIONAL_SHAPE = "functional_shape"


class EvidenceScope(StrictModel):
    material: str | None = None
    laser_type: Literal["fs", "ps"] | None = None
    geometry_type: str | None = None
    equipment_id: str | None = None
    target: Literal["depth_um", "roughness_um"] | None = None


class EvidenceProvenance(StrictModel):
    source_id: str = Field(min_length=1)
    review_id: str | None = None


class Evidence(StrictModel):
    evidence_id: str = Field(min_length=1)
    source_type: Literal["literature", "process_prior", "historical", "validated_rule"]
    claim_type: EvidenceClaimType
    parameter: str | None = None
    target: Literal["depth_um", "roughness_um"] | None = None
    claim: dict[str, Any]
    scope: EvidenceScope
    provenance: EvidenceProvenance
    review_status: Literal["pending", "approved", "rejected"]
    version: str = "1"

    @model_validator(mode="after")
    def validate_supported_claim(self) -> Evidence:
        if self.parameter is not None and self.parameter not in CORE_PARAMETER_NAMES:
            raise ValueError(f"unsupported parameter: {self.parameter}")
        if (
            self.claim_type == EvidenceClaimType.PARAMETER_DIRECTION
            and self.claim.get("direction") not in {"positive", "negative"}
        ):
            raise ValueError("parameter_direction requires positive/negative direction")
        if self.claim_type == EvidenceClaimType.RANGE_PREFERENCE:
            lower, upper = self.claim.get("lower"), self.claim.get("upper")
            if (
                not isinstance(lower, (int, float))
                or not isinstance(upper, (int, float))
                or lower >= upper
            ):
                raise ValueError("range_preference requires numeric lower < upper")
        forbidden = {"confidence", "prior_mean", "prior_std"}.intersection(self.claim)
        if forbidden:
            raise ValueError(
                f"unsupported unverified numeric prior fields: {sorted(forbidden)}"
            )
        return self


class ExperimentRecord(StrictModel):
    experiment_id: str = Field(min_length=1)
    scope: TaskScope
    parameters: ProcessParameters
    quality: ProcessQuality
    experiment_batch_id: str = Field(min_length=1)
    parameter_combination_id: str | None = None
    source_file: str | None = None
    data_origin: str = Field(min_length=1)
    is_synthetic: bool = False
    valid_flag: bool = True


class ExperimentImportRequest(StrictModel):
    records: list[ExperimentRecord] = Field(min_length=1)
    dataset_version: str | None = None


class EvidenceCompileRequest(StrictModel):
    scope: TaskScope
    evidence: list[Evidence] = Field(default_factory=list)


class ParameterIdentificationRequest(StrictModel):
    scope: TaskScope
    methods: list[Literal["rsm_effect", "permutation_importance"]] = [
        "rsm_effect",
        "permutation_importance",
    ]
    random_seed: int | None = None


class ModelPolicyRequest(StrictModel):
    scope: TaskScope
    data_profile: DataProfile
    evidence: list[Evidence] = Field(default_factory=list)


class E2PPrepareRequest(StrictModel):
    scope: TaskScope
    data_profile: DataProfile
    evidence: list[Evidence] = Field(default_factory=list)


class ModelTrainRequest(StrictModel):
    scope: TaskScope
    model_policy_run_id: str | None = None
    candidate_models: (
        list[Literal["RSM", "GPR", "RandomForest", "HistGradientBoosting"]] | None
    ) = None
    cv_folds: int | None = Field(default=None, ge=2, le=10)
    random_seed: int | None = None


class ParameterBounds(StrictModel):
    lower: float
    upper: float

    @model_validator(mode="after")
    def ordered(self) -> ParameterBounds:
        if self.lower >= self.upper:
            raise ValueError("parameter lower bound must be less than upper bound")
        return self


class GovernedPriorArtifactPayload(StrictModel):
    """Server-issued, review-bound soft-prior contract accepted by Topic2 BO.

    ``prior_spec`` has no standalone request path.  ``artifact_id`` resolves to
    the persisted E2P preparation run that issued this exact payload.
    """

    artifact_id: str = Field(min_length=1)
    prior_spec: dict[str, Any]
    review_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    approval_trace: list[dict[str, Any]] = Field(min_length=1)
    compiler_version: str = Field(min_length=1)
    scope: dict[str, Any]
    content_hash: str = Field(min_length=1)
    verification: Literal["repository_verified"]

    @model_validator(mode="after")
    def require_traceable_soft_prior(self) -> GovernedPriorArtifactPayload:
        preferences = self.prior_spec.get("range_preferences")
        if not isinstance(preferences, list) or not preferences:
            raise ValueError("governed prior artifact requires range_preferences")
        if any(not review_id.strip() for review_id in self.review_ids):
            raise ValueError("governed prior artifact contains an empty review_id")
        traced_reviews = {
            str(item.get("review_id"))
            for item in self.approval_trace
            if item.get("status") == "verified" and item.get("review_id")
        }
        missing = set(self.review_ids).difference(traced_reviews)
        if missing:
            raise ValueError(f"approval trace missing verified reviews: {sorted(missing)}")
        return self


class OptimizationRequest(StrictModel):
    scope: TaskScope
    machine_bounds: dict[str, ParameterBounds]
    model_id: str | None = None
    model_policy_run_id: str | None = None
    governed_prior_artifact: GovernedPriorArtifactPayload | None = None
    beta: float | None = Field(default=None, gt=0)
    lambda_0: float | None = Field(default=None, ge=0)
    alpha: float | None = Field(default=None, ge=0)
    n_candidates: int | None = Field(default=None, ge=20, le=100_000)
    random_seed: int | None = None

    @model_validator(mode="after")
    def require_core_bounds(self) -> OptimizationRequest:
        missing = set(CORE_PARAMETER_NAMES).difference(self.machine_bounds)
        if missing:
            raise ValueError(f"missing machine bounds: {sorted(missing)}")
        passes = self.machine_bounds.get("passes")
        if passes is not None:
            # passes 是整数参数：区间必须至少包含一个整数，否则采样会得到
            # 全越界候选（运行期机器边界异常）。
            import math

            if math.ceil(passes.lower) > math.floor(passes.upper):
                raise ValueError(
                    "passes bounds must contain at least one integer "
                    f"([{passes.lower}, {passes.upper}])"
                )
        return self
