from __future__ import annotations

import pytest

from ultrafast_requirements import (
    DependencySpec,
    ModelCapability,
    RequirementCategory,
    RequirementCompiler,
    RequirementSource,
    ScientificDependencyGraph,
)


def test_dependency_closure_classifies_missing_scientific_inputs() -> None:
    compiled = RequirementCompiler().compile(
        {
            "target": "depth_um",
            "material": "SiC",
            "laser_type": "fs",
            "wavelength_nm": 1030,
        },
        {
            "laser_power_W": 20.0,
            "frequency_Hz": 200_000.0,
            "scan_speed_m_s": 1.0,
        },
    )
    by_quantity = {item.quantity: item for item in compiled.requirements}

    assert by_quantity["beam_radius_m"].category == RequirementCategory.RESOURCE_REQUIREMENT
    assert by_quantity["ablation_threshold_J_m2"].category == (
        RequirementCategory.KNOWLEDGE_REQUIREMENT
    )
    assert by_quantity["incubation_coefficient"].category == (
        RequirementCategory.KNOWLEDGE_REQUIREMENT
    )
    assert by_quantity["peak_fluence_J_m2"].category == RequirementCategory.DERIVABLE
    assert by_quantity["laser_power_W"].category == RequirementCategory.SATISFIED
    assert by_quantity["frequency_Hz"].category == RequirementCategory.SATISFIED
    assert set(by_quantity["frequency_Hz"].required_by) == {
        "mean_power_to_pulse_energy",
        "scan_pulse_spacing",
    }
    assert by_quantity["ablation_threshold_J_m2"].conditions["material"] == "SiC"


def test_compiler_uses_declarations_without_executing_a_model() -> None:
    graph = ScientificDependencyGraph(
        [
            ModelCapability(
                capability_id="declared-only-model",
                predicts=["response"],
                inputs=[
                    DependencySpec(
                        quantity="measured_input",
                        role="model_input",
                        acceptable_sources=[RequirementSource.EXPERIMENT],
                        expected_unit="m",
                    )
                ],
            )
        ]
    )
    compiled = RequirementCompiler(graph).compile({"target": "response"})

    assert compiled.selected_capabilities == ["declared-only-model"]
    assert compiled.data_requirements[0].quantity == "measured_input"


def test_ambiguous_model_provider_requires_explicit_selection() -> None:
    capabilities = [
        ModelCapability(capability_id=name, predicts=["response"])
        for name in ("model-a", "model-b")
    ]
    compiler = RequirementCompiler(ScientificDependencyGraph(capabilities))

    with pytest.raises(ValueError, match="ambiguous dependency provider"):
        compiler.compile({"target": "response"})

    compiled = compiler.compile(
        {"target": "response", "model_capability_id": "model-b"}
    )
    assert compiled.selected_capabilities == ["model-b"]
