"""Backend Semantic Gates 1-5 acceptance runner.

Run:  python scripts/run_backend_semantic_gates.py
Exit:  0 when every gate PASSes, 1 otherwise.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.process_contracts.prior_objects import ParameterPrior
from packages.scientific_computation.capability import ScientificCapabilityAnalyzer
from packages.scientific_computation.contracts import (
    EvidenceOrigin,
    IdentifiabilityStatus,
    SimulationFidelity,
    TargetGeometry,
)
from packages.scientific_computation.identification import (
    ParameterIdentificationEngine,
    cumulative_ablation_depth,
)
from packages.scientific_computation.local_removal import LocalRemovalModelFactory
from packages.scientific_computation.mechanism_registry import MechanismRegistry
from packages.scientific_computation.parameter_resolver import resolve_parameters
from packages.scientific_computation.planning import ToolpathPlanner
from packages.scientific_computation.simulator import MorphologySimulator

FIXED_SCENARIO = {
    "task": {"material": "SiC", "geometry_type": "rectangular_groove", "equipment_id": "EQ-TEST-FS"},
    "machine_profile": {
        "actual_power_W": 5.0,
        "beam_radius_um": 10.0,
        "wavelength_nm": 1030.0,
        "verified": True,
    },
    "data_rows": [
        {"pulse_width_ps": 0.5, "frequency_kHz": 10, "scan_speed_mm_s": 20, "hatch_spacing_um": 4, "passes": passes}
        for passes in (1, 2, 4, 8)
    ],
}

TRUE_PARAMS = {"F_th_eff": 1.0, "incubation_S": 0.8, "delta_eff": 0.5}


def synthetic_observations():
    observations = []
    for fluence in (1.5, 2.5, 3.5, 4.5):
        for pulse_count in (1, 2, 4, 8):
            depth = cumulative_ablation_depth(
                fluence, pulse_count, TRUE_PARAMS["F_th_eff"], TRUE_PARAMS["incubation_S"], TRUE_PARAMS["delta_eff"]
            )
            observations.append(
                {
                    "peak_fluence_J_cm2": fluence,
                    "pulse_count": pulse_count,
                    "depth_um": round(depth, 6),
                    "data_ref": f"syn-{fluence}-{pulse_count}",
                    "origin": EvidenceOrigin.SYNTHETIC_TEST_FIXTURE.value,
                }
            )
    return observations


def make_prior(parameter, lower, upper, unit):
    return ParameterPrior(
        prior_id=f"prior-{parameter}",
        parameter=parameter,
        lower=lower,
        upper=upper,
        unit=unit,
        uncertainty="MEDIUM",
        status="EXTERNAL_PRIOR",
        evidence_refs=[{"type": "EvidenceIR", "id": f"evidence-{parameter}"}],
        provenance=[{"type": "EvidenceIR", "id": f"evidence-{parameter}"}],
    )


def gate1() -> tuple[bool, str]:
    params = MechanismRegistry.required_parameters(["SATURATION_INCUBATION"])
    names = [spec["parameter"] for spec in params]
    if "N_sat" not in names:
        return False, "SATURATION_INCUBATION did not require N_sat"
    n_sat = next(spec for spec in params if spec["parameter"] == "N_sat")
    if n_sat["calibration_supported"] is not False:
        return False, "N_sat must be calibration_supported=False (engine untouched)"
    if "N_sat" in ParameterIdentificationEngine.PARAMETER_BOUNDS:
        return False, "calibration engine was modified for the registry"
    report = ScientificCapabilityAnalyzer().analyze(
        task={**FIXED_SCENARIO["task"], "active_mechanism_models": ["SATURATION_INCUBATION"]},
        data_rows=FIXED_SCENARIO["data_rows"],
        machine_profile=FIXED_SCENARIO["machine_profile"],
    )
    report_names = [item.parameter for item in report.mechanism_parameter_requirements]
    if "N_sat" not in report_names:
        return False, "capability report did not expose N_sat as mechanism parameter"
    return True, "SATURATION_INCUBATION -> N_sat auto-required (engine untouched)"


def gate2() -> tuple[bool, str]:
    capability = ScientificCapabilityAnalyzer().analyze(
        task=FIXED_SCENARIO["task"],
        data_rows=FIXED_SCENARIO["data_rows"],
        machine_profile=FIXED_SCENARIO["machine_profile"],
    )
    priors = [make_prior("F_th_eff", 0.6, 1.4, "J/cm2"), make_prior("incubation_S", 0.6, 1.0, "dimensionless")]
    _, calibration = ParameterIdentificationEngine().identify(
        observations=synthetic_observations(),
        parameter_priors=priors,
        requested_parameters=["F_th_eff", "incubation_S", "delta_eff", "thermal_diffusivity"],
        random_seed=42,
    )
    required = MechanismRegistry.required_parameters(
        ["GAUSSIAN_BEAM", "LOG_ABLATION", "SATURATION_INCUBATION"]
    )
    resolutions = resolve_parameters(
        required=required,
        capability=capability,
        canonical_quantities=["peak_fluence"],
        priors=priors,
        calibration_estimates=[item.model_dump(mode="json") for item in calibration.parameters],
    )
    allowed = {"MEASURED", "DERIVED", "PRIOR", "FITTABLE", "MISSING"}
    by_name = {item["parameter"]: item["resolution"] for item in resolutions}
    if len(resolutions) != len(required) or any(item["resolution"] not in allowed for item in resolutions):
        return False, "not every required parameter resolved to one of the five states"
    expected = {
        "beam_radius_um": "MEASURED",
        "F_th_eff": "FITTABLE",
        "delta_eff": "FITTABLE",
        "incubation_S": "FITTABLE",
        "N_sat": "MISSING",
    }
    for parameter, resolution in expected.items():
        if by_name.get(parameter) != resolution:
            return False, f"{parameter} resolved to {by_name.get(parameter)}, expected {resolution}"
    return True, "every required parameter resolved (MEASURED/DERIVED/PRIOR/FITTABLE/MISSING)"


def gate3() -> tuple[bool, str]:
    priors = [make_prior("F_th_eff", 0.6, 1.4, "J/cm2"), make_prior("incubation_S", 0.6, 1.0, "dimensionless")]
    report, calibration = ParameterIdentificationEngine().identify(
        observations=synthetic_observations(),
        parameter_priors=priors,
        requested_parameters=["F_th_eff", "incubation_S", "delta_eff", "thermal_diffusivity"],
        random_seed=42,
    )
    ident = {item.parameter: item.status for item in report.parameters}
    if ident["thermal_diffusivity"] != IdentifiabilityStatus.NOT_IDENTIFIABLE:
        return False, "thermal_diffusivity must abstain (NOT_IDENTIFIABLE)"
    thermal = next(item for item in calibration.parameters if item.parameter == "thermal_diffusivity")
    if thermal.estimate is not None or thermal.lower is not None or thermal.upper is not None:
        return False, "NOT_IDENTIFIABLE parameter must not expose an estimate"
    return True, "thermal_diffusivity NOT_IDENTIFIABLE with withheld estimate (abstain OK)"


def gate4() -> tuple[bool, str]:
    priors = [make_prior("F_th_eff", 0.6, 1.4, "J/cm2"), make_prior("incubation_S", 0.6, 1.0, "dimensionless")]
    _, calibration = ParameterIdentificationEngine().identify(
        observations=synthetic_observations(),
        parameter_priors=priors,
        requested_parameters=["F_th_eff", "incubation_S", "delta_eff"],
        random_seed=42,
    )
    fitted = {item.parameter: item for item in calibration.parameters if item.estimate is not None}
    if len(fitted) == 0:
        return False, "CalibrationResult must not be empty (Parameters 0)"
    for name, value in TRUE_PARAMS.items():
        if not math.isclose(float(fitted[name].estimate), value, rel_tol=0.1):
            return False, f"{name} recovered {fitted[name].estimate}, expected {value}"
    return True, f"prior -> fit -> CalibrationResult with {len(fitted)} fitted parameters within tolerance"


def gate5() -> tuple[bool, str]:
    priors = [make_prior("F_th_eff", 0.6, 1.4, "J/cm2"), make_prior("incubation_S", 0.6, 1.0, "dimensionless")]
    _, calibration = ParameterIdentificationEngine().identify(
        observations=synthetic_observations(),
        parameter_priors=priors,
        requested_parameters=["F_th_eff", "incubation_S", "delta_eff"],
        random_seed=42,
    )
    model = LocalRemovalModelFactory().reconstructed(
        calibration=calibration, parameter_priors=priors, beam_radius_um=10.0, grid_spacing_um=2.0
    )
    positions = [(x * 5.0, 0.0) for x in range(12)]
    for fidelity in (
        SimulationFidelity.F0_FIXED_KERNEL,
        SimulationFidelity.F1_INCUBATION,
        SimulationFidelity.F2_DEFOCUS_RECURSION,
    ):
        simulation = MorphologySimulator().simulate(
            model=model,
            pulse_positions_um=positions,
            grid_shape=(21, 21),
            grid_spacing_um=2.0,
            peak_fluence_J_cm2=3.0,
            fidelity=fidelity,
            deterministic_seed=42,
            target_depth_field_um=[[3.0] * 21 for _ in range(21)],
        )
        if simulation.metrics.morphology_rmse_um is None:
            return False, f"simulation at {fidelity.value} produced no rmse"
    target = TargetGeometry(
        geometry_type="RECTANGULAR_POCKET",
        width_um=80.0,
        height_um=60.0,
        target_depth_um=6.0,
        grid_spacing_um=2.0,
    )
    plan, plan_simulation = ToolpathPlanner().plan(
        target=target,
        model=model,
        laser_parameters={"frequency_kHz": 20.0, "scan_speed_mm_s": 50.0, "peak_fluence_J_cm2": 3.0},
        machine_constraints=[
            {"name": "frequency_kHz", "lower": 2.0, "upper": 200.0, "unit": "kHz"},
            {"name": "scan_speed_mm_s", "lower": 20.0, "upper": 80.0, "unit": "mm/s"},
        ],
        path_families=["RASTER", "CROSS_HATCH"],
        fidelity=SimulationFidelity.F2_DEFOCUS_RECURSION,
        deterministic_seed=42,
    )
    families = {item["path_family"] for item in plan.candidate_summary}
    if {"RASTER", "CROSS_HATCH"} > families:
        return False, "planner did not produce RASTER and CROSS_HATCH candidates"
    if plan.status.value != "RECOMMENDED":
        return False, "no recommended ToolpathPlan"
    if plan.simulation_ref.id != plan_simulation.simulation_id:
        return False, "ToolpathPlan simulation_ref does not resolve"
    return True, "Calibration -> LocalRemovalModel -> F0/F1/F2 -> RASTER/CROSS_HATCH -> ToolpathPlan"


def main() -> int:
    gates = {
        "G1_dynamic_parameter_registry": gate1,
        "G2_parameter_resolver": gate2,
        "G3_identifiability_abstain": gate3,
        "G4_real_calibration": gate4,
        "G5_simulation_to_planning": gate5,
    }
    results = {}
    for name, runner in gates.items():
        try:
            passed, detail = runner()
        except Exception as exc:  # noqa: BLE001 - acceptance runner reports any failure
            passed, detail = False, f"exception: {exc!r}"
        results[name] = {"status": "PASS" if passed else "FAIL", "detail": detail}
    overall = all(item["status"] == "PASS" for item in results.values())
    report = {"overall_status": "PASS" if overall else "FAIL", "gates": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
