"""Parameter resolver: every required parameter maps to exactly one of
MEASURED / DERIVED / PRIOR / FITTABLE / MISSING (semantic Gate 2).

Resolution is deterministic and purely declarative over the artifacts already
produced by the pipeline: capability report inputs, canonical physics state
quantities, typed priors, and the calibration result.  The resolver never
computes physics and never fabricates a value for an unresolvable parameter.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from packages.process_contracts.prior_objects import ParameterPrior
from packages.scientific_computation.contracts import (
    ArtifactRef,
    IdentifiabilityStatus,
    ScientificCapabilityReport,
)

Resolution = Literal["MEASURED", "DERIVED", "PRIOR", "FITTABLE", "MISSING"]

# alias groups used to match capability input names to registry parameter names
_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "beam_radius_um": ("beam_radius_um", "spot_radius_um", "beam_radius"),
    "actual_power_W": ("actual_power_W", "actual_power", "average_power_W", "laser_power_W"),
    "F_th_eff": ("F_th_eff", "F_th", "ablation_threshold"),
    "delta_eff": ("delta_eff", "delta"),
    "incubation_S": ("incubation_S", "s"),
    "N_sat": ("N_sat",),
    "alpha_defocus": ("alpha_defocus",),
    "thermal_memory_eff": ("thermal_memory_eff",),
    "wavelength_nm": ("wavelength_nm",),
    "pulse_width_ps": ("pulse_width_ps",),
    "frequency_kHz": ("frequency_kHz",),
    "scan_speed_mm_s": ("scan_speed_mm_s",),
    "hatch_spacing_um": ("hatch_spacing_um",),
    "passes": ("passes",),
}


def resolve_parameters(
    *,
    required: Iterable[dict[str, Any]],
    capability: ScientificCapabilityReport | dict[str, Any] | None = None,
    canonical_quantities: Iterable[str] = (),
    priors: Iterable[ParameterPrior | dict[str, Any]] = (),
    calibration_estimates: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Resolve each required parameter to exactly one of the five states.

    Priority (deterministic):
      1. FITTABLE — a calibration estimate exists and identifiability allows it
      2. MEASURED  — capability input AVAILABLE from machine/data sources
      3. DERIVED   — present in the canonical physics state (computed quantity)
      4. PRIOR     — a typed ParameterPrior covers the parameter
      5. MISSING   — nothing covers it
    """
    capability_view = (
        capability
        if isinstance(capability, ScientificCapabilityReport)
        else ScientificCapabilityReport.model_validate(capability)
        if capability is not None
        else None
    )
    prior_parameters: set[str] = set()
    for item in priors:
        prior = (
            item if isinstance(item, ParameterPrior) else ParameterPrior.model_validate(item)
        )
        if prior.conflict_status.value == "NONE":
            prior_parameters.add(prior.parameter)
    estimate_by_parameter: dict[str, dict[str, Any]] = {}
    for estimate in calibration_estimates:
        estimate_by_parameter[str(estimate.get("parameter"))] = estimate

    available_inputs: dict[str, tuple[str, list[ArtifactRef]]] = {}
    if capability_view is not None:
        for item in capability_view.available:
            available_inputs[item.name] = (item.status.value, item.source_refs)
        for item in capability_view.missing:
            available_inputs[item.name] = (item.status.value, item.source_refs)

    def matches(name: str, target: str) -> bool:
        return name.lower() in {alias.lower() for alias in _NAME_ALIASES.get(target, (target,))}

    resolutions: list[dict[str, Any]] = []
    for spec in required:
        parameter = str(spec["parameter"])
        estimate = estimate_by_parameter.get(parameter)
        if estimate and estimate.get("identifiability") != IdentifiabilityStatus.NOT_IDENTIFIABLE.value:
            resolutions.append(
                {
                    "parameter": parameter,
                    "role": spec.get("role", "OTHER"),
                    "unit": spec.get("unit", ""),
                    "source_model": spec.get("source_model", ""),
                    "resolution": "FITTABLE",
                    "reason_codes": ["calibration_estimate_available"],
                }
            )
            continue
        input_hit = next(
            ((name, status, refs) for name, (status, refs) in available_inputs.items() if matches(name, parameter)),
            None,
        )
        if input_hit and input_hit[1] == "AVAILABLE":
            source_types = [ref.type for ref in input_hit[2]]
            source_kind = (
                "machine_profile"
                if any("machine" in t.lower() or "equipment" in t.lower() for t in source_types)
                else "data"
                if any("data" in t.lower() or "observation" in t.lower() for t in source_types)
                else "other"
            )
            resolutions.append(
                {
                    "parameter": parameter,
                    "role": spec.get("role", "OTHER"),
                    "unit": spec.get("unit", ""),
                    "source_model": spec.get("source_model", ""),
                    "resolution": "MEASURED",
                    "reason_codes": [f"capability_input_available_from_{source_kind}"],
                }
            )
            continue
        if parameter in canonical_quantities or any(
            matches(str(quantity), parameter) for quantity in canonical_quantities
        ):
            resolutions.append(
                {
                    "parameter": parameter,
                    "role": spec.get("role", "OTHER"),
                    "unit": spec.get("unit", ""),
                    "source_model": spec.get("source_model", ""),
                    "resolution": "DERIVED",
                    "reason_codes": ["present_in_canonical_physics_state"],
                }
            )
            continue
        if parameter in prior_parameters:
            resolutions.append(
                {
                    "parameter": parameter,
                    "role": spec.get("role", "OTHER"),
                    "unit": spec.get("unit", ""),
                    "source_model": spec.get("source_model", ""),
                    "resolution": "PRIOR",
                    "reason_codes": ["typed_parameter_prior_available"],
                }
            )
            continue
        resolutions.append(
            {
                "parameter": parameter,
                "role": spec.get("role", "OTHER"),
                "unit": spec.get("unit", ""),
                "source_model": spec.get("source_model", ""),
                "resolution": "MISSING",
                "reason_codes": ["no_measured_derived_prior_or_fit_source"],
            }
        )
    return resolutions
