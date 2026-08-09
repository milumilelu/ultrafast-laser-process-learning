from __future__ import annotations

import pytest

from ultrafast_requirements import (
    DependencySpec,
    ModelCapability,
    RequirementCategory,
    RequirementCompiler,
    RequirementSource,
    ScientificDependencyGraph,
    VariableSemantic,
)


def test_dependency_closure_classifies_missing_scientific_inputs() -> None:
    compiled = RequirementCompiler().compile(
        {
            "target": "depth_um",
            "task_type": "prediction",
            "material": "SiC",
            "laser_type": "fs",
            "wavelength_nm": 1030,
        },
        [
            {"quantity": "laser_power_W", "value": 20.0, "unit": "W", "source": "task"},
            {"quantity": "frequency_kHz", "value": 200.0, "unit": "kHz", "source": "task"},
            {"quantity": "scan_speed_mm_s", "value": 1000.0, "unit": "mm/s", "source": "task"},
        ],
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
    assert compiled.quantity_values[1].canonical_value == 200_000.0
    assert compiled.quantity_values[2].canonical_value == 1.0


def test_optimization_requires_bounded_decision_variables() -> None:
    compiled = RequirementCompiler().compile(
        {
            "target": "depth_um",
            "task_type": "optimization",
            "decision_variables": [
                {
                    "quantity": "frequency_kHz",
                    "minimum": 100,
                    "maximum": 500,
                    "resolution": 10,
                    "unit": "kHz",
                }
            ],
        }
    )
    frequency = next(item for item in compiled.requirements if item.quantity == "frequency_Hz")

    assert frequency.variable_semantic == VariableSemantic.DECISION_VARIABLE
    assert frequency.supplied_value["canonical_minimum"] == 100_000.0
    assert next(
        item for item in compiled.requirements if item.quantity == "laser_power_W"
    ).variable_semantic == VariableSemantic.DECISION_VARIABLE


def test_naked_numeric_alias_is_rejected() -> None:
    with pytest.raises(TypeError, match="naked value forbidden"):
        RequirementCompiler().compile(
            {"target": "response", "task_type": "prediction"},
            {"frequency_kHz": 100.0},
        )


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
    compiled = RequirementCompiler(graph).compile(
        {"target": "response", "task_type": "prediction"}
    )

    assert compiled.selected_capabilities == ["declared-only-model"]
    assert compiled.data_requirements[0].quantity == "measured_input"


def test_ambiguous_model_provider_requires_explicit_selection() -> None:
    capabilities = [
        ModelCapability(capability_id=name, predicts=["response"])
        for name in ("model-a", "model-b")
    ]
    compiler = RequirementCompiler(ScientificDependencyGraph(capabilities))

    with pytest.raises(ValueError, match="ambiguous dependency provider"):
        compiler.compile({"target": "response", "task_type": "prediction"})

    compiled = compiler.compile(
        {
            "target": "response",
            "task_type": "prediction",
            "model_capability_id": "model-b",
        }
    )
    assert compiled.selected_capabilities == ["model-b"]
