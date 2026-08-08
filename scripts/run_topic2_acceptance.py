"""Run the independent Physics-to-Planning V1 backend acceptance (B0-B9).

The runner uses the real FastAPI POST ApplicationRun boundary, an isolated
database, deterministic synthetic *test* observations, and persisted artifact
lineage.  It never labels fixtures as experimental validation.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.topic2_backend.api.app import create_app
from apps.topic2_backend.application.service import ALL_STAGES
from apps.topic2_backend.settings import Settings
from packages.scientific_computation.contracts import (
    EvidenceOrigin,
    ParameterObservation,
)
from packages.scientific_computation.identification import (
    cumulative_ablation_depth,
)

REQUIRED_ARTIFACTS = (
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
)


def _observations() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fluence in (1.2, 1.8, 2.5, 3.2):
        for pulse_count in (1, 3, 7):
            rows.append(
                ParameterObservation(
                    peak_fluence_J_cm2=fluence,
                    pulse_count=pulse_count,
                    depth_um=cumulative_ablation_depth(fluence, pulse_count, 0.8, 0.78, 0.45),
                    data_ref=f"SYNTHETIC-ACCEPTANCE-{fluence}-{pulse_count}",
                    origin=EvidenceOrigin.SYNTHETIC_TEST_FIXTURE,
                ).model_dump(mode="json")
            )
    return rows


def _task() -> dict[str, Any]:
    return {
        "task_context_id": "P2P-V1-BACKEND-ACCEPTANCE",
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
                "evidence_id": "E-ACCEPTANCE-FTH",
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
                "evidence_id": "E-ACCEPTANCE-MECHANISM",
                "claim_type": "mechanism_model",
                "claim": {"model_family": "POWER_LAW_INCUBATION"},
                "review_status": "approved",
                "applicability_status": "PARTIAL",
            },
            {
                "evidence_id": "E-ACCEPTANCE-PATH",
                "claim_type": "path_strategy",
                "claim": {
                    "path_families": ["CROSS_HATCH"],
                    "preference": "soft path-family candidate",
                },
                "review_status": "approved",
                "applicability_status": "UNKNOWN",
            },
        ],
        "calibration_observations": _observations(),
    }


def _gate(condition: bool, evidence: Any) -> dict[str, Any]:
    return {"status": "PASS" if condition else "FAIL", "evidence": evidence}


def run_acceptance(output_path: Path | None = None) -> dict[str, Any]:
    output_path = output_path or ROOT / "outputs" / "physics_to_planning_v1_backend_acceptance.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p2p-v1-acceptance-") as temp_name:
        temp = Path(temp_name)
        settings = replace(
            Settings.from_env(),
            database_path=temp / "acceptance.db",
            artifact_dir=temp / "artifacts",
            report_dir=temp / "reports",
            fixture_path=ROOT / "data" / "test_fixture" / "topic2_experiments_v1.csv",
        )
        app = create_app(settings)
        client = TestClient(app)
        health = client.get("/api/v1/health")
        request = {
            "mode": "research",
            "task_spec": _task(),
            "random_seed": 42,
            "client_request_id": "p2p-v1-backend-acceptance",
        }
        created = client.post("/api/v1/application-runs", json=request)
        created.raise_for_status()
        summary = created.json()
        idempotent = client.post("/api/v1/application-runs", json=request)
        idempotent.raise_for_status()
        run_id = summary["application_run_id"]
        run_response = client.get(f"/api/v1/application-runs/{run_id}")
        run_response.raise_for_status()
        run = run_response.json()
        artifact_list_response = client.get(f"/api/v1/application-runs/{run_id}/artifacts")
        artifact_list_response.raise_for_status()
        artifact_items = artifact_list_response.json()["items"]
        by_type = {item["artifact_type"]: item["artifact_id"] for item in artifact_items}
        service = app.state.application_service
        snapshots = {
            artifact_type: service.artifact(artifact_id)["content"]
            for artifact_type, artifact_id in by_type.items()
        }

        capability = snapshots["ScientificCapabilityReport"]["content"]
        query_plan = snapshots["LiteratureRetrievalQueryPlan"]["content"]
        priors = snapshots["PriorObjectSet"]["content"]
        identifiability = snapshots["IdentifiabilityReport"]["content"]
        calibration = snapshots["CalibrationResult"]["content"]
        local_model = snapshots["LocalRemovalModel"]["content"]
        simulation = snapshots["MorphologySimulationResult"]["content"]
        plan = snapshots["ToolpathPlan"]["content"]
        artifact_ids = set(by_type.values())
        all_required_refs_exist = True
        for artifact_type in REQUIRED_ARTIFACTS:
            snapshot = snapshots.get(artifact_type) or {}
            for ref in snapshot.get("input_refs") or []:
                if ref.get("id") not in artifact_ids and ref.get("type") not in {
                    "TaskScope",
                    "Observation",
                }:
                    all_required_refs_exist = False
        calibration_by_name = {item["parameter"]: item for item in calibration["parameters"]}

        gates = {
            "B0_regression_contract": _gate(
                health.status_code == 200
                and summary["status"] == "completed"
                and set(run["stage_status"]) == set(ALL_STAGES)
                and idempotent.json()["application_run_id"] == run_id,
                {
                    "health": health.json(),
                    "stages": sorted(run["stage_status"]),
                    "idempotent_run_id": idempotent.json()["application_run_id"],
                },
            ),
            "B1_typed_contracts": _gate(
                set(REQUIRED_ARTIFACTS).issubset(by_type)
                and all(snapshots[item]["schema_version"] for item in REQUIRED_ARTIFACTS),
                {"required_artifacts": list(REQUIRED_ARTIFACTS), "actual": sorted(by_type)},
            ),
            "B2_capability_preflight": _gate(
                capability["simulation_supported"]
                and capability["available"]
                and capability["identifiability"]
                and capability["recommended_requirements"],
                {
                    "capability_id": capability["capability_id"],
                    "requirements": len(capability["recommended_requirements"]),
                },
            ),
            "B3_requirement_retrieval": _gate(
                query_plan["geometry_policy"] == "SOFT_RANKING_HINT_ONLY"
                and all(
                    plan_item["geometry_is_hard_filter"] is False
                    for plan_item in query_plan["plans"]
                ),
                {"query_plan_ref": by_type["LiteratureRetrievalQueryPlan"]},
            ),
            "B4_e2p_boundary": _gate(
                {item["prior_type"] for item in priors["priors"]}
                >= {"ParameterPrior", "MechanismModelPrior", "PlanningPreferencePrior"}
                and "probability" not in json.dumps(priors, ensure_ascii=False).lower(),
                {"prior_types": sorted({item["prior_type"] for item in priors["priors"]})},
            ),
            "B5_parameter_identification": _gate(
                calibration_by_name["F_th_eff"]["estimate"] is not None
                and calibration_by_name["F_th_eff"]["prior_refs"]
                and calibration_by_name["thermal_diffusivity"]["identifiability"]
                == "NOT_IDENTIFIABLE"
                and calibration_by_name["thermal_diffusivity"]["estimate"] is None
                and not calibration["validation_data_refs"],
                {
                    "identifiability_report": identifiability["report_id"],
                    "fit_metrics": calibration["fit_metrics"],
                },
            ),
            "B6_stateful_simulator": _gate(
                simulation["fidelity"] == "F2_DEFOCUS_RECURSION"
                and simulation["pulse_count"] > 0
                and simulation["state"]["height_field_um"],
                {"simulation_id": simulation["simulation_id"], "metrics": simulation["metrics"]},
            ),
            "B7_removal_initialization": _gate(
                local_model["mode"] == "RECONSTRUCTED"
                and local_model["parameter_semantics"]
                and local_model["input_refs"],
                {"model_id": local_model["model_id"], "mode": local_model["mode"]},
            ),
            "B8_toolpath_planning": _gate(
                plan["path_family"] in {"RASTER", "CROSS_HATCH"}
                and plan["status"] == "RECOMMENDED"
                and plan["simulation_ref"]["id"] == by_type["MorphologySimulationResult"]
                and len(plan["candidate_summary"]) >= 2,
                {"plan_id": plan["plan_id"], "path_family": plan["path_family"]},
            ),
            "B9_full_backend_e2e": _gate(
                all_required_refs_exist and plan["simulation_ref"]["id"] in artifact_ids,
                {
                    "application_run_id": run_id,
                    "lineage": run["result"]["audit"]["artifactLineage"],
                    "all_required_refs_exist": all_required_refs_exist,
                },
            ),
        }
        report = {
            "acceptance": "Physics-to-Planning V1 independent backend",
            "schema_version": "backend-acceptance-v1",
            "application_run_id": run_id,
            "overall_status": (
                "PASS" if all(item["status"] == "PASS" for item in gates.values()) else "FAIL"
            ),
            "gates": gates,
            "scientific_disclosures": [
                "synthetic calibration observations are SYNTHETIC_TEST_FIXTURE, not experimental validation",
                "uncalibrated CFA remains NOT_YET_CALIBRATED",
                "terminal depth alone does not identify physical thermal diffusivity",
            ],
        }
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if report["overall_status"] != "PASS":
            failed = [name for name, item in gates.items() if item["status"] != "PASS"]
            raise RuntimeError(f"backend acceptance failed: {failed}")
        return report


def main() -> None:
    report = run_acceptance()
    print(
        json.dumps(
            {
                "overall_status": report["overall_status"],
                "gates": {key: value["status"] for key, value in report["gates"].items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
