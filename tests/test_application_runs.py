"""Application Orchestrator tests (BE-1..BE-5): research runs, idempotency,
events, artifacts, vanilla/assisted comparison and demo replay contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from apps.topic2_backend.application.service import (  # noqa: E402
    ALL_STAGES,
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
    assert "TargetPhysicsReadiness" in kinds
    assert "KnowledgeRequirements" in kinds
    assert "KnowledgeState" in kinds
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


def test_knowledge_state_unresolved_without_literature(app_service) -> None:
    """V0 main chain: no literature -> requirements generated from real
    diagnostics, all UNSATISFIED, run still completes with Vanilla BO."""
    summary = app_service.create_application_run(
        mode="research", task_spec=TASK_SPEC, random_seed=42
    )
    result = app_service.get_result(summary["application_run_id"])
    ks = result["knowledgeState"]
    assert ks["requirements"], "gap analysis must produce requirements"
    assert ks["assessment_version"]
    satisfactions = ks["satisfactions"]
    assert len(satisfactions) == len(ks["requirements"])
    for satisfaction in satisfactions:
        assert satisfaction["assessment_method"] == "DETERMINISTIC_PROVISIONAL"
        assert satisfaction["status"] in {
            "SATISFIED",
            "PARTIALLY_SATISFIED",
            "SATISFIED_WITH_CONFLICT",
            "UNSATISFIED",
        }
        assert satisfaction["requirement_id"]
    assert ks["missing_topics"], "no literature => requirements unresolved"
    # run completes with vanilla BO even with unresolved knowledge
    assert result["optimization"]["vanilla"]["run_id"]
    assert result["optimization"]["priorAppliedEvidence"]["assisted_search_prior_applied"] is False


def test_gap_requirements_carry_diagnostics_triggers(app_service) -> None:
    summary = app_service.create_application_run(
        mode="research", task_spec=TASK_SPEC, random_seed=42
    )
    result = app_service.get_result(summary["application_run_id"])
    requirements = result["knowledgeState"]["requirements"]
    types = {requirement["type"] for requirement in requirements}
    assert "parameter_effect" in types
    assert "reported_optimum" in types
    for requirement in requirements:
        assert requirement["trigger_reasons"], "trigger_reasons must reference diagnostics"
        assert requirement["priority"] in {"high", "medium", "low"}


def test_checkpoint_resume_gap_then_knowledge(app_service) -> None:
    """两段式入口：运行到知识缺口（1-4）→ 检查 Requirement → 续跑知识准备（5-8）。
    同一 run，已完成阶段不重复执行。"""
    summary = app_service.create_application_run(
        mode="research",
        task_spec=TASK_SPEC,
        stages=list(Topic2ApplicationService.GAP_STAGES),
        random_seed=42,
    )
    assert summary["status"] == "completed"
    run = app_service.get_run(summary["application_run_id"])
    assert set(run["stage_status"]) == set(Topic2ApplicationService.GAP_STAGES)
    assert run["task_spec"] is not None
    partial = run["result"]
    assert partial["knowledgeState"]["requirements"], "gap run must expose requirements"
    assert partial["optimization"]["vanilla"] is None  # BO 尚未执行

    # 续跑剩余阶段（同一 run_id）
    resumed = app_service.continue_application_run(
        summary["application_run_id"],
        stages=list(Topic2ApplicationService.KNOWLEDGE_STAGES),
        random_seed=42,
    )
    assert resumed["application_run_id"] == summary["application_run_id"]
    assert resumed["status"] == "completed"
    full = app_service.get_run(summary["application_run_id"])
    assert set(full["stage_status"]) == set(ALL_STAGES)
    assert full["result"]["optimization"]["vanilla"]["run_id"]
    # 事件序号单调递增（续跑不冲突）
    events = app_service.events(summary["application_run_id"])
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)


def test_continue_refuses_repeat_stage(app_service) -> None:
    summary = app_service.create_application_run(
        mode="research",
        task_spec=TASK_SPEC,
        stages=list(Topic2ApplicationService.GAP_STAGES),
        random_seed=42,
    )
    with pytest.raises(ValueError, match="already executed"):
        app_service.continue_application_run(
            summary["application_run_id"],
            stages=["baseline_learning"],
        )


def test_requirement_specific_coverage(app_service) -> None:
    """一条 range_preference evidence 只能满足 range 类需求，不能误满足
    process_mechanism（functional_shape）需求；data_quality 恒不被文献满足。"""
    from packages.process_contracts.schemas import Evidence, EvidenceClaimType, EvidenceProvenance, EvidenceScope

    evidence = Evidence(
        evidence_id="E-COV-001",
        source_type="literature",
        claim_type=EvidenceClaimType.RANGE_PREFERENCE,
        parameter="frequency_kHz",
        target="depth_um",
        claim={"lower": 50.0, "upper": 200.0, "strength": "medium"},
        scope=EvidenceScope(material="SiC", laser_type="fs"),
        provenance=EvidenceProvenance(source_id="paper-x", review_id="review-1"),
        review_status="approved",
        version="1",
    )
    with app_service.repository.connection() as db:
        db.execute(
            "INSERT OR REPLACE INTO evidence(evidence_id,evidence_version,payload_json,review_status) VALUES(?,?,?,?)",
            (evidence.evidence_id, "1", json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False), "approved"),
        )

    summary = app_service.create_application_run(
        mode="research", task_spec=TASK_SPEC, random_seed=42
    )
    result = app_service.get_result(summary["application_run_id"])
    satisfactions = {
        s["requirement_id"]: s for s in result["knowledgeState"]["satisfactions"]
    }
    by_type = {}
    for req in result["knowledgeState"]["requirements"]:
        by_type[req["requirement_id"]] = req["type"]
    # range 类需求（parameter_effect / reported_optimum）应被部分满足
    for req_id, req_type in by_type.items():
        if req_type in ("parameter_effect", "reported_optimum"):
            assert satisfactions[req_id]["status"] in ("SATISFIED", "PARTIALLY_SATISFIED"), req_id
            assert "E-COV-001" in satisfactions[req_id]["basis_refs"], req_id
        if req_type in ("process_mechanism", "formula"):
            assert satisfactions[req_id]["status"] == "UNSATISFIED", req_id
        if req_type == "data_quality":
            assert satisfactions[req_id]["status"] == "UNSATISFIED", req_id
