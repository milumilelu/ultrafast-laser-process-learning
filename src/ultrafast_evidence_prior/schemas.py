"""V1 contracts for task-driven literature evidence and E2P soft priors.

The contracts intentionally do not inherit the legacy Physics-to-Planning
artifacts.  Evidence remains a paper-local, quoted scientific statement;
beliefs add explicit transfer/applicability judgments; priors are downstream
soft guidance and never machine constraints.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TargetMetric(StrEnum):
    DEPTH_UM = "depth_um"
    ROUGHNESS_UM = "roughness_um"


class KnowledgeRequirementType(StrEnum):
    MATERIAL_IDENTITY = "MATERIAL_IDENTITY"
    MATERIAL_PROPERTY = "MATERIAL_PROPERTY"
    PROCESS_OBSERVATION = "PROCESS_OBSERVATION"
    PROCESS_METHOD = "PROCESS_METHOD"
    PARAMETER_EFFECT = "PARAMETER_EFFECT"
    MECHANISM = "MECHANISM"
    REPORTED_OPTIMUM = "REPORTED_OPTIMUM"


class EvidenceType(StrEnum):
    PARAMETER_VALUE = "PARAMETER_VALUE"
    PARAMETER_RANGE = "PARAMETER_RANGE"
    PROCESS_OBSERVATION = "PROCESS_OBSERVATION"
    PARAMETER_EFFECT = "PARAMETER_EFFECT"
    MECHANISM = "MECHANISM"
    PROCESS_METHOD = "PROCESS_METHOD"
    MATERIAL_IDENTITY = "MATERIAL_IDENTITY"
    REPORTED_OPTIMUM = "REPORTED_OPTIMUM"


class EvidenceDirection(StrEnum):
    INCREASES = "INCREASES"
    DECREASES = "DECREASES"
    NON_MONOTONIC = "NON_MONOTONIC"
    OPTIMUM = "OPTIMUM"
    THRESHOLD = "THRESHOLD"
    NO_CLEAR_EFFECT = "NO_CLEAR_EFFECT"
    UNKNOWN = "UNKNOWN"


class ExtractionStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    FAILED = "FAILED"


class ValidationState(StrEnum):
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ConditionValidationState(StrEnum):
    VALIDATED = "VALIDATED"
    UNVERIFIED = "UNVERIFIED"
    REJECTED = "REJECTED"


class TaskRequestV1(StrictModel):
    material: str = Field(min_length=1)
    material_grade: str | None = None
    equipment_profile_id: str = Field(min_length=1)
    equipment_revision_id: str = Field(min_length=1)
    target_metric: TargetMetric


class EquipmentContext(StrictModel):
    equipment_profile_id: str
    equipment_revision_id: str
    profile_name: str
    wavelength_nm: float | None = None
    pulse_width_min_fs: float | None = None
    pulse_width_max_fs: float | None = None
    frequency_min_kHz: float | None = None
    frequency_max_kHz: float | None = None
    scan_speed_min_mm_s: float | None = None
    scan_speed_max_mm_s: float | None = None
    spot_diameter_um: float | None = None
    rated_max_power_W: float | None = None
    measured_max_power_W: float | None = None
    power_transmission_ratio: float | None = None
    effective_max_power_W: float | None = None
    effective_max_power_source: Literal[
        "MEASURED", "DERIVED_FROM_ATTENUATION", "MANUFACTURER_SPEC", "UNKNOWN"
    ] = "UNKNOWN"
    missing_fields: list[str] = Field(default_factory=list)


class ResolvedTaskV1(StrictModel):
    material: str
    material_grade: str | None = None
    target_metric: TargetMetric
    equipment: EquipmentContext


class KnowledgeRequirementV1(StrictModel):
    requirement_id: str
    requirement_type: KnowledgeRequirementType
    scientific_question: str
    target_metric: TargetMetric
    evidence_types: list[EvidenceType] = Field(min_length=1)
    query_terms: list[str] = Field(min_length=1)
    coverage_targets: list[str] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)
    expected_unit: str | None = None
    priority: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    compiler_version: str = "knowledge-requirement-template-v1"


class ParameterSetting(StrictModel):
    parameter: str = Field(min_length=1)
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str = Field(min_length=1)


class ParameterValueContent(StrictModel):
    evidence_type: Literal[EvidenceType.PARAMETER_VALUE]
    parameter: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    statement: str = Field(min_length=1)


class ParameterRangeContent(StrictModel):
    evidence_type: Literal[EvidenceType.PARAMETER_RANGE]
    parameter: str = Field(min_length=1)
    lower: float
    upper: float
    unit: str = Field(min_length=1)
    statement: str = Field(min_length=1)


class ProcessObservationContent(StrictModel):
    evidence_type: Literal[EvidenceType.PROCESS_OBSERVATION]
    statement: str = Field(min_length=1)
    target_metric: str | None = None
    measured_value: float | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def require_value_unit_pair(self) -> ProcessObservationContent:
        if (self.measured_value is None) != (self.unit is None):
            raise ValueError("measured_value and unit must be provided together")
        return self


class ParameterEffectContent(StrictModel):
    evidence_type: Literal[EvidenceType.PARAMETER_EFFECT]
    parameter: str = Field(min_length=1)
    target_metric: str = Field(min_length=1)
    direction: EvidenceDirection
    threshold_value: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str | None = None
    statement: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_numeric_effect(self) -> ParameterEffectContent:
        has_numeric = any(
            value is not None
            for value in (self.threshold_value, self.lower, self.upper)
        )
        if has_numeric and self.unit is None:
            raise ValueError("numeric parameter effects require a unit")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("parameter-effect lower bound exceeds upper bound")
        return self


class MechanismContent(StrictModel):
    evidence_type: Literal[EvidenceType.MECHANISM]
    mechanism: str = Field(min_length=1)
    statement: str = Field(min_length=1)


class ProcessMethodContent(StrictModel):
    evidence_type: Literal[EvidenceType.PROCESS_METHOD]
    method: str = Field(min_length=1)
    statement: str = Field(min_length=1)


class MaterialIdentityContent(StrictModel):
    evidence_type: Literal[EvidenceType.MATERIAL_IDENTITY]
    material: str = Field(min_length=1)
    material_grade: str | None = None
    statement: str = Field(min_length=1)


class ReportedOptimumContent(StrictModel):
    evidence_type: Literal[EvidenceType.REPORTED_OPTIMUM]
    target_metric: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    parameters: list[ParameterSetting] = Field(default_factory=list)


EvidenceContent = Annotated[
    ParameterValueContent
    | ParameterRangeContent
    | ProcessObservationContent
    | ParameterEffectContent
    | MechanismContent
    | ProcessMethodContent
    | MaterialIdentityContent
    | ReportedOptimumContent,
    Field(discriminator="evidence_type"),
]


class ConditionProvenance(StrictModel):
    source: Literal["BLOCK", "PAPER_METADATA", "UNRESOLVED"]
    source_block_refs: list[str] = Field(default_factory=list)
    validation_state: ConditionValidationState = ConditionValidationState.UNVERIFIED
    reason_codes: list[str] = Field(default_factory=list)


class EvidenceIRV2(StrictModel):
    schema_version: str = "evidence-ir-v2"
    evidence_id: str
    requirement_id: str
    paper_id: str
    document_version_id: str
    paper_title: str = ""
    paper_metadata: dict[str, Any] = Field(default_factory=dict)
    content: EvidenceContent
    conditions: dict[str, Any] = Field(default_factory=dict)
    condition_provenance: dict[str, ConditionProvenance] = Field(default_factory=dict)
    evidence_quote: str = ""
    source_block_refs: list[str] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    validation_state: ValidationState
    validation_errors: list[str] = Field(default_factory=list)
    governance_status: str = "unreviewed"
    extraction_route: Literal["llm_extraction", "structured_knowledge"] = "llm_extraction"
    extractor_model: str
    prompt_version: str

    @property
    def evidence_type(self) -> EvidenceType:
        return EvidenceType(self.content.evidence_type)

    @property
    def validated_conditions(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.conditions.items()
            if self.condition_provenance.get(key) is not None
            and self.condition_provenance[key].validation_state
            == ConditionValidationState.VALIDATED
        }


class EvidenceMiss(StrictModel):
    requirement_id: str
    paper_id: str
    document_version_id: str
    status: ExtractionStatus
    reason: str | None = None


class CoverageFacetSpec(StrictModel):
    facet_id: str
    kind: str
    canonical_target: str | None = None
    importance: Literal["CORE", "OPTIONAL"] = "CORE"
    minimum_claims: int = Field(default=1, ge=1)
    minimum_papers: int = Field(default=1, ge=1)
    required_condition_keys: list[str] = Field(default_factory=list)


class RequirementCoverageSpec(StrictModel):
    schema_version: str = "requirement-coverage-spec-v1"
    requirement_id: str
    facets: list[CoverageFacetSpec] = Field(min_length=1)
    minimum_core_facets: int = Field(default=1, ge=1)
    target_coverage: float = Field(default=1.0, ge=0.0, le=1.0)


class CoverageFacetResult(StrictModel):
    facet_id: str
    status: Literal["SUPPORTED", "PARTIAL", "MISSING", "CONFLICT"]
    evidence_ids: list[str] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)
    missing_condition_keys: list[str] = Field(default_factory=list)


class CoverageGap(StrictModel):
    facet_id: str
    missing_fields: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    suggested_terms: list[str] = Field(default_factory=list)


class EvidenceCoverageReport(StrictModel):
    schema_version: str = "evidence-coverage-report-v1"
    requirement_id: str
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    operationally_sufficient: bool
    facets: list[CoverageFacetResult] = Field(default_factory=list)
    gaps: list[CoverageGap] = Field(default_factory=list)
    rejected_evidence_ids: list[str] = Field(default_factory=list)


class SupplementalQuery(StrictModel):
    query_id: str
    gap_ids: list[str] = Field(min_length=1)
    query_text: str = Field(min_length=1, max_length=256)
    target_index: Literal["PAPER", "BLOCK", "BOTH"] = "BOTH"
    paper_ids: list[str] = Field(default_factory=list)
    preferred_sections: list[str] = Field(default_factory=list)
    top_k: int = Field(default=3, ge=1, le=20)


class SupplementalQueryPlan(StrictModel):
    schema_version: str = "supplemental-query-plan-v1"
    plan_id: str
    round: int = Field(ge=1)
    planner_type: Literal["DETERMINISTIC", "LLM"]
    queries: list[SupplementalQuery] = Field(max_length=3)
    reason_codes: list[str] = Field(default_factory=list)


class AcquisitionRoundTrace(StrictModel):
    round: int = Field(ge=0)
    planner_type: Literal["CACHE", "BASELINE", "DETERMINISTIC", "LLM"]
    queries: list[SupplementalQuery] = Field(default_factory=list)
    candidate_count: int = 0
    new_candidate_count: int = 0
    window_count: int = 0
    new_window_count: int = 0
    extraction_calls: int = 0
    validated_evidence_count: int = 0
    coverage: EvidenceCoverageReport


class AcquisitionTrace(StrictModel):
    schema_version: str = "evidence-acquisition-trace-v1"
    requirement_id: str
    coverage_spec: RequirementCoverageSpec
    rounds: list[AcquisitionRoundTrace] = Field(default_factory=list)
    stop_reason: Literal[
        "COVERAGE_SATISFIED",
        "MAX_ROUNDS",
        "QUERY_BUDGET_EXHAUSTED",
        "NO_NOVEL_HITS",
        "NO_COVERAGE_GAIN",
        "NO_ELIGIBLE_GAPS",
        "INVALID_QUERY_PLAN",
        "INDEX_NOT_READY",
    ]
    index_revisions: dict[str, str] = Field(default_factory=dict)
    total_queries: int = 0
    total_extraction_calls: int = 0


class EvidenceIRSetV2(StrictModel):
    schema_version: str = "evidence-ir-set-v2"
    evidence_set_id: str
    items: list[EvidenceIRV2] = Field(default_factory=list)
    misses: list[EvidenceMiss] = Field(default_factory=list)
    paper_candidates: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    acquisition_traces: dict[str, AcquisitionTrace] = Field(default_factory=dict)
    knowledge_reused_count: int = 0
    llm_call_count: int = 0


class ApplicabilityFacet(StrictModel):
    facet: str
    status: Literal["MATCH", "PARTIAL", "MISMATCH", "UNKNOWN", "NOT_APPLICABLE"]
    score: float = Field(ge=0.0, le=1.0)
    task_value: Any | None = None
    evidence_value: Any | None = None
    reason: str


class TransferLevel(StrEnum):
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"
    VERY_WEAK = "VERY_WEAK"


class UncertaintyLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class EvidenceBelief(StrictModel):
    schema_version: str = "evidence-belief-v2"
    belief_id: str
    evidence_id: str
    evidence_type: EvidenceType
    applicability_score: float = Field(ge=0.0, le=1.0)
    evidence_quality: float = Field(ge=0.0, le=1.0)
    transfer_level: TransferLevel
    recommended_prior_strength: float = Field(ge=0.0, le=1.0)
    uncertainty: UncertaintyLevel
    facets: list[ApplicabilityFacet] = Field(default_factory=list)
    support_basis: list[str] = Field(default_factory=list)
    governance_status: str = "unreviewed"
    method: str = "faceted-transfer-score-v2"


class EvidenceBeliefSet(StrictModel):
    schema_version: str = "evidence-belief-set-v2"
    belief_set_id: str
    beliefs: list[EvidenceBelief] = Field(default_factory=list)


class PriorBase(StrictModel):
    schema_version: str = "prior-object-v3"
    prior_id: str
    evidence_refs: list[str] = Field(min_length=1)
    belief_refs: list[str] = Field(min_length=1)
    applicability_score: float = Field(ge=0.0, le=1.0)
    evidence_quality: float = Field(ge=0.0, le=1.0)
    recommended_strength: float = Field(ge=0.0, le=1.0)
    uncertainty: UncertaintyLevel
    status: Literal["PROVISIONAL", "GOVERNED"] = "PROVISIONAL"
    conflict_group_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)


class ParameterPrior(PriorBase):
    prior_type: Literal["ParameterPrior"] = "ParameterPrior"
    parameter: str
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str


class RegionPrior(PriorBase):
    prior_type: Literal["RegionPrior"] = "RegionPrior"
    target_metric: str
    parameters: list[ParameterSetting] = Field(default_factory=list)
    statement: str


class PreferencePrior(PriorBase):
    prior_type: Literal["PreferencePrior"] = "PreferencePrior"
    parameter: str | None = None
    direction: EvidenceDirection | None = None
    threshold_value: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str | None = None
    statement: str
    hard_constraint: Literal[False] = False


class ModelStructurePrior(PriorBase):
    prior_type: Literal["ModelStructurePrior"] = "ModelStructurePrior"
    mechanism: str
    statement: str


PriorObjectV2 = Annotated[
    ParameterPrior | RegionPrior | PreferencePrior | ModelStructurePrior,
    Field(discriminator="prior_type"),
]


class TransferObservation(StrictModel):
    schema_version: str = "transfer-observation-v1"
    observation_id: str
    evidence_refs: list[str] = Field(min_length=1)
    belief_refs: list[str] = Field(min_length=1)
    applicability_score: float = Field(ge=0.0, le=1.0)
    evidence_quality: float = Field(ge=0.0, le=1.0)
    recommended_strength: float = Field(ge=0.0, le=1.0)
    uncertainty: UncertaintyLevel
    status: Literal["PROVISIONAL", "GOVERNED"] = "PROVISIONAL"
    target_metric: str | None = None
    measured_value: float | None = None
    unit: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    statement: str
    assumptions: list[str] = Field(default_factory=list)


class PriorConflict(StrictModel):
    conflict_id: str
    parameter: str
    prior_refs: list[str] = Field(min_length=2)
    reason: str
    resolution: Literal["PRESERVE_SEPARATELY"] = "PRESERVE_SEPARATELY"


class PriorObjectSetV2(StrictModel):
    schema_version: str = "prior-object-set-v3"
    prior_set_id: str
    priors: list[PriorObjectV2] = Field(default_factory=list)
    observations: list[TransferObservation] = Field(default_factory=list)
    conflicts: list[PriorConflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidencePriorAnalysisResult(StrictModel):
    schema_version: str = "evidence-prior-analysis-v1"
    analysis_run_id: str
    task: ResolvedTaskV1
    requirements: list[KnowledgeRequirementV1]
    evidence: EvidenceIRSetV2
    beliefs: EvidenceBeliefSet
    priors: PriorObjectSetV2
    warnings: list[str] = Field(default_factory=list)
