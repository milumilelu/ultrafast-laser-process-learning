"""Mechanism model registry: which mechanisms require which parameters.

The registry is the single source of truth for mechanism-driven parameter
requirements.  Registering a new mechanism model (e.g. SATURATION_INCUBATION
requiring N_sat) automatically extends the required parameter set; the
calibration engine (ParameterIdentificationEngine) is intentionally never
edited for registry growth.  Parameters the engine cannot fit are resolved to
PRIOR or MISSING by the parameter resolver, never silently fitted.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, TypedDict


class ParameterSpec(TypedDict):
    parameter: str
    role: str
    unit: str
    bounds: tuple[float, float]
    calibration_supported: bool
    fallback: Literal["PRIOR", "MISSING"]


class MechanismRegistry:
    """Deterministic mechanism model registry.

    `MODELS` maps a mechanism model id to its required parameter specs.
    `required_parameters(active_models)` returns the union of parameters for
    the active mechanisms — adding a mechanism here is enough for the system
    to require its parameters downstream.
    """

    MODELS: ClassVar[dict[str, dict[str, ParameterSpec]]] = {
        "GAUSSIAN_BEAM": {
            "beam_radius_um": {
                "parameter": "beam_radius_um",
                "role": "OPTICAL",
                "unit": "um",
                "bounds": (1.0, 200.0),
                "calibration_supported": False,
                "fallback": "PRIOR",
            },
        },
        "LOG_ABLATION": {
            "F_th_eff": {
                "parameter": "F_th_eff",
                "role": "INTERACTION",
                "unit": "J/cm2",
                "bounds": (0.01, 20.0),
                "calibration_supported": True,
                "fallback": "PRIOR",
            },
            "delta_eff": {
                "parameter": "delta_eff",
                "role": "ABLATION",
                "unit": "um",
                "bounds": (0.001, 100.0),
                "calibration_supported": True,
                "fallback": "PRIOR",
            },
        },
        "POWER_LAW_INCUBATION": {
            "incubation_S": {
                "parameter": "incubation_S",
                "role": "INCUBATION",
                "unit": "dimensionless",
                "bounds": (0.2, 1.2),
                "calibration_supported": True,
                "fallback": "PRIOR",
            },
        },
        "SATURATION_INCUBATION": {
            "incubation_S": {
                "parameter": "incubation_S",
                "role": "INCUBATION",
                "unit": "dimensionless",
                "bounds": (0.2, 1.2),
                "calibration_supported": True,
                "fallback": "PRIOR",
            },
            "N_sat": {
                "parameter": "N_sat",
                "role": "INCUBATION",
                "unit": "pulses",
                "bounds": (2.0, 1000.0),
                "calibration_supported": False,
                "fallback": "PRIOR",
            },
        },
        "DEFOCUS_RECURSION": {
            "alpha_defocus": {
                "parameter": "alpha_defocus",
                "role": "OPTICAL",
                "unit": "1/um",
                "bounds": (0.0, 1.0),
                "calibration_supported": False,
                "fallback": "PRIOR",
            },
        },
        "THERMAL_MEMORY_PROXY": {
            "thermal_memory_eff": {
                "parameter": "thermal_memory_eff",
                "role": "THERMAL",
                "unit": "dimensionless",
                "bounds": (0.0, 1.0),
                "calibration_supported": False,
                "fallback": "PRIOR",
            },
        },
    }

    # mechanisms active by default when the task does not declare a set
    DEFAULT_ACTIVE_MODELS: ClassVar[tuple[str, ...]] = (
        "GAUSSIAN_BEAM",
        "LOG_ABLATION",
        "POWER_LAW_INCUBATION",
        "DEFOCUS_RECURSION",
        "THERMAL_MEMORY_PROXY",
    )

    @classmethod
    def is_registered(cls, model_id: str) -> bool:
        return model_id in cls.MODELS

    @classmethod
    def required_parameters(
        cls, active_models: list[str]
    ) -> list[dict[str, Any]]:
        """Union of parameter specs for the active mechanisms.

        Order is stable: first occurrence wins, matching the deterministic
        replay requirement (same input -> same parameter list).
        """
        specs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for model_id in active_models:
            if model_id not in cls.MODELS:
                raise ValueError(f"unknown mechanism model: {model_id}")
            for spec in cls.MODELS[model_id].values():
                parameter = spec["parameter"]
                if parameter in seen:
                    continue
                seen.add(parameter)
                specs.append({**spec, "source_model": model_id})
        return specs

    @classmethod
    def active_models(cls, task: dict[str, Any] | None = None) -> list[str]:
        """Active mechanism set for a task: explicit declaration wins over default."""
        declared = (task or {}).get("active_mechanism_models")
        if isinstance(declared, list) and declared:
            return [str(item) for item in declared]
        return list(cls.DEFAULT_ACTIVE_MODELS)
