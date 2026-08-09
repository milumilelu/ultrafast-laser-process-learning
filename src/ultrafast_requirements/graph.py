"""Registry-backed scientific dependency graph."""

from __future__ import annotations

from ultrafast_requirements.schemas import (
    DependencySpec,
    ModelCapability,
    RequirementSource,
    VariableSemantic,
)


class ScientificDependencyGraph:
    def __init__(self, capabilities: list[ModelCapability] | None = None) -> None:
        self._capabilities: dict[str, ModelCapability] = {}
        self._providers: dict[str, list[str]] = {}
        for capability in capabilities or []:
            self.register(capability)

    def register(self, capability: ModelCapability) -> None:
        if capability.capability_id in self._capabilities:
            raise ValueError(f"duplicate capability: {capability.capability_id}")
        self._capabilities[capability.capability_id] = capability
        for quantity in capability.predicts:
            self._providers.setdefault(quantity, []).append(capability.capability_id)

    def capability(self, capability_id: str) -> ModelCapability:
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown scientific capability: {capability_id}") from exc

    def providers(self, quantity: str) -> list[ModelCapability]:
        return [self._capabilities[item] for item in self._providers.get(quantity, [])]

    def choose_provider(self, quantity: str, preferred: str | None = None) -> ModelCapability | None:
        providers = self.providers(quantity)
        if preferred is not None:
            for provider in providers:
                if provider.capability_id == preferred:
                    return provider
            raise ValueError(f"capability {preferred!r} does not predict {quantity!r}")
        if len(providers) > 1:
            names = [item.capability_id for item in providers]
            raise ValueError(
                f"ambiguous dependency provider for {quantity!r}; select one of {names}"
            )
        return providers[0] if providers else None

    def capabilities(self) -> tuple[ModelCapability, ...]:
        return tuple(self._capabilities.values())


def _dep(
    quantity: str,
    role: str,
    sources: tuple[RequirementSource, ...],
    unit: str | None = None,
    *,
    policy: str = "require_observed_or_governed_value",
    query_terms: tuple[str, ...] = (),
    semantic: VariableSemantic = VariableSemantic.RESOURCE_INPUT,
    optimizable: bool = False,
) -> DependencySpec:
    return DependencySpec(
        quantity=quantity,
        role=role,
        acceptable_sources=list(sources),
        expected_unit=unit,
        resolution_policy=policy,
        query_terms=list(query_terms),
        variable_semantic=semantic,
        optimizable=optimizable,
    )


def default_dependency_graph() -> ScientificDependencyGraph:
    """Declared dependencies for the current ablation-depth workflow.

    These declarations contain no model execution.  Adding or replacing a
    model is a registry operation and does not change compiler logic.
    """

    equipment = (RequirementSource.EQUIPMENT,)
    knowledge_literature_calibration = (
        RequirementSource.STRUCTURED_KNOWLEDGE,
        RequirementSource.LITERATURE,
        RequirementSource.CALIBRATION,
        RequirementSource.UNRESOLVED,
    )
    capabilities = [
        ModelCapability(
            capability_id="incubation_ablation_depth",
            predicts=["depth_um"],
            model_family="ablation_process_model",
            description="Incubation-aware logarithmic ultrafast ablation depth model.",
            inputs=[
                _dep("ablation_threshold_J_m2", "material_threshold", knowledge_literature_calibration, "J/m2", query_terms=("ablation threshold", "threshold fluence"), semantic=VariableSemantic.MODEL_PARAMETER),
                _dep("incubation_coefficient", "multi_pulse_material_response", knowledge_literature_calibration, "", query_terms=("incubation coefficient", "incubation factor"), semantic=VariableSemantic.MODEL_PARAMETER),
                _dep("optical_penetration_depth_m", "energy_deposition_length", knowledge_literature_calibration, "m", query_terms=("optical penetration depth", "effective penetration depth"), semantic=VariableSemantic.MODEL_PARAMETER),
                _dep("peak_fluence_J_m2", "driving_fluence", (RequirementSource.DERIVED,), "J/m2", semantic=VariableSemantic.DERIVED_QUANTITY),
                _dep("pulse_overlap", "multi_pulse_exposure", (RequirementSource.DERIVED,), "", semantic=VariableSemantic.DERIVED_QUANTITY),
                _dep("pulse_width_s", "pulse_duration", equipment, "s", policy="decision_bounds_or_equipment_value_required", optimizable=True),
                _dep("hatch_spacing_m", "cross_scan_spacing", equipment, "m", policy="decision_bounds_or_equipment_value_required", optimizable=True),
                _dep("passes", "pass_count", equipment, "", policy="decision_bounds_or_equipment_value_required", optimizable=True),
            ],
            assumptions=["model applicability must be checked for material and pulse regime"],
        ),
        ModelCapability(
            capability_id="gaussian_peak_fluence",
            predicts=["peak_fluence_J_m2"],
            model_family="deterministic_formula",
            inputs=[
                _dep("pulse_energy_J", "pulse_energy", (RequirementSource.DERIVED,), "J", semantic=VariableSemantic.DERIVED_QUANTITY),
                _dep("beam_radius_m", "gaussian_1e2_radius", equipment, "m", policy="equipment_measurement_required"),
            ],
            assumptions=["gaussian spatial profile", "beam radius is the 1/e^2 intensity radius"],
        ),
        ModelCapability(
            capability_id="mean_power_to_pulse_energy",
            predicts=["pulse_energy_J"],
            model_family="deterministic_formula",
            inputs=[
                _dep("laser_power_W", "average_power", equipment, "W", policy="decision_bounds_or_equipment_value_required", optimizable=True),
                _dep("frequency_Hz", "pulse_repetition_rate", equipment, "Hz", policy="decision_bounds_or_equipment_value_required", optimizable=True),
            ],
        ),
        ModelCapability(
            capability_id="scan_pulse_overlap",
            predicts=["pulse_overlap"],
            model_family="deterministic_formula",
            inputs=[
                _dep("pulse_spacing_m", "along_scan_spacing", (RequirementSource.DERIVED,), "m", semantic=VariableSemantic.DERIVED_QUANTITY),
                _dep("spot_diameter_m", "beam_spot_diameter", (RequirementSource.DERIVED,), "m", semantic=VariableSemantic.DERIVED_QUANTITY),
            ],
        ),
        ModelCapability(
            capability_id="scan_pulse_spacing",
            predicts=["pulse_spacing_m"],
            model_family="deterministic_formula",
            inputs=[
                _dep("scan_speed_m_s", "scan_speed", equipment, "m/s", policy="decision_bounds_or_equipment_value_required", optimizable=True),
                _dep("frequency_Hz", "pulse_repetition_rate", equipment, "Hz", policy="decision_bounds_or_equipment_value_required", optimizable=True),
            ],
        ),
        ModelCapability(
            capability_id="radius_to_diameter",
            predicts=["spot_diameter_m"],
            model_family="deterministic_definition",
            inputs=[
                _dep("beam_radius_m", "gaussian_1e2_radius", equipment, "m", policy="equipment_measurement_required"),
            ],
        ),
    ]
    return ScientificDependencyGraph(capabilities)
