"""M5: Golden Scientific Vertical Slice E2E (DEMO-P2P-001, SiC / fs / groove).

Fixture setup creates ONLY resources:
  - EquipmentProfile     : DEMO-FS-LASER-01 in the fixture store
  - Literature corpus    : CURATED_LITERATURE_FIXTURE (6 SiC papers) + pre-recorded
                           analysis cache in the shared memory DB
  - Dataset              : golden_sic_dataset.csv (15 SiC rows, DEMO-FS-LASER-01)
  - Calibration fixture  : golden_sic_calibration.json (single/multi-pulse)

The Task carries IDs only - no machine_profile / evidence_ir /
calibration_observations injection.  The system must resolve:

  Task -> Equipment snapshot -> Capability -> Needs -> KnowledgeRequirements
       -> RetrievalQueryPlan -> Corpus -> LLM reading (cache replay)
       -> validation -> EvidenceIR -> applicability -> typed E2P priors
       -> calibration -> LocalRemovalModel -> simulation -> ToolpathPlan

The run is checkpointed after the GAP_STAGES so the literature fixture is
seeded with the requirement-driven retrieval intents (deterministic cache keys).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from apps.topic2_backend.application.service import (
    Topic2ApplicationService,
)

GAP_STAGES = Topic2ApplicationService.GAP_STAGES
KNOWLEDGE_STAGES = Topic2ApplicationService.KNOWLEDGE_STAGES

GOLDEN_TASK: dict = {
    "task_context_id": "DEMO-P2P-001",
    "task_context_version": 1,
    "material": "SiC",
    "laser_type": "fs",
    "process_type": "fs_laser_processing",
    "equipment_profile_id": "DEMO-FS-LASER-01",
    "execution_equipment_ref": "DEMO-FS-LASER-01",
    "geometry_type": "rectangular_groove",
    "objective_metric": "depth_um",
    "execution_mode": "DEMO_FIXTURE",
    "target_geometry": {
        "width_um": 30.0,
        "height_um": 24.0,
        "target_depth_um": 20.0,
        "grid_spacing_um": 2.0,
    },
}

INJECTED_KEYS = ("machine_profile", "evidence_ir", "calibration_observations")


@pytest.fixture()
def golden_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    monkeypatch.setenv("ULTRAFAST_MEMORY_ROOT", str(memory_root))
    from ultrafast_shared.config import loader as _loader

    _loader._load_revision_cached.cache_clear()

    from dataclasses import replace

    from apps.topic2_backend.settings import Settings

    base = Settings.from_env()
    settings = replace(
        base,
        database_path=tmp_path / "topic2.db",
        artifact_dir=tmp_path / "artifacts",
        report_dir=tmp_path / "reports",
        fixture_path=REPO / "data" / "test_fixture" / "golden_sic_dataset.csv",
        calibration_fixture_path=REPO
        / "data"
        / "test_fixture"
        / "golden_sic_calibration.json",
    )
    from apps.topic2_backend.service import Topic2Service

    service = Topic2Service(settings, approval_verifier=lambda _review_id: False)
    app = Topic2ApplicationService(service, resolution_model="scientific-reading-v1")
    return app


def _artifact_payload(app: Topic2ApplicationService, artifact_id: str) -> dict:
    return dict(app.artifact(artifact_id)["content"]["content"])


def _scope_from_task_state(app: Topic2ApplicationService, run_id: str) -> dict:
    artifacts = app.artifacts(run_id)
    task_state_id = next(
        artifact["artifact_id"]
        for artifact in artifacts
        if artifact["artifact_type"] == "TaskState"
    )
    return dict(_artifact_payload(app, task_state_id)["task_scope"])


def _latest_requirements(app: Topic2ApplicationService, run_id: str) -> list[dict]:
    artifacts = app.artifacts(run_id)
    requirement_artifact_id = next(
        artifact["artifact_id"]
        for artifact in artifacts
        if artifact["artifact_type"] == "KnowledgeRequirementSet"
    )
    return list(_artifact_payload(app, requirement_artifact_id)["requirements"])


def test_golden_vertical_slice(golden_app: Topic2ApplicationService) -> None:
    app = golden_app
    # ---- 1. gap stages with IDs-only task (equipment resolution inside) ----
    gap = app.create_application_run(
        mode="research", task_spec=GOLDEN_TASK, stages=list(GAP_STAGES), random_seed=42
    )
    assert gap["status"] == "completed", gap
    run_id = gap["application_run_id"]

    # task spec persisted WITHOUT injected machine/evidence/calibration
    run = app.get_run(run_id)
    assert all(key not in run["task_spec"] for key in INJECTED_KEYS)

    # ---- 2. fixture setup: CURATED literature corpus + recorded analyses ----
    from apps.topic2_backend.application.literature_fixture import seed_golden_corpus

    scope = _scope_from_task_state(app, run_id)
    requirements = _latest_requirements(app, run_id)
    seeded = seed_golden_corpus(task_scope=scope, requirements=requirements)
    assert seeded["papers"] == 6
    assert seeded["seeded_analyses"] >= 4, seeded

    # ---- 3. knowledge + physics stages (system resolves everything) ----
    resumed = app.continue_application_run(
        run_id, stages=list(KNOWLEDGE_STAGES), random_seed=42
    )
    assert resumed["status"] == "completed", resumed

    def artifact_content(artifact_type: str) -> dict:
        artifacts = app.artifacts(run_id)
        artifact_id = next(
            artifact["artifact_id"]
            for artifact in reversed(artifacts)
            if artifact["artifact_type"] == artifact_type
        )
        return _artifact_payload(app, artifact_id)

    # ---- equipment: canonical snapshot, fixture quality ----
    snapshot = artifact_content("MachineProfileSnapshot")
    assert snapshot["resource_status"] == "READY"
    assert snapshot["source_quality"] == "DEMO_FIXTURE"
    assert snapshot["fields"]["actual_power_W"]["value"] == 10.0
    assert snapshot["fields"]["beam_radius_um"]["status"] == "DERIVED"
    assert snapshot["fields"]["wavelength_nm"]["value"] == 1030.0

    # ---- needs: resource needs resolved, knowledge needs classified ----
    need_set = artifact_content("ScientificNeedSet")
    need_types = {need["need_type"] for need in need_set["needs"]}
    assert "SCIENTIFIC_KNOWLEDGE" in need_types
    assert "CALIBRATION_OBSERVATION" in need_types

    # ---- literature chain: five frozen artifacts, Artifact → Service → Artifact ----
    corpus_pack = artifact_content("ScientificCorpusPack")
    assert len(corpus_pack["corpus_pack"]["sources"]) >= 4
    assert corpus_pack["analysis_mapping"]["from_cache"] >= 4

    ledger = artifact_content("CandidateLedger")
    assert ledger["metrics"]["candidates"] >= 8
    assert all(
        candidate["source_type"] == "LLM_DISCOVERY"
        for candidate in ledger["candidates"]
    )

    conditions = artifact_content("SourceConditionSet")
    assert len(conditions["conditions"]) >= 1
    condition_ids = {condition["condition_id"] for condition in conditions["conditions"]}

    reconstructibility = artifact_content("ReconstructibilityReportSet")
    assert len(reconstructibility["reports"]) == len(conditions["conditions"])
    assert all(
        report["condition_id"] in condition_ids
        for report in reconstructibility["reports"]
    )

    applicability = artifact_content("ApplicabilityReportSet")
    assert len(applicability["items"]) >= 6

    evidence_set = artifact_content("EvidenceIRSet")
    evidence_items = evidence_set["items"]
    assert len(evidence_items) >= 6
    evidence_types = {item["claim_type"] for item in evidence_items}
    assert "threshold" in evidence_types  # F_th literature evidence present
    # EvidenceIR -> Condition -> Reconstructibility traceability
    threshold_item = next(
        item for item in evidence_items if item["claim_type"] == "threshold"
    )
    assert threshold_item["ledger_ref"]["type"] == "CandidateLedger"
    assert threshold_item["condition_refs"], (
        "threshold evidence must trace to a compiled condition"
    )
    assert threshold_item["reconstructibility_refs"], (
        "threshold evidence must trace to a reconstructibility report"
    )
    assert all(
        ref["id"] in condition_ids for ref in threshold_item["condition_refs"]
    )

    # ---- typed priors: F_th prior + incubation mechanism + path strategy ----
    prior_set = artifact_content("PriorObjectSet")
    parameter_priors = [
        p for p in prior_set["priors"] if p["prior_type"] == "ParameterPrior"
    ]
    fth = next(p for p in parameter_priors if p["parameter"] == "F_th_eff")
    assert fth["lower"] == pytest.approx(0.65) and fth["upper"] == pytest.approx(0.95)
    mechanism = next(
        p for p in prior_set["priors"] if p["prior_type"] == "MechanismModelPrior"
    )
    assert mechanism["model_family"] == "POWER_LAW_INCUBATION"
    planning = next(
        p
        for p in prior_set["priors"]
        if p["prior_type"] == "PlanningPreferencePrior" and p["path_families"]
    )
    assert planning["path_families"] == ["CROSS_HATCH"]

    # ---- calibration: fitted from fixture observations with prior guidance ----
    calibration = artifact_content("CalibrationResult")
    estimates = {
        item["parameter"]: item["estimate"]
        for item in calibration["parameters"]
        if item["estimate"] is not None
    }
    assert estimates["F_th_eff"] == pytest.approx(0.8, abs=0.1)
    assert estimates["incubation_S"] == pytest.approx(0.78, abs=0.1)
    assert estimates["delta_eff"] == pytest.approx(0.45, abs=0.1)

    # ---- physical model: reconstructed, beam radius from snapshot ----
    model = artifact_content("LocalRemovalModel")
    assert model["mode"] == "RECONSTRUCTED"
    assert model["kernel"]["radius_um"] == pytest.approx(8.0)

    # ---- planning: two path families, recommended plan, full lineage ----
    plan = artifact_content("ToolpathPlan")
    assert plan["status"] == "RECOMMENDED"
    assert {item["path_family"] for item in plan["candidate_summary"]} == {
        "RASTER",
        "CROSS_HATCH",
    }
    simulation = artifact_content("MorphologySimulationResult")
    assert simulation["simulation_id"]
    assert plan["simulation_ref"]["type"] == "MorphologySimulationResult"
    assert plan["simulation_ref"]["id"] == next(
        artifact["artifact_id"]
        for artifact in app.artifacts(run_id)
        if artifact["artifact_type"] == "MorphologySimulationResult"
    )

    # ---- control state: lives in run result (手册 §15), gates not blocked ----
    control = app.get_result(run_id)["runControlState"]
    assert control["phase_status"] in {"COMPLETED", "PARTIAL"}, control
    assert control["execution_mode"] == "DEMO_FIXTURE"
    assert control["provisional"] is False
    assert all(
        control["gates"][name]["status"] in {"READY", "PARTIAL"}
        for name in ("A", "B", "C", "D")
    ), control
    assert not control["blocking_reasons"]

    # ---- provenance: evidence -> paper ----
    evidence_paper_ids = {
        ref["id"]
        for item in evidence_items
        for ref in item.get("source_refs") or []
        if ref.get("type") == "Paper"
    }
    assert evidence_paper_ids  # literature provenance anchors exist


def test_golden_run_fails_closed_without_equipment(golden_app) -> None:
    """RESEARCH mode with an unresolvable equipment id must BLOCK at Gate A."""
    task = dict(GOLDEN_TASK)
    task["execution_mode"] = "RESEARCH"
    task["equipment_profile_id"] = "EQ-NOPE-404"
    task["execution_equipment_ref"] = "EQ-NOPE-404"
    summary = golden_app.create_application_run(
        mode="research", task_spec=task, random_seed=42
    )
    assert summary["status"] == "blocked", summary
    run = golden_app.get_run(summary["application_run_id"])
    control = run["result"]["runControlState"]
    assert control["blocking_reasons"]
