"""阶段二验收矩阵 (T7): gates strictness, mechanism activation, fidelity downgrade.

用例覆盖（用户验收矩阵）:
1. 缺 alpha_defocus + F1 条件齐全 -> F1 runnable / F2 blocked / run 不失败 / planner 用 F1
2. 缺 thermal prior -> THERMAL_MEMORY INACTIVE（不是 thermal_memory_eff=0 calibrated）
3. 只有 ParameterPrior(S) 无 MechanismModelPrior -> Gate B BLOCKED（参数不替代结构）
4. Macro rows 但无 literature/observations -> Gate B BLOCKED（此前最大 bug 的回归）
5. 无 target_geometry -> Gate A BLOCKED
6. blocked 状态一致性（stage_status / blocking_reasons / completed_stages）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from apps.topic2_backend.application.gates import knowledge_gate
from apps.topic2_backend.application.service import (
    Topic2ApplicationService,
)

GAP_STAGES = Topic2ApplicationService.GAP_STAGES
KNOWLEDGE_STAGES = Topic2ApplicationService.KNOWLEDGE_STAGES

MECHANISM_REQUIRED = [
    {
        "parameter": "beam_radius_um",
        "role": "OPTICAL",
        "unit": "um",
        "calibration_supported": False,
        "fallback": "PRIOR",
        "source_model": "GAUSSIAN_BEAM",
    },
    {
        "parameter": "F_th_eff",
        "role": "INTERACTION",
        "unit": "J/cm2",
        "calibration_supported": True,
        "fallback": "PRIOR",
        "source_model": "LOG_ABLATION",
    },
    {
        "parameter": "delta_eff",
        "role": "ABLATION",
        "unit": "um",
        "calibration_supported": True,
        "fallback": "PRIOR",
        "source_model": "LOG_ABLATION",
    },
    {
        "parameter": "incubation_S",
        "role": "INCUBATION",
        "unit": "dimensionless",
        "calibration_supported": True,
        "fallback": "PRIOR",
        "source_model": "POWER_LAW_INCUBATION",
    },
    {
        "parameter": "alpha_defocus",
        "role": "OPTICAL",
        "unit": "1/um",
        "calibration_supported": False,
        "fallback": "PRIOR",
        "source_model": "DEFOCUS_RECURSION",
    },
    {
        "parameter": "thermal_memory_eff",
        "role": "THERMAL",
        "unit": "dimensionless",
        "calibration_supported": False,
        "fallback": "PRIOR",
        "source_model": "THERMAL_MEMORY_PROXY",
    },
]

GOLDEN_TASK: dict = {
    "task_context_id": "DEMO-P2P-001",
    "task_context_version": 1,
    "material": "SiC",
    "laser_type": "fs",
    "process_type": "fs_laser_processing",
    "equipment_profile_id": "DEMO-FS-LASER-01",
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


@pytest.fixture()
def strict_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Golden environment WITHOUT the DEMO_FIXTURE prior fixture:
    alpha_defocus / thermal_memory_eff stay unsupported."""
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
        prior_fixture_path=tmp_path / "no_prior_fixture.json",
    )
    from apps.topic2_backend.service import Topic2Service

    service = Topic2Service(settings, approval_verifier=lambda _review_id: False)
    return Topic2ApplicationService(service, resolution_model="scientific-reading-v1")


def _run_golden(strict_app: Topic2ApplicationService, task: dict):
    app = strict_app
    gap = app.create_application_run(
        mode="research", task_spec=task, stages=list(GAP_STAGES), random_seed=42
    )
    assert gap["status"] == "completed", gap
    run_id = gap["application_run_id"]

    from apps.topic2_backend.application.literature_fixture import seed_golden_corpus

    task_state_id = next(
        a["artifact_id"]
        for a in app.artifacts(run_id)
        if a["artifact_type"] == "TaskState"
    )
    scope = dict(app.artifact(task_state_id)["content"]["content"]["task_scope"])
    req_id = next(
        a["artifact_id"]
        for a in app.artifacts(run_id)
        if a["artifact_type"] == "KnowledgeRequirementSet"
    )
    requirements = list(app.artifact(req_id)["content"]["content"]["requirements"])
    seed_golden_corpus(task_scope=scope, requirements=requirements)
    return app, run_id


def _artifact_payload(app: Topic2ApplicationService, run_id: str, artifact_type: str) -> dict:
    artifact_id = next(
        artifact["artifact_id"]
        for artifact in app.artifacts(run_id)
        if artifact["artifact_type"] == artifact_type
    )
    return dict(app.artifact(artifact_id)["content"]["content"])


# ---------------------------------------------------------------------------
# 用例 3: 只有 ParameterPrior(S)，没有 MechanismModelPrior -> 结构未解决
# ---------------------------------------------------------------------------


def test_gate_b_incubation_structure_required() -> None:
    gate = knowledge_gate(
        parameter_priors={"incubation_S", "F_th_eff", "delta_eff"},
        mechanism_model_priors=set(),
        observation_capabilities=set(),
        mechanism_required=MECHANISM_REQUIRED,
        machine_fields={"beam_radius_um"},
        execution_mode="DEMO_FIXTURE",
    )
    assert gate.status == "BLOCKED"
    assert any("POWER_LAW_INCUBATION" in reason for reason in gate.reasons)


def test_gate_b_structure_and_parameter_both_required() -> None:
    # structure 解决了但参数没有 -> 仍然 BLOCKED
    gate = knowledge_gate(
        parameter_priors={"F_th_eff", "delta_eff"},
        mechanism_model_priors={"POWER_LAW_INCUBATION"},
        observation_capabilities=set(),
        mechanism_required=MECHANISM_REQUIRED,
        machine_fields={"beam_radius_um"},
        execution_mode="DEMO_FIXTURE",
    )
    assert gate.status == "BLOCKED"
    assert any("incubation_S" in reason for reason in gate.reasons)


def test_gate_b_macro_rows_do_not_count() -> None:
    # observation_capabilities 空 = 只有宏数据集 -> 参数全部 unresolved
    gate = knowledge_gate(
        parameter_priors=set(),
        mechanism_model_priors=set(),
        observation_capabilities=set(),
        mechanism_required=MECHANISM_REQUIRED,
        machine_fields={"beam_radius_um"},
        execution_mode="DEMO_FIXTURE",
    )
    assert gate.status == "BLOCKED"
    assert any("F_th_eff" in reason for reason in gate.reasons)


def test_gate_b_optional_mechanisms_partial_not_blocked() -> None:
    # 必需参数齐备 + structure 解决 -> READY（可选机制缺失只是 PARTIAL）
    gate = knowledge_gate(
        parameter_priors={"F_th_eff", "incubation_S", "delta_eff"},
        mechanism_model_priors={"POWER_LAW_INCUBATION"},
        observation_capabilities={"F_th_eff", "incubation_S", "delta_eff"},
        mechanism_required=MECHANISM_REQUIRED,
        machine_fields={"beam_radius_um"},
        execution_mode="DEMO_FIXTURE",
    )
    assert gate.status == "READY"


# ---------------------------------------------------------------------------
# 用例 1+2: fidelity downgrade + thermal inactive（服务级，无 fixture prior）
# ---------------------------------------------------------------------------


def test_fidelity_downgrade_and_thermal_inactive(strict_app) -> None:
    app, run_id = _run_golden(strict_app, GOLDEN_TASK)
    resumed = app.continue_application_run(
        run_id, stages=list(KNOWLEDGE_STAGES), random_seed=42
    )
    assert resumed["status"] == "completed", resumed

    model = _artifact_payload(app, run_id, "LocalRemovalModel")
    inactive = {item["mechanism"] for item in model["inactive_mechanisms"]}
    assert "DEFOCUS_RECURSION" in inactive, "no alpha prior -> F2 must be inactive"
    assert "THERMAL_MEMORY" in inactive, "no thermal prior -> mechanism inactive"

    bindings = {b["parameter"]: b for b in model["parameter_bindings"]}
    assert "thermal_memory_eff" not in bindings, (
        "INACTIVE mechanism must not expose a default value"
    )
    assert "alpha_defocus" not in bindings
    assert bindings["F_th_eff"]["source_type"] in {
        "LITERATURE_PRIOR",
        "TARGET_CALIBRATION",
    }
    assert bindings["delta_eff"]["source_type"] == "TARGET_CALIBRATION"

    # planner 自动降级到 F1，run 不整体失败
    simulation = _artifact_payload(app, run_id, "MorphologySimulationResult")
    assert simulation["fidelity"] == "F1_INCUBATION"
    plan = _artifact_payload(app, run_id, "ToolpathPlan")
    assert plan["status"] == "DEMO_CANDIDATE"


def test_fidelity_f2_available_with_fixture_alpha_prior(tmp_path, monkeypatch) -> None:
    """golden 环境含 DEMO_FIXTURE alpha prior -> F2 runnable（对照用例 1）。"""
    from dataclasses import replace

    from apps.topic2_backend.application.service import Topic2ApplicationService
    from apps.topic2_backend.service import Topic2Service
    from apps.topic2_backend.settings import Settings

    KNOW = Topic2ApplicationService.KNOWLEDGE_STAGES

    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    monkeypatch.setenv("ULTRAFAST_MEMORY_ROOT", str(memory_root))
    from ultrafast_shared.config import loader as _loader

    _loader._load_revision_cached.cache_clear()
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
        prior_fixture_path=REPO / "data" / "test_fixture" / "golden_sic_priors.json",
    )
    service = Topic2Service(settings, approval_verifier=lambda _review_id: False)
    app = Topic2ApplicationService(service, resolution_model="scientific-reading-v1")

    _, run_id = _run_golden(app, GOLDEN_TASK)
    resumed = app.continue_application_run(run_id, stages=list(KNOW), random_seed=42)
    assert resumed["status"] == "completed", resumed
    model = _artifact_payload(app, run_id, "LocalRemovalModel")
    inactive = {item["mechanism"] for item in model["inactive_mechanisms"]}
    assert "DEFOCUS_RECURSION" not in inactive
    assert "THERMAL_MEMORY" in inactive  # 热机制仍然诚实 inactive
    bindings = {b["parameter"]: b for b in model["parameter_bindings"]}
    assert bindings["alpha_defocus"]["source_type"] == "DEMO_FIXTURE"
    simulation = _artifact_payload(app, run_id, "MorphologySimulationResult")
    assert simulation["fidelity"] == "F2_DEFOCUS_RECURSION"


# ---------------------------------------------------------------------------
# 用例 5: 无 target_geometry -> Gate A BLOCKED
# ---------------------------------------------------------------------------


def test_gate_a_requires_target_geometry(strict_app) -> None:
    task = dict(GOLDEN_TASK)
    task.pop("target_geometry")
    summary = strict_app.create_application_run(
        mode="research", task_spec=task, random_seed=42
    )
    assert summary["status"] == "blocked", summary
    run = strict_app.get_run(summary["application_run_id"])
    control = run["result"]["runControlState"]
    assert control["gates"]["A"]["status"] == "BLOCKED"
    assert any(
        action["type"] == "SPECIFY_TARGET_GEOMETRY"
        for action in control["next_actions"]
    )
    assert "target_depth_um" in control["blocking_reasons"][-1]


# ---------------------------------------------------------------------------
# 用例 6: blocked 状态一致性（SANDBOX 不受影响）
# ---------------------------------------------------------------------------


def test_sandbox_keeps_computational_defaults_but_marks_provisional(strict_app) -> None:
    task = dict(GOLDEN_TASK)
    task["execution_mode"] = "SANDBOX"
    task.pop("target_geometry")  # SANDBOX 允许 synthetic target
    summary = strict_app.create_application_run(
        mode="research", task_spec=task, random_seed=42
    )
    assert summary["status"] == "completed", summary
    run = strict_app.get_run(summary["application_run_id"])
    control = run["result"]["runControlState"]
    assert control["provisional"] is True
    assert control["gates"]["A"]["status"] == "READY"
    plan = run["result"]["physicsToPlanning"]["toolpathPlan"]
    assert plan["status"] == "PROVISIONAL_SIMULATION_ONLY"
