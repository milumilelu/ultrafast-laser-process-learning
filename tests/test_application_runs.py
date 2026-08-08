"""Application Orchestrator tests (BE-1..BE-5): research runs, idempotency,
events, artifacts, vanilla/assisted comparison and demo replay contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from apps.topic2_backend.application.service import (  # noqa: E402
    DEMO_SCENARIO_01,
    Topic2ApplicationService,
)
from apps.topic2_backend.service import Topic2Service  # noqa: E402

TASK_SPEC = {
    "task_context_id": "T2-TEST-001",
    "task_context_version": 3,
    "material": "SiC",
    "laser_type": "fs",
    "equipment_profile_id": "EQ-TEST-FS",
    "geometry_type": "rectangular_groove",
    "objective_metric": "depth_um",
    "random_seed": 42,
}


@pytest.fixture()
def app_service(tmp_path: Path) -> Topic2ApplicationService:
    from dataclasses import replace

    from apps.topic2_backend.settings import Settings

    base = Settings.from_env()
    service = Topic2Service(
        replace(
            base,
            database_path=tmp_path / "topic2.db",
            artifact_dir=tmp_path / "artifacts",
            report_dir=tmp_path / "reports",
            fixture_path=REPO / "data" / "test_fixture" / "topic2_experiments_v1.csv",
        ),
        approval_verifier=lambda _review_id: False,
    )
    return Topic2ApplicationService(service)


def test_research_run_completes_all_stages(app_service) -> None:
    summary = app_service.create_application_run(
        mode="research", task_spec=TASK_SPEC, random_seed=42
    )
    assert summary["status"] == "completed"
    assert summary["mode"] == "research"
    run = app_service.get_run(summary["application_run_id"])
    result = run["result"]
    assert result["runId"] == summary["application_run_id"]
    assert result["workflowVersion"]
    assert result["targetTask"]["material"] == "SiC"
    assert result["processLearning"]["selectedModel"]
    assert isinstance(result["optimization"]["vanilla"], dict)
    assert isinstance(result["optimization"]["evidenceAssisted"], dict)
    prior = result["optimization"]["priorAppliedEvidence"]
    assert prior["vanilla_search_prior_applied"] is False
    assert prior["assisted_search_prior_applied"] is False
    assert result["cfa"]["calibrationStatus"] == "NOT_YET_CALIBRATED"
    assert result["audit"]["replayable"] is False


def test_research_run_events_and_artifacts(app_service) -> None:
    summary = app_service.create_application_run(
        mode="research", task_spec=TASK_SPEC, random_seed=42
    )
    run_id = summary["application_run_id"]
    events = app_service.events(run_id)
    types = [event["type"] for event in events]
    assert "RUN_STARTED" in types
    assert "RUN_COMPLETED" in types
    assert "STAGE_STARTED" in types
    assert "STAGE_COMPLETED" in types
    assert "ARTIFACT_CREATED" in types
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences)
    assert sequences[0] == 1
    artifacts = app_service.artifacts(run_id)
    kinds = {item["artifact_type"] for item in artifacts}
    assert "ProcessLearningResult" in kinds
    assert "ModelTrainingResult" in kinds
    assert "CFAReport" in kinds
    stored = app_service.artifact(artifacts[0]["artifact_id"])
    assert "content" in stored
    assert stored["application_run_id"] == run_id


def test_client_request_id_idempotency(app_service) -> None:
    first = app_service.create_application_run(
        mode="research",
        task_spec=TASK_SPEC,
        random_seed=42,
        client_request_id="req-001",
    )
    second = app_service.create_application_run(
        mode="research",
        task_spec=TASK_SPEC,
        random_seed=42,
        client_request_id="req-001",
    )
    assert first["application_run_id"] == second["application_run_id"]


def test_compare_optimization_vanilla_without_prior(app_service) -> None:
    summary = app_service.create_application_run(
        mode="research", task_spec=TASK_SPEC, random_seed=42
    )
    comparison = app_service.compare_optimization(
        scope=TASK_SPEC,
        machine_bounds={
            "pulse_width_ps": {"lower": 0.2, "upper": 8.0},
            "frequency_kHz": {"lower": 20.0, "upper": 2000.0},
            "hatch_spacing_um": {"lower": 20.0, "upper": 300.0},
            "passes": {"lower": 1.0, "upper": 8.0},
            "scan_speed_mm_s": {"lower": 20.0, "upper": 400.0},
        },
        random_seed=42,
    )
    assert comparison["vanilla"]["run_id"]
    assert comparison["evidence_assisted"]["run_id"]
    assert comparison["prior_applied_evidence"]["vanilla_search_prior_applied"] is False
    assert comparison["prior_applied_evidence"]["assisted_search_prior_applied"] is False
    assert comparison["vanilla"]["recommended_parameters"]


def test_machine_bounds_from_data_cover_core_parameters(app_service) -> None:
    scope = app_service._scope(TASK_SPEC)
    rows = app_service.topic2._rows_for_scope(scope)
    bounds = app_service._machine_bounds(scope, rows)
    assert set(bounds) == {
        "pulse_width_ps",
        "frequency_kHz",
        "hatch_spacing_um",
        "passes",
        "scan_speed_mm_s",
    }
    for name, value in bounds.items():
        assert value["lower"] < value["upper"], name


def test_missing_stage_rejected(app_service) -> None:
    with pytest.raises(ValueError):
        app_service.create_application_run(
            mode="research", task_spec=TASK_SPEC, stages=["nonsense"]
        )


def test_demo_slice_runs_offline(app_service) -> None:
    summary = app_service.create_application_run(mode="demo", random_seed=42)
    assert summary["status"] == "completed"
    result = app_service.get_result(summary["application_run_id"])
    assert result["targetTask"]["material"] == "SiC"
    assert result["targetTask"]["target"] == "depth_um"
    assert result["optimization"]["priorAppliedEvidence"]["vanilla_search_prior_applied"] is False
    assert result["cfa"]["calibrationStatus"] == "NOT_YET_CALIBRATED"
    assert result["audit"]["replayable"] is True
    assert result["scientificBasis"]["paperCount"] >= 1


def test_demo_replay_scientific_payload_identical(app_service) -> None:
    summary = app_service.create_application_run(mode="demo", random_seed=42)
    replay = app_service.replay(summary["application_run_id"])
    assert replay["scientific_payload_identical"] is True
    assert replay["runtime_ids_changed"] is True
    assert replay["replay_run_id"] != summary["application_run_id"]


def test_replay_rejected_for_research(app_service) -> None:
    summary = app_service.create_application_run(
        mode="research", task_spec=TASK_SPEC, random_seed=42
    )
    with pytest.raises(ValueError):
        app_service.replay(summary["application_run_id"])


def test_ndjson_events_after_sequence(app_service) -> None:
    summary = app_service.create_application_run(
        mode="research", task_spec=TASK_SPEC, random_seed=42
    )
    all_events = app_service.events(summary["application_run_id"])
    tail = app_service.events(summary["application_run_id"], after_sequence=3)
    assert len(all_events) > 3
    assert tail[0]["sequence"] > 3
    assert [e["sequence"] for e in tail] == sorted(e["sequence"] for e in tail)
