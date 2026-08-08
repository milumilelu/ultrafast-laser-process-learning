"""Versioned contracts for the Physics-to-Planning V1 scientific core.

The contracts deliberately encode epistemic state as enums.  Effective or
provisional fitted values can therefore never be serialized as physical truth.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "physics-to-planning-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScientificStatus(StrEnum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    MISMATCH = "MISMATCH"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNVERIFIED = "UNVERIFIED"
    MISSING = "MISSING"


class IdentifiabilityStatus(StrEnum):
    IDENTIFIABLE = "IDENTIFIABLE"
    WEAKLY_IDENTIFIABLE = "WEAKLY_IDENTIFIABLE"
    NOT_IDENTIFIABLE = "NOT_IDENTIFIABLE"


class ParameterSemantics(StrEnum):
    PHYSICAL = "PHYSICAL"
    EFFECTIVE = "EFFECTIVE"
    PROVISIONAL = "PROVISIONAL"


class CalibrationStatus(StrEnum):
    CALIBRATED = "CALIBRATED"
    NOT_YET_CALIBRATED = "NOT_YET_CALIBRATED"


class InteractionTopology(StrEnum):
    OPEN_SURFACE = "OPEN_SURFACE"
    SHALLOW_2_5D = "SHALLOW_2_5D"
    DEEP_CONFINED = "DEEP_CONFINED"
    PERCUSSION_DRILLING = "PERCUSSION_DRILLING"
    THROUGH_HOLE = "THROUGH_HOLE"
    UNKNOWN = "UNKNOWN"


class SimulationFidelity(StrEnum):
    F0_FIXED_KERNEL = "F0_FIXED_KERNEL"
    F1_INCUBATION = "F1_INCUBATION"
    F2_DEFOCUS_RECURSION = "F2_DEFOCUS_RECURSION"
    F3_THERMAL_MEMORY_PROXY = "F3_THERMAL_MEMORY_PROXY"


class RemovalModelMode(StrEnum):
    EMPIRICAL = "EMPIRICAL"
    RECONSTRUCTED = "RECONSTRUCTED"
    HYBRID = "HYBRID"


class EvidenceOrigin(StrEnum):
    EXPERIMENTAL_OBSERVATION = "EXPERIMENTAL_OBSERVATION"
    LITERATURE = "LITERATURE"
    SYNTHETIC_TEST_FIXTURE = "SYNTHETIC_TEST_FIXTURE"
    MODEL_RECONSTRUCTION = "MODEL_RECONSTRUCTION"


class PathFamily(StrEnum):
    SINGLE_LINE = "SINGLE_LINE"
    RASTER = "RASTER"
    CROSS_HATCH = "CROSS_HATCH"
    CONTOUR = "CONTOUR"
    SPIRAL = "SPIRAL"


class PlanStatus(StrEnum):
    RECOMMENDED = "RECOMMENDED"
    CANDIDATE = "CANDIDATE"
    NOT_EXECUTABLE = "NOT_EXECUTABLE"


class LearningMode(StrEnum):
    RAW = "RAW"
    PHYSICS = "PHYSICS"
    HYBRID = "HYBRID"


class ArtifactRef(StrictModel):
    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class ProvenanceRecord(StrictModel):
    source_type: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    role: str = Field(min_length=1)


class CapabilityInput(StrictModel):
    name: str = Field(min_length=1)
    value: float | int | str | None = None
    unit: str = Field(min_length=1)
    status: AvailabilityStatus
    source_refs: list[ArtifactRef] = Field(default_factory=list)


class PhysicsQuantity(StrictModel):
    value: float
    unit: str = Field(min_length=1)
    status: AvailabilityStatus


class CanonicalPhysicsState(StrictModel):
    schema_version: str = SCHEMA_VERSION
    state_id: str = Field(min_length=1)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    quantities: dict[str, PhysicsQuantity] = Field(default_factory=dict)
    missing_inputs: list[str] = Field(default_factory=list)
    status: ScientificStatus
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class ParameterIdentifiability(StrictModel):
    parameter: str = Field(min_length=1)
    status: IdentifiabilityStatus
    reason_codes: list[str] = Field(default_factory=list)
    required_observations: list[str] = Field(default_factory=list)


class CapabilityRequirement(StrictModel):
    requirement_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    scientific_question: str = Field(min_length=1)
    required_for: str = Field(min_length=1)
    priority: Literal["high", "medium", "low"]
    trigger_reasons: list[str] = Field(min_length=1)
    required_evidence_roles: list[str] = Field(default_factory=list)
    satisfaction_criteria: list[str] = Field(default_factory=list)
    status: ScientificStatus = ScientificStatus.UNKNOWN
    provenance: list[ArtifactRef] = Field(default_factory=list)


class ScientificCapabilityReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    capability_id: str = Field(min_length=1)
    task_ref: ArtifactRef
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    interaction_topology: InteractionTopology
    simulation_supported: bool
    supported_fidelity: list[SimulationFidelity] = Field(default_factory=list)
    available: list[CapabilityInput] = Field(default_factory=list)
    missing: list[CapabilityInput] = Field(default_factory=list)
    identifiability: list[ParameterIdentifiability] = Field(default_factory=list)
    recommended_requirements: list[CapabilityRequirement] = Field(default_factory=list)
    status: ScientificStatus
    reason_codes: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class ParameterObservation(StrictModel):
    peak_fluence_J_cm2: float | None = Field(default=None, gt=0)
    pulse_count: int = Field(ge=1)
    depth_um: float
    data_ref: str = Field(min_length=1)
    origin: EvidenceOrigin


class ParameterEstimate(StrictModel):
    parameter: str = Field(min_length=1)
    estimate: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str = Field(min_length=1)
    identifiability: IdentifiabilityStatus
    parameter_semantics: ParameterSemantics
    prior_refs: list[ArtifactRef] = Field(default_factory=list)
    data_refs: list[ArtifactRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interval_and_identifiability(self) -> ParameterEstimate:
        if self.identifiability == IdentifiabilityStatus.NOT_IDENTIFIABLE:
            if self.estimate is not None:
                raise ValueError("NOT_IDENTIFIABLE parameter cannot expose an estimate")
            return self
        if self.estimate is None:
            raise ValueError("identifiable parameter requires an estimate")
        if (
            self.lower is None
            or self.upper is None
            or self.lower > self.estimate
            or self.upper < self.estimate
        ):
            raise ValueError("parameter interval must contain estimate")
        return self


class IdentifiabilityReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    report_id: str = Field(min_length=1)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    parameters: list[ParameterIdentifiability]
    observation_type: str = Field(min_length=1)
    status: ScientificStatus
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class FitMetrics(StrictModel):
    rmse: float = Field(ge=0)
    mae: float = Field(ge=0)
    r2: float | None = None
    target_unit: str = Field(min_length=1)
    n_observations: int = Field(ge=0)


class CalibrationResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    calibration_id: str = Field(min_length=1)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    parameters: list[ParameterEstimate]
    fit_metrics: FitMetrics
    status: CalibrationStatus
    validation_data_refs: list[ArtifactRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class PhysicalModelState(StrictModel):
    schema_version: str = SCHEMA_VERSION
    state_id: str = Field(min_length=1)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    canonical_physics_status: ScientificStatus
    active_mechanism_models: list[str] = Field(default_factory=list)
    calibrated_parameter_refs: list[ArtifactRef] = Field(default_factory=list)
    local_removal_model_ref: ArtifactRef | None = None
    simulator_fidelity: SimulationFidelity
    uncertainty_status: ScientificStatus
    assumptions: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class RemovalKernel(StrictModel):
    shape: Literal["GAUSSIAN", "MEASURED_GRID"]
    radius_um: float = Field(gt=0)
    peak_depth_um: float = Field(ge=0)
    grid_spacing_um: float = Field(gt=0)
    values_um: list[list[float]] = Field(min_length=1)
    origin: EvidenceOrigin


class LocalRemovalModel(StrictModel):
    schema_version: str = SCHEMA_VERSION
    model_id: str = Field(min_length=1)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    mode: RemovalModelMode
    kernel: RemovalKernel
    threshold_J_cm2: float = Field(gt=0)
    incubation_S: float = Field(gt=0, le=1.5)
    delta_um: float = Field(gt=0)
    alpha_defocus_per_um: float = Field(ge=0)
    thermal_memory_eff: float = Field(default=0, ge=0)
    parameter_semantics: dict[str, ParameterSemantics]
    status: ScientificStatus
    assumptions: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class MorphologyState(StrictModel):
    height_field_um: list[list[float]]
    effective_pulse_count: list[list[float]]
    accumulated_fluence_J_cm2: list[list[float]]
    thermal_memory_proxy: list[list[float]]
    grid_spacing_um: float = Field(gt=0)
    validity_flags: list[str] = Field(default_factory=list)


class MorphologyMetrics(StrictModel):
    mean_depth_um: float = Field(ge=0)
    max_depth_um: float = Field(ge=0)
    removed_volume_um3: float = Field(ge=0)
    morphology_rmse_um: float | None = Field(default=None, ge=0)
    machining_time_s: float = Field(default=0, ge=0)


class MorphologySimulationResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    simulation_id: str = Field(min_length=1)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    local_removal_model_ref: ArtifactRef
    fidelity: SimulationFidelity
    state: MorphologyState
    target_depth_field_um: list[list[float]] | None = None
    predicted_depth_field_um: list[list[float]]
    difference_field_um: list[list[float]] | None = None
    metrics: MorphologyMetrics
    pulse_count: int = Field(ge=0)
    deterministic_seed: int
    status: ScientificStatus
    warnings: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class TargetGeometry(StrictModel):
    geometry_type: Literal["RECTANGULAR_POCKET", "SHALLOW_GROOVE", "OPEN_SURFACE"]
    width_um: float = Field(gt=0)
    height_um: float = Field(gt=0)
    target_depth_um: float = Field(gt=0)
    grid_spacing_um: float = Field(gt=0)


class ConstraintValue(StrictModel):
    name: str = Field(min_length=1)
    lower: float | None = None
    upper: float | None = None
    unit: str = Field(min_length=1)


class ToolpathPlan(StrictModel):
    schema_version: str = SCHEMA_VERSION
    plan_id: str = Field(min_length=1)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    path_family: PathFamily
    path_parameters: dict[str, float | int | str]
    laser_parameters: dict[str, float | int | str]
    predicted_metrics: MorphologyMetrics
    machine_constraints: list[ConstraintValue]
    simulation_ref: ArtifactRef
    planning_prior_refs: list[ArtifactRef] = Field(default_factory=list)
    status: PlanStatus
    objective_value: float
    candidate_summary: list[dict[str, Any]] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class ObservationMeasurement(StrictModel):
    name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    method: str = Field(min_length=1)


class ObservationResult(StrictModel):
    """Closed-loop observation contract; it does not imply validation."""

    schema_version: str = SCHEMA_VERSION
    observation_id: str = Field(min_length=1)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    origin: EvidenceOrigin
    measurements: list[ObservationMeasurement] = Field(min_length=1)
    morphology_payload_ref: ArtifactRef | None = None
    status: ScientificStatus
    update_triggers: list[
        Literal[
            "DATA_STATE",
            "CALIBRATION",
            "PROCESS_MODEL",
            "E2P_TRUST",
        ]
    ] = Field(default_factory=list)
    independent_validation: bool = False
    assumptions: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def synthetic_is_not_validation(self) -> ObservationResult:
        if self.origin == EvidenceOrigin.SYNTHETIC_TEST_FIXTURE and self.independent_validation:
            raise ValueError("synthetic fixture cannot be independent validation")
        return self


class ProcessCorrectionInterface(StrictModel):
    """Residual-capable boundary; V1 does not fabricate a trained field model."""

    schema_version: str = SCHEMA_VERSION
    interface_id: str = Field(min_length=1)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    supported_modes: list[LearningMode] = Field(
        default_factory=lambda: [LearningMode.RAW, LearningMode.PHYSICS, LearningMode.HYBRID]
    )
    raw_baseline_ref: ArtifactRef
    physics_prediction_ref: ArtifactRef
    residual_model_ref: ArtifactRef | None = None
    status: ScientificStatus
    assumptions: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
