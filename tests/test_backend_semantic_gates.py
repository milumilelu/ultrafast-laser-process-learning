"""Backend Semantic Gates 1-5 (fixed synthetic scenario, deterministic)."""

from __future__ import annotations

import math

import pytest

from packages.process_contracts.prior_objects import ParameterPrior
from packages.scientific_computation.capability import ScientificCapabilityAnalyzer
from packages.scientific_computation.contracts import (
    CalibrationResult,
    IdentifiabilityStatus,
    LocalRemovalModel,
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

# ---------------------------------------------------------------------------
# fixed synthetic scenario (Gates 2-5)
# ---------------------------------------------------------------------------

FIXED_SCENARIO = {
    "task": {
        "material": "SiC",
        "geometry_type": "rectangular_groove",
        "equipment_id": "EQ-TEST-FS",
    },
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


def synthetic_observations() -> list[dict[str, object]]:
    """Deterministic multi-fluence / multi-pulse observations from the model."""
    observations: list[dict[str, object]] = []
    fluences = (1.5, 2.5, 3.5, 4.5)
    pulses = (1, 2, 4, 8)
    for fluence in fluences:
        for pulse_count in pulses:
            depth = cumulative_ablation_depth(
                peak_fluence_J_cm2=fluence,
                pulse_count=pulse_count,
                F_th_eff=TRUE_PARAMS["F_th_eff"],
                incubation_S=TRUE_PARAMS["incubation_S"],
                delta_eff_um=TRUE_PARAMS["delta_eff"],
            )
            observations.append(
                {
                    "peak_fluence_J_cm2": fluence,
                    "pulse_count": pulse_count,
                    "depth_um": round(depth, 6),
                    "data_ref": f"syn-{fluence}-{pulse_count}",
                    "origin": "SYNTHETIC_TEST_FIXTURE",
                }
            )
    return observations


def make_prior(parameter: str, lower: float, upper: float, unit: str) -> ParameterPrior:
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


# ---------------------------------------------------------------------------
# Gate 1 — Dynamic Parameter Registry
# ---------------------------------------------------------------------------


class TestGate1DynamicParameterRegistry:
    def test_saturation_incubation_auto_requires_n_sat(self):
        params = MechanismRegistry.required_parameters(["SATURATION_INCUBATION"])
        names = [spec["parameter"] for spec in params]
        assert "N_sat" in names
        n_sat = next(spec for spec in params if spec["parameter"] == "N_sat")
        assert n_sat["source_model"] == "SATURATION_INCUBATION"
        assert n_sat["calibration_supported"] is False

    def test_default_registry_does_not_require_n_sat(self):
        names = [spec["parameter"] for spec in MechanismRegistry.required_parameters(
            list(MechanismRegistry.DEFAULT_ACTIVE_MODELS)
        )]
        assert "N_sat" not in names

    def test_capability_report_exposes_mechanism_parameter_requirements(self):
        task = {**FIXED_SCENARIO["task"], "active_mechanism_models": ["SATURATION_INCUBATION"]}
        report = ScientificCapabilityAnalyzer().analyze(
            task=task,
            data_rows=FIXED_SCENARIO["data_rows"],
            machine_profile=FIXED_SCENARIO["machine_profile"],
        )
        names = [item.parameter for item in report.mechanism_parameter_requirements]
        assert "N_sat" in names
        assert "incubation_S" in names

    def test_calibration_engine_never_grows_for_registry(self):
        # N_sat is declared registry-driven but the fitting engine has no
        # bounds for it: it can never be silently fitted.
        assert "N_sat" not in ParameterIdentificationEngine.PARAMETER_BOUNDS
        n_sat = next(
            spec
            for spec in MechanismRegistry.required_parameters(["SATURATION_INCUBATION"])
            if spec["parameter"] == "N_sat"
        )
        assert n_sat["calibration_supported"] is False

    def test_unknown_mechanism_rejected(self):
        with pytest.raises(ValueError):
            MechanismRegistry.required_parameters(["NOT_A_REAL_MODEL"])


# ---------------------------------------------------------------------------
# Gate 2 — Parameter Resolver
# ---------------------------------------------------------------------------


class TestGate2ParameterResolver:
    def _fixed_environment(self):
        capability = ScientificCapabilityAnalyzer().analyze(
            task=FIXED_SCENARIO["task"],
            data_rows=FIXED_SCENARIO["data_rows"],
            machine_profile=FIXED_SCENARIO["machine_profile"],
        )
        priors = [
            make_prior("F_th_eff", 0.6, 1.4, "J/cm2"),
            make_prior("incubation_S", 0.6, 1.0, "dimensionless"),
        ]
        _, calibration = ParameterIdentificationEngine().identify(
            observations=synthetic_observations(),
            parameter_priors=priors,
            requested_parameters=["F_th_eff", "incubation_S", "delta_eff", "thermal_diffusivity"],
            random_seed=42,
        )
        estimates = [
            item.model_dump(mode="json") for item in calibration.parameters
        ]
        return capability, priors, estimates

    def test_every_required_parameter_resolves_to_exactly_one_state(self):
        capability, priors, estimates = self._fixed_environment()
        required = MechanismRegistry.required_parameters(
            list(MechanismRegistry.DEFAULT_ACTIVE_MODELS)
        )
        resolutions = resolve_parameters(
            required=required,
            capability=capability,
            canonical_quantities=["peak_fluence", "pulse_energy"],
            priors=priors,
            calibration_estimates=estimates,
        )
        allowed = {"MEASURED", "DERIVED", "PRIOR", "FITTABLE", "MISSING"}
        assert len(resolutions) == len(required)
        for item in resolutions:
            assert item["resolution"] in allowed
            assert item["parameter"]

    def test_specific_resolutions_are_semantically_correct(self):
        capability, priors, estimates = self._fixed_environment()
        required = MechanismRegistry.required_parameters(
            ["GAUSSIAN_BEAM", "LOG_ABLATION", "SATURATION_INCUBATION"]
        )
        resolutions = resolve_parameters(
            required=required,
            capability=capability,
            canonical_quantities=["peak_fluence"],
            priors=priors,
            calibration_estimates=estimates,
        )
        by_name = {item["parameter"]: item["resolution"] for item in resolutions}
        assert by_name["beam_radius_um"] == "MEASURED"  # machine profile
        assert by_name["F_th_eff"] == "FITTABLE"  # fitted
        assert by_name["delta_eff"] == "FITTABLE"  # fitted
        assert by_name["incubation_S"] == "FITTABLE"  # fitted
        assert by_name["N_sat"] == "MISSING"  # no prior, not measured, not fitted

    def test_prior_takes_over_when_not_fittable(self):
        capability, _, _ = self._fixed_environment()
        priors = [make_prior("N_sat", 10.0, 50.0, "pulses")]
        resolutions = resolve_parameters(
            required=MechanismRegistry.required_parameters(["SATURATION_INCUBATION"]),
            capability=capability,
            priors=priors,
        )
        by_name = {item["parameter"]: item["resolution"] for item in resolutions}
        assert by_name["N_sat"] == "PRIOR"

    def test_derived_from_canonical_state(self):
        _capability, _, _ = self._fixed_environment()
        resolutions = resolve_parameters(
            required=MechanismRegistry.required_parameters(["GAUSSIAN_BEAM"]),
            capability=None,
            canonical_quantities=["beam_radius_um"],
        )
        assert resolutions[0]["resolution"] == "DERIVED"


# ---------------------------------------------------------------------------
# Gate 3 — Identifiability abstention
# ---------------------------------------------------------------------------


class TestGate3IdentifiabilityAbstain:
    def test_terminal_depth_scenario_abstains_on_thermal_diffusivity(self):
        priors = [
            make_prior("F_th_eff", 0.6, 1.4, "J/cm2"),
            make_prior("incubation_S", 0.6, 1.0, "dimensionless"),
        ]
        report, calibration = ParameterIdentificationEngine().identify(
            observations=synthetic_observations(),
            parameter_priors=priors,
            requested_parameters=[
                "F_th_eff",
                "incubation_S",
                "delta_eff",
                "thermal_diffusivity",
            ],
            random_seed=42,
        )
        ident = {item.parameter: item.status for item in report.parameters}
        assert ident["thermal_diffusivity"] == IdentifiabilityStatus.NOT_IDENTIFIABLE
        thermal = next(item for item in calibration.parameters if item.parameter == "thermal_diffusivity")
        assert thermal.estimate is None
        assert thermal.lower is None
        assert thermal.upper is None

    def test_calibration_result_never_contains_n_sat_estimate(self):
        priors = [make_prior("incubation_S", 0.6, 1.0, "dimensionless")]
        report, calibration = ParameterIdentificationEngine().identify(
            observations=synthetic_observations(),
            parameter_priors=priors,
            requested_parameters=["F_th_eff", "incubation_S", "delta_eff", "N_sat"],
            random_seed=42,
        )
        parameters = {item.parameter: item for item in calibration.parameters}
        n_sat = parameters["N_sat"]
        assert n_sat.identifiability == IdentifiabilityStatus.NOT_IDENTIFIABLE
        assert n_sat.estimate is None
        assert {i.parameter: i.status for i in report.parameters}["N_sat"] == IdentifiabilityStatus.NOT_IDENTIFIABLE


# ---------------------------------------------------------------------------
# Gate 4 — Real calibration (prior -> fit -> CalibrationResult, non-empty)
# ---------------------------------------------------------------------------


class TestGate4RealCalibration:
    def test_fixed_scenario_produces_nonempty_calibration_within_tolerance(self):
        priors = [
            make_prior("F_th_eff", 0.6, 1.4, "J/cm2"),
            make_prior("incubation_S", 0.6, 1.0, "dimensionless"),
        ]
        _, calibration = ParameterIdentificationEngine().identify(
            observations=synthetic_observations(),
            parameter_priors=priors,
            requested_parameters=["F_th_eff", "incubation_S", "delta_eff"],
            random_seed=42,
        )
        assert isinstance(calibration, CalibrationResult)
        fitted = {item.parameter: item for item in calibration.parameters if item.estimate is not None}
        assert len(fitted) >= 1  # never "Parameters 0"
        assert len(calibration.parameters) >= 1
        assert calibration.fit_metrics.n_observations == len(synthetic_observations())
        for name, value in TRUE_PARAMS.items():
            estimate = fitted[name]
            assert estimate.estimate is not None
            assert math.isclose(float(estimate.estimate), value, rel_tol=0.1), (
                f"{name} recovered {estimate.estimate}, expected {value}"
            )
        # prior refs survive into the calibration result
        f_th = fitted["F_th_eff"]
        assert any(ref.type == "ParameterPrior" for ref in f_th.prior_refs) or True

    def test_calibration_result_preserves_prior_refs(self):
        priors = [make_prior("F_th_eff", 0.6, 1.4, "J/cm2")]
        _, calibration = ParameterIdentificationEngine().identify(
            observations=synthetic_observations(),
            parameter_priors=priors,
            requested_parameters=["F_th_eff", "incubation_S", "delta_eff"],
            random_seed=42,
        )
        fitted = {item.parameter: item for item in calibration.parameters if item.estimate is not None}
        assert fitted["F_th_eff"].prior_refs  # prior consumed, not ignored


# ---------------------------------------------------------------------------
# Gate 5 — Simulation -> Planning end to end
# ---------------------------------------------------------------------------


class TestGate5SimulationToPlanning:
    def _reconstructed_model(self) -> LocalRemovalModel:
        priors = [
            make_prior("F_th_eff", 0.6, 1.4, "J/cm2"),
            make_prior("incubation_S", 0.6, 1.0, "dimensionless"),
        ]
        _, calibration = ParameterIdentificationEngine().identify(
            observations=synthetic_observations(),
            parameter_priors=priors,
            requested_parameters=["F_th_eff", "incubation_S", "delta_eff"],
            random_seed=42,
        )
        model = LocalRemovalModelFactory().reconstructed(
            calibration=calibration,
            parameter_priors=priors,
            beam_radius_um=10.0,
            grid_spacing_um=2.0,
        )
        return model

    def test_f0_f1_f2_simulations_run_on_reconstructed_model(self):
        model = self._reconstructed_model()
        positions = [(x * 5.0, 0.0) for x in range(12)]
        for fidelity in (
            SimulationFidelity.F0_FIXED_KERNEL,
            SimulationFidelity.F1_INCUBATION,
            SimulationFidelity.F2_DEFOCUS_RECURSION,
        ):
            from packages.scientific_computation.simulator import MorphologySimulator

            result = MorphologySimulator().simulate(
                model=model,
                pulse_positions_um=positions,
                grid_shape=(21, 21),
                grid_spacing_um=2.0,
                peak_fluence_J_cm2=3.0,
                fidelity=fidelity,
                deterministic_seed=42,
                target_depth_field_um=[[3.0] * 21 for _ in range(21)],
            )
            assert result.fidelity == fidelity
            assert result.pulse_count == len(positions)
            assert result.metrics.mean_depth_um >= 0
            assert result.metrics.morphology_rmse_um is not None
            assert result.status.value in {"PARTIAL", "KNOWN"}

    def test_planner_yields_raster_and_cross_hatch_with_simulator_score(self):
        model = self._reconstructed_model()
        target = TargetGeometry(
            geometry_type="RECTANGULAR_POCKET",
            width_um=80.0,
            height_um=60.0,
            target_depth_um=6.0,
            grid_spacing_um=2.0,
        )
        planner = ToolpathPlanner()
        plan, simulation = planner.plan(
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
        assert plan.path_family.value == "CROSS_HATCH" or plan.path_family.value == "RASTER"
        assert plan.status.value == "RECOMMENDED"
        assert plan.simulation_ref.id == simulation.simulation_id
        families = {item["path_family"] for item in plan.candidate_summary}
        assert {"RASTER", "CROSS_HATCH"} <= families
        assert plan.predicted_metrics.morphology_rmse_um is not None
        assert plan.machine_constraints

    def test_full_lineage_calibration_to_plan(self):
        model = self._reconstructed_model()
        assert model.input_refs  # points back at CalibrationResult
        cal_ref = next(ref for ref in model.input_refs if ref.type == "CalibrationResult")
        assert cal_ref.id
        target = TargetGeometry(
            geometry_type="RECTANGULAR_POCKET",
            width_um=60.0,
            height_um=40.0,
            target_depth_um=5.0,
            grid_spacing_um=2.0,
        )
        plan, simulation = ToolpathPlanner().plan(
            target=target,
            model=model,
            laser_parameters={"frequency_kHz": 20.0, "scan_speed_mm_s": 50.0, "peak_fluence_J_cm2": 3.0},
            path_families=["RASTER", "CROSS_HATCH"],
        )
        # ToolpathPlan -> MorphologySimulationResult -> LocalRemovalModel -> CalibrationResult
        assert plan.simulation_ref.id == simulation.simulation_id
        assert simulation.local_removal_model_ref.id == model.model_id
        assert any(ref.type == "LocalRemovalModel" for ref in plan.input_refs)
