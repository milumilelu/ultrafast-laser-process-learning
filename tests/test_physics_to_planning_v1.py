"""Independent backend acceptance tests for Physics-to-Planning V1 (B1-B9)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from apps.topic2_backend.application.service import ALL_STAGES, Topic2ApplicationService
from apps.topic2_backend.service import Topic2Service
from apps.topic2_backend.settings import Settings
from packages.e2p.application.typed_prior_compiler import compile_typed_priors
from packages.e2p.domain.prior_objects import (
    MechanismModelPrior,
    ParameterPrior,
    PlanningPreferencePrior,
)
from packages.scientific_computation.canonicalization import PhysicsCanonicalizer
from packages.scientific_computation.capability import ScientificCapabilityAnalyzer
from packages.scientific_computation.contracts import (
    AvailabilityStatus,
    EvidenceOrigin,
    IdentifiabilityStatus,
    ParameterObservation,
    PathFamily,
    RemovalKernel,
    ScientificStatus,
    SimulationFidelity,
    TargetGeometry,
)
from packages.scientific_computation.identification import (
    ParameterIdentificationEngine,
    cumulative_ablation_depth,
)
from packages.scientific_computation.local_removal import LocalRemovalModelFactory
from packages.scientific_computation.planning import ToolpathPlanner
from packages.scientific_computation.simulator import MorphologySimulator
from packages.scientific_retrieval import (
    RetrievalCandidate,
    plan_retrieval,
    rank_candidates,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def physics_app(tmp_path: Path) -> Topic2ApplicationService:
    base = Settings.from_env()
    service = Topic2Service(
        replace(
            base,
            database_path=tmp_path / "physics-to-planning.db",
            artifact_dir=tmp_path / "artifacts",
            report_dir=tmp_path / "reports",
            fixture_path=REPO / "data" / "test_fixture" / "topic2_experiments_v1.csv",
        ),
        approval_verifier=lambda _review_id: False,
    )
    return Topic2ApplicationService(service)


def _task() -> dict:
    return {
        "task_context_id": "P2P-V1-ACCEPTANCE",
        "task_context_version": 1,
        "material": "SiC",
        "laser_type": "fs",
        "equipment_profile_id": "EQ-TEST-FS",
        "geometry_type": "rectangular_groove",
        "objective_metric": "depth_um",
        "target_geometry": {
            "width_um": 30.0,
            "height_um": 24.0,
            "target_depth_um": 2.0,
            "grid_spacing_um": 2.0,
        },
        "machine_profile": {
            "actual_power_W": 10.0,
            "actual_power_W_verified": True,
            "beam_radius_um": 8.0,
            "beam_radius_um_verified": True,
            "wavelength_nm": 1030.0,
            "wavelength_nm_verified": True,
        },
        "evidence_ir": [
            {
                "evidence_id": "E-FTH-001",
                "claim_type": "threshold",
                "parameter": "F_th_eff",
                "claim": {
                    "lower": 0.65,
                    "upper": 0.95,
                    "unit": "J/cm2",
                    "parameter_semantics": "PROVISIONAL",
                },
                "review_status": "approved",
                "applicability_status": "PARTIAL",
            },
            {
                "evidence_id": "E-MECH-001",
                "claim_type": "mechanism_model",
                "claim": {
                    "model_family": "POWER_LAW_INCUBATION",
                    "alternatives": ["SATURATION_INCUBATION"],
                },
                "review_status": "approved",
                "applicability_status": "PARTIAL",
            },
            {
                "evidence_id": "E-PATH-001",
                "claim_type": "path_strategy",
                "claim": {
                    "path_families": ["CROSS_HATCH"],
                    "preference": "cross hatch is a soft candidate for shallow pockets",
                },
                "review_status": "approved",
                "applicability_status": "UNKNOWN",
            },
        ],
        "calibration_observations": _synthetic_observations(),
    }


def _synthetic_observations() -> list[dict]:
    values = []
    for fluence in (1.2, 1.8, 2.5, 3.2):
        for pulse_count in (1, 3, 7):
            values.append(
                ParameterObservation(
                    peak_fluence_J_cm2=fluence,
                    pulse_count=pulse_count,
                    depth_um=cumulative_ablation_depth(fluence, pulse_count, 0.8, 0.78, 0.45),
                    data_ref=f"SYN-{fluence}-{pulse_count}",
                    origin=EvidenceOrigin.SYNTHETIC_TEST_FIXTURE,
                ).model_dump(mode="json")
            )
    return values


def _synthetic_kernel() -> RemovalKernel:
    return RemovalKernel(
        shape="MEASURED_GRID",
        radius_um=2.0,
        peak_depth_um=1.0,
        grid_spacing_um=1.0,
        values_um=[
            [0.1, 0.2, 0.1],
            [0.2, 1.0, 0.2],
            [0.1, 0.2, 0.1],
        ],
        origin=EvidenceOrigin.SYNTHETIC_TEST_FIXTURE,
    )


def test_capability_preflight() -> None:
    rows = [
        {
            "pulse_width_ps": 0.5,
            "frequency_kHz": 100.0,
            "scan_speed_mm_s": 50.0,
            "hatch_spacing_um": 5.0,
            "passes": 2,
            "depth_um": 4.0,
        }
    ]
    task = {
        "task_context_id": "T",
        "material": "SiC",
        "geometry_type": "rectangular_groove",
        "equipment_id": "EQ",
    }
    analyzer = ScientificCapabilityAnalyzer()
    first = analyzer.analyze(task=task, data_rows=rows)
    second = analyzer.analyze(task=task, data_rows=rows)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.simulation_supported is True
    assert {item.name for item in first.missing} >= {"actual_power_W", "beam_radius_um"}
    assert first.recommended_requirements
    assert all(
        item.required_for and item.trigger_reasons for item in first.recommended_requirements
    )
    thermal = next(
        item for item in first.identifiability if item.parameter == "thermal_diffusivity"
    )
    assert thermal.status == IdentifiabilityStatus.NOT_IDENTIFIABLE
    empty = analyzer.analyze(task=task, data_rows=[])
    assert empty.simulation_supported is False
    assert empty.status == ScientificStatus.UNKNOWN


def test_physics_canonicalization_shared_transform() -> None:
    inputs = {
        "average_power_W": 10.0,
        "frequency_kHz": 100.0,
        "pulse_width_ps": 0.5,
        "scan_speed_mm_s": 50.0,
        "hatch_spacing_um": 5.0,
        "beam_radius_um": 8.0,
        "passes": 2,
        "F_th_eff_J_cm2": 0.8,
    }
    verified = set(inputs)
    canonicalizer = PhysicsCanonicalizer()
    source_state = canonicalizer.canonicalize(inputs, verified_inputs=verified)
    target_state = canonicalizer.canonicalize(dict(inputs), verified_inputs=verified)

    assert source_state == target_state
    assert source_state.missing_inputs == []
    assert source_state.quantities["pulse_energy"].value == pytest.approx(100.0)
    assert source_state.quantities["pulse_energy"].unit == "uJ"
    assert source_state.quantities["pulse_spacing"].value == pytest.approx(0.5)
    assert source_state.quantities["normalized_fluence"].status == AvailabilityStatus.AVAILABLE
    assert source_state.status == ScientificStatus.KNOWN


def test_requirement_from_computation_gap() -> None:
    report = ScientificCapabilityAnalyzer().analyze(
        task={
            "task_context_id": "T",
            "material": "SiC",
            "geometry_type": "rectangular_groove",
            "equipment_id": "EQ",
        },
        data_rows=[
            {
                "pulse_width_ps": 0.5,
                "frequency_kHz": 100,
                "scan_speed_mm_s": 50,
                "hatch_spacing_um": 5,
                "passes": 2,
                "depth_um": 4,
            }
        ],
    )
    by_required_for = {item.required_for: item for item in report.recommended_requirements}
    assert "PhysicsCanonicalization.peak_fluence" in by_required_for
    assert "LocalRemovalModel.F_th_eff" in by_required_for
    assert by_required_for["LocalRemovalModel.F_th_eff"].priority == "high"


def test_geometry_not_hard_retrieval_filter() -> None:
    plan = plan_retrieval(
        {
            "requirement_id": "KR-FTH",
            "type": "PARAMETER_PRIOR",
            "scientific_question": "Need SiC ablation threshold",
        },
        {
            "material": "SiC",
            "laser_type": "fs",
            "geometry_type": "rectangular_groove",
            "target": "depth_um",
        },
    )
    assert plan.geometry_is_hard_filter is False
    assert "rectangular_groove" in plan.soft_facets["target_geometry_hint"]
    ranked = rank_candidates(
        plan,
        [
            RetrievalCandidate(
                candidate_id="surface",
                title="Femtosecond SiC surface ablation threshold",
                material="SiC",
                geometry="surface",
                evidence_roles=["threshold"],
            ),
            RetrievalCandidate(
                candidate_id="circle",
                title="Threshold of circular SiC features",
                material="SiC",
                geometry="circle",
                evidence_roles=["threshold"],
            ),
            RetrievalCandidate(
                candidate_id="groove",
                title="SiC groove ablation threshold",
                material="SiC",
                geometry="rectangular_groove",
                evidence_roles=["threshold"],
            ),
            RetrievalCandidate(
                candidate_id="other",
                title="Metal rectangular groove",
                material="steel",
                geometry="rectangular_groove",
                evidence_roles=["threshold"],
            ),
        ],
    )
    ids = {item.candidate.candidate_id for item in ranked}
    assert {"surface", "circle", "groove"}.issubset(ids)
    assert "other" not in ids


def test_e2p_prior_contract() -> None:
    result = compile_typed_priors(
        [
            {
                "evidence_id": "E1",
                "claim_type": "threshold",
                "parameter": "F_th_eff",
                "claim": {"lower": 0.5, "upper": 0.8, "unit": "J/cm2"},
                "review_status": "approved",
                "applicability_status": "PARTIAL",
            },
            {
                "evidence_id": "E2",
                "claim_type": "threshold",
                "parameter": "F_th_eff",
                "claim": {"lower": 1.2, "upper": 1.5, "unit": "J/cm2"},
                "review_status": "approved",
                "applicability_status": "UNKNOWN",
            },
            {
                "evidence_id": "E3",
                "claim_type": "mechanism_model",
                "claim": {"model_family": "POWER_LAW_INCUBATION"},
                "review_status": "approved",
            },
            {
                "evidence_id": "E4",
                "claim_type": "path_strategy",
                "claim": {"path_families": ["RASTER"], "preference": "soft raster preference"},
                "review_status": "approved",
            },
        ]
    )
    assert sum(isinstance(item, ParameterPrior) for item in result.priors) == 2
    assert any(isinstance(item, MechanismModelPrior) for item in result.priors)
    assert any(isinstance(item, PlanningPreferencePrior) for item in result.priors)
    assert result.conflicts and all(
        item.conflict_status.value == "CONFLICT"
        for item in result.priors
        if isinstance(item, ParameterPrior)
    )
    payload = result.model_dump(mode="json")
    assert "probability" not in str(payload).lower()
    assert all(item.evidence_refs and item.provenance for item in result.priors)


def test_parameter_prior_calibration() -> None:
    prior_set = compile_typed_priors(
        [
            {
                "evidence_id": "EP",
                "claim_type": "threshold",
                "parameter": "F_th_eff",
                "claim": {"lower": 0.6, "upper": 1.0, "unit": "J/cm2"},
                "review_status": "approved",
                "applicability_status": "PARTIAL",
            }
        ]
    )
    prior = next(item for item in prior_set.priors if isinstance(item, ParameterPrior))
    report, calibration = ParameterIdentificationEngine().identify(
        _synthetic_observations(), parameter_priors=[prior], random_seed=7
    )
    values = {item.parameter: item for item in calibration.parameters}
    assert values["F_th_eff"].estimate == pytest.approx(0.8, rel=0.03)
    assert values["incubation_S"].estimate == pytest.approx(0.78, rel=0.03)
    assert values["delta_eff"].estimate == pytest.approx(0.45, rel=0.03)
    assert values["F_th_eff"].prior_refs[0].id == prior.prior_id
    assert values["thermal_diffusivity"].identifiability == IdentifiabilityStatus.NOT_IDENTIFIABLE
    assert values["thermal_diffusivity"].estimate is None
    assert calibration.validation_data_refs == []
    assert report.schema_version and calibration.schema_version


def test_parameter_identifiability() -> None:
    report, calibration = ParameterIdentificationEngine().identify_from_macro_rows(
        [{"depth_um": 3.0, "passes": 1}, {"depth_um": 8.0, "passes": 2}]
    )
    thermal = next(item for item in report.parameters if item.parameter == "thermal_diffusivity")
    estimate = next(
        item for item in calibration.parameters if item.parameter == "thermal_diffusivity"
    )
    assert thermal.status == IdentifiabilityStatus.NOT_IDENTIFIABLE
    assert estimate.estimate is None
    delta = next(item for item in calibration.parameters if item.parameter == "delta_eff")
    assert delta.parameter_semantics.value == "EFFECTIVE"


def test_simulator_fixed_kernel() -> None:
    factory = LocalRemovalModelFactory()
    empirical = factory.empirical(
        kernel=_synthetic_kernel(),
        threshold_J_cm2=1.0,
        incubation_S=0.75,
        delta_um=1.0,
        alpha_defocus_per_um=0.2,
    )
    assert empirical.mode.value == "EMPIRICAL"
    assert "not experimental validation" in " ".join(empirical.assumptions)
    simulator = MorphologySimulator()
    single = simulator.simulate(
        model=empirical,
        pulse_positions_um=[(0.0, 0.0)],
        grid_shape=(9, 9),
        grid_spacing_um=1.0,
        peak_fluence_J_cm2=2.0,
        fidelity=SimulationFidelity.F0_FIXED_KERNEL,
    )
    depth = simulator.removal_depth_field(single)
    assert depth[3:6, 3:6] == pytest.approx(np.asarray(_synthetic_kernel().values_um))
    far = simulator.simulate(
        model=empirical,
        pulse_positions_um=[(-3.0, 0.0), (3.0, 0.0)],
        grid_shape=(11, 11),
        grid_spacing_um=1.0,
        peak_fluence_J_cm2=2.0,
        fidelity="F0_FIXED_KERNEL",
    )
    replay = simulator.simulate(
        model=empirical,
        pulse_positions_um=[(-3.0, 0.0), (3.0, 0.0)],
        grid_shape=(11, 11),
        grid_spacing_um=1.0,
        peak_fluence_J_cm2=2.0,
        fidelity="F0_FIXED_KERNEL",
    )
    assert far.model_dump(mode="json") == replay.model_dump(mode="json")
    f1_one = simulator.simulate(
        model=empirical,
        pulse_positions_um=[(0, 0)],
        grid_shape=(11, 11),
        peak_fluence_J_cm2=2,
        fidelity="F1_INCUBATION",
    )
    f1_two = simulator.simulate(
        model=empirical,
        pulse_positions_um=[(0, 0), (0, 0)],
        grid_shape=(11, 11),
        peak_fluence_J_cm2=2,
        fidelity="F1_INCUBATION",
    )
    assert f1_two.metrics.max_depth_um > 2 * f1_one.metrics.max_depth_um
    f2 = simulator.simulate(
        model=empirical,
        pulse_positions_um=[(0, 0), (0, 0)],
        grid_shape=(11, 11),
        peak_fluence_J_cm2=2,
        fidelity="F2_DEFOCUS_RECURSION",
    )
    assert f2.state.height_field_um != f1_two.state.height_field_um
    with pytest.raises(ValueError):
        simulator.simulate(model=empirical, pulse_positions_um=[(0, 0)], peak_fluence_J_cm2=-1)

    _, calibration = ParameterIdentificationEngine().identify(_synthetic_observations())
    reconstructed = factory.reconstructed(calibration=calibration, beam_radius_um=8)
    hybrid = factory.hybrid(empirical_kernel=_synthetic_kernel(), calibration=calibration)
    assert {empirical.mode.value, reconstructed.mode.value, hybrid.mode.value} == {
        "EMPIRICAL",
        "RECONSTRUCTED",
        "HYBRID",
    }
    assert type(empirical) is type(reconstructed) is type(hybrid)


def test_simulator_incubation() -> None:
    model = LocalRemovalModelFactory().empirical(
        kernel=_synthetic_kernel(), threshold_J_cm2=1.0, incubation_S=0.7, delta_um=1.0
    )
    simulator = MorphologySimulator()
    one = simulator.simulate(
        model=model,
        pulse_positions_um=[(0, 0)],
        grid_shape=(9, 9),
        peak_fluence_J_cm2=2,
        fidelity="F1_INCUBATION",
    )
    two = simulator.simulate(
        model=model,
        pulse_positions_um=[(0, 0), (0, 0)],
        grid_shape=(9, 9),
        peak_fluence_J_cm2=2,
        fidelity="F1_INCUBATION",
    )
    assert two.metrics.max_depth_um > 2 * one.metrics.max_depth_um


def test_simulator_defocus_state_update() -> None:
    model = LocalRemovalModelFactory().empirical(
        kernel=_synthetic_kernel(),
        threshold_J_cm2=1.0,
        incubation_S=0.8,
        delta_um=1.0,
        alpha_defocus_per_um=0.3,
    )
    simulator = MorphologySimulator()
    f0 = simulator.simulate(
        model=model,
        pulse_positions_um=[(0, 0), (0, 0)],
        grid_shape=(11, 11),
        peak_fluence_J_cm2=2,
        fidelity="F0_FIXED_KERNEL",
    )
    f2 = simulator.simulate(
        model=model,
        pulse_positions_um=[(0, 0), (0, 0)],
        grid_shape=(11, 11),
        peak_fluence_J_cm2=2,
        fidelity="F2_DEFOCUS_RECURSION",
    )
    assert f2.state.height_field_um != f0.state.height_field_um
    assert f2.state.effective_pulse_count != f0.state.effective_pulse_count


def test_local_removal_modes() -> None:
    factory = LocalRemovalModelFactory()
    empirical = factory.empirical(kernel=_synthetic_kernel(), threshold_J_cm2=1.0)
    _, calibration = ParameterIdentificationEngine().identify(_synthetic_observations())
    reconstructed = factory.reconstructed(calibration=calibration, beam_radius_um=8)
    hybrid = factory.hybrid(empirical_kernel=_synthetic_kernel(), calibration=calibration)
    assert [item.mode.value for item in (empirical, reconstructed, hybrid)] == [
        "EMPIRICAL",
        "RECONSTRUCTED",
        "HYBRID",
    ]
    assert all(item.schema_version for item in (empirical, reconstructed, hybrid))


def test_toolpath_simulator_loop() -> None:
    _, calibration = ParameterIdentificationEngine().identify(_synthetic_observations())
    model = LocalRemovalModelFactory().reconstructed(calibration=calibration, beam_radius_um=6)
    plan, simulation = ToolpathPlanner().plan(
        target=TargetGeometry(
            geometry_type="RECTANGULAR_POCKET",
            width_um=24,
            height_um=20,
            target_depth_um=2,
            grid_spacing_um=2,
        ),
        model=model,
        laser_parameters={"frequency_kHz": 100, "scan_speed_mm_s": 100, "peak_fluence_J_cm2": 2.0},
        path_families=(PathFamily.RASTER, PathFamily.CROSS_HATCH),
    )
    assert plan.path_family in {PathFamily.RASTER, PathFamily.CROSS_HATCH}
    assert plan.status.value == "RECOMMENDED"
    assert len(plan.candidate_summary) >= 2
    assert plan.simulation_ref.id == simulation.simulation_id
    assert plan.predicted_metrics.morphology_rmse_um is not None


def test_full_physics_to_planning_run(physics_app: Topic2ApplicationService) -> None:
    summary = physics_app.create_application_run(mode="research", task_spec=_task(), random_seed=42)
    assert summary["status"] == "completed"
    run_id = summary["application_run_id"]
    run = physics_app.get_run(run_id)
    assert set(run["stage_status"]) == set(ALL_STAGES)
    artifacts = physics_app.artifacts(run_id)
    by_type = {item["artifact_type"]: item["artifact_id"] for item in artifacts}
    required = {
        "ScientificCapabilityReport",
        "KnowledgeRequirementSet",
        "EvidenceIRSet",
        "PriorObjectSet",
        "CanonicalPhysicsState",
        "IdentifiabilityReport",
        "CalibrationResult",
        "PhysicalModelState",
        "LocalRemovalModel",
        "MorphologySimulationResult",
        "ProcessLearningResult",
        "ProcessCorrectionInterface",
        "ToolpathPlan",
    }
    assert required.issubset(by_type)
    for artifact_type in required:
        stored = physics_app.artifact(by_type[artifact_type])["content"]
        assert stored["id"] == by_type[artifact_type]
        assert stored["type"] == artifact_type
        assert stored["schema_version"]
        assert isinstance(stored["input_refs"], list)

    plan_snapshot = physics_app.artifact(by_type["ToolpathPlan"])["content"]
    plan = plan_snapshot["content"]
    assert plan["simulation_ref"]["id"] == by_type["MorphologySimulationResult"]
    assert {ref["id"] for ref in plan_snapshot["input_refs"]} >= {
        by_type["MorphologySimulationResult"],
        by_type["LocalRemovalModel"],
        by_type["CanonicalPhysicsState"],
        by_type["PriorObjectSet"],
    }
    result = run["result"]["physicsToPlanning"]
    assert result["toolpathPlan"]["status"] == "RECOMMENDED"
    assert result["morphologySimulation"]["fidelity"] == "F2_DEFOCUS_RECURSION"
    assert result["morphologySimulation"]["target_depth_field_um"] is not None
    assert result["morphologySimulation"]["predicted_depth_field_um"]
    assert result["morphologySimulation"]["difference_field_um"] is not None
    assert result["calibrationResult"]["validation_data_refs"] == []
    assert set(result["processCorrection"]["supported_modes"]) == {
        "RAW",
        "PHYSICS",
        "HYBRID",
    }
    assert result["processCorrection"]["residual_model_ref"] is None
    events = physics_app.events(run_id)
    completed_ops = [event for event in events if event["type"] == "TOOL_COMPLETED"]
    assert any((event["details"] or {}).get("output_refs") for event in completed_ops)


def test_artifact_lineage(physics_app: Topic2ApplicationService) -> None:
    summary = physics_app.create_application_run(mode="research", task_spec=_task(), random_seed=42)
    run_id = summary["application_run_id"]
    artifacts = physics_app.artifacts(run_id)
    by_id = {item["artifact_id"]: item["artifact_type"] for item in artifacts}
    plan_id = next(item_id for item_id, item_type in by_id.items() if item_type == "ToolpathPlan")
    plan = physics_app.artifact(plan_id)["content"]
    for ref in plan["input_refs"]:
        assert ref["id"] in by_id, ref
    simulation_id = next(
        ref["id"] for ref in plan["input_refs"] if ref["type"] == "MorphologySimulationResult"
    )
    simulation = physics_app.artifact(simulation_id)["content"]
    model_id = next(
        ref["id"] for ref in simulation["input_refs"] if ref["type"] == "LocalRemovalModel"
    )
    model = physics_app.artifact(model_id)["content"]
    assert any(ref["type"] == "CalibrationResult" for ref in model["input_refs"])
    assert any(ref["type"] == "PriorObjectSet" for ref in model["input_refs"])


def test_resume_new_stages(physics_app: Topic2ApplicationService) -> None:
    first = physics_app.create_application_run(
        mode="research",
        task_spec=_task(),
        stages=list(Topic2ApplicationService.GAP_STAGES),
        random_seed=42,
    )
    run_id = first["application_run_id"]
    before_events = physics_app.events(run_id)
    before_sequences = [event["sequence"] for event in before_events]
    physics_app.continue_application_run(
        run_id,
        stages=list(Topic2ApplicationService.KNOWLEDGE_STAGES),
        random_seed=42,
    )
    run = physics_app.get_run(run_id)
    assert set(run["stage_status"]) == set(ALL_STAGES)
    after_events = physics_app.events(run_id)
    sequences = [event["sequence"] for event in after_events]
    assert sequences == sorted(set(sequences))
    for stage in Topic2ApplicationService.GAP_STAGES:
        assert (
            sum(
                1
                for event in after_events
                if event["type"] == "STAGE_STARTED" and event["stage"] == stage
            )
            == 1
        )
    assert max(before_sequences) < max(sequences)


def test_observation_contract_and_optional_stage(
    physics_app: Topic2ApplicationService,
) -> None:
    task = _task()
    task["observation"] = {
        "origin": "SYNTHETIC_TEST_FIXTURE",
        "source_ref": "deterministic-closed-loop-fixture",
        "measurements": [
            {
                "name": "mean_depth",
                "value": 2.1,
                "unit": "um",
                "method": "synthetic_fixture",
            }
        ],
        "independent_validation": False,
    }
    summary = physics_app.create_application_run(mode="research", task_spec=task, random_seed=42)
    run = physics_app.get_run(summary["application_run_id"])
    assert run["stage_status"]["evaluate_observation"]["status"] == "completed"
    observation_id = next(
        item["artifact_id"]
        for item in physics_app.artifacts(summary["application_run_id"])
        if item["artifact_type"] == "ObservationResult"
    )
    observation = physics_app.artifact(observation_id)["content"]["content"]
    assert observation["origin"] == "SYNTHETIC_TEST_FIXTURE"
    assert observation["independent_validation"] is False
    assert set(observation["update_triggers"]) == {
        "DATA_STATE",
        "CALIBRATION",
        "PROCESS_MODEL",
        "E2P_TRUST",
    }
