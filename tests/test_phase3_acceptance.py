"""阶段三最终验收断言 (T5).

A. 前端零 workflow transition logic（源码扫描）。
B. PDF provenance: PDF -> ScientificDocument -> literature 表（pdf_ref 保留），
   Evidence 引用的 paper 必须能回到 literature_paper 行（source 定位）。
C. golden 与 blocked 使用同一 orchestration（同一 ApplicationRun 路径，
   只有输入资源不同——blocked run 也产出任务层 artifacts 并走 RUN_BLOCKED）。
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
        prior_fixture_path=REPO / "data" / "test_fixture" / "golden_sic_priors.json",
    )
    from apps.topic2_backend.service import Topic2Service

    service = Topic2Service(settings, approval_verifier=lambda _review_id: False)
    return Topic2ApplicationService(service, resolution_model="scientific-reading-v1")


# ---------------------------------------------------------------------------
# A. 前端零 workflow transition logic
# ---------------------------------------------------------------------------


def test_frontend_has_no_workflow_transition_logic() -> None:
    frontend_src = REPO / "apps" / "topic2_frontend" / "src"
    forbidden_identifiers = ("CHECKPOINT_STAGES", "nextCheckpoint")
    offenders: list[str] = []
    for path in frontend_src.rglob("*.ts*"):
        if "__fixtures__" in path.parts or path.name.endswith(".test.ts") or path.name.endswith(".test.tsx"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for identifier in forbidden_identifiers:
            if identifier in text:
                offenders.append(f"{path.relative_to(frontend_src)}: {identifier}")
    assert not offenders, (
        "frontend must contain zero workflow transition logic: "
        + "; ".join(offenders)
    )
    # the stages domain still documents phases as pure display keys
    stages = (frontend_src / "domain" / "stages.ts").read_text(encoding="utf-8")
    assert "phase" in stages
    assert "纯显示" in stages or "display" in stages


# ---------------------------------------------------------------------------
# B. PDF provenance: PDF -> ScientificDocument -> literature projection
# ---------------------------------------------------------------------------


def test_pdf_ingestion_preserves_document_provenance(tmp_path, monkeypatch) -> None:
    """PILOT_PDF ingestion keeps pdf_ref/pdf_sha256/document_version per paper."""
    try:
        from demo.t2_slice.resources import resolve_literature_archive

        resolve_literature_archive()
    except RuntimeError as exc:
        pytest.skip(f"literature archive unavailable: {exc}")

    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    monkeypatch.setenv("ULTRAFAST_MEMORY_ROOT", str(memory_root))
    from ultrafast_shared.config import loader as _loader

    _loader._load_revision_cached.cache_clear()

    from apps.topic2_backend.application.literature_fixture import seed_from_pdfs
    from ultrafast_memory.db.session import get_connection

    summary = seed_from_pdfs(paper_ids=["11_arxiv_2404.09906.pdf"])
    assert summary["label"] == "PILOT_PDF"
    assert summary["analysis_method"] == "PENDING_LLM"
    doc_ref = summary["document_refs"][0]
    assert doc_ref["pdf_sha256"]

    with get_connection() as conn:
        paper = conn.execute(
            "SELECT * FROM literature_paper WHERE paper_id=?", (doc_ref["paper_id"],)
        ).fetchone()
    assert paper is not None
    assert paper["source"] == "pilot_pdf"
    assert paper["url"] == doc_ref["pdf_ref"]
    chunk = None
    with get_connection() as conn:
        chunk = conn.execute(
            "SELECT * FROM literature_chunk WHERE paper_id=? LIMIT 1",
            (doc_ref["paper_id"],),
        ).fetchone()
    assert chunk is not None
    metadata = json_loads(chunk["metadata_json"])
    assert metadata["pdf_ref"] == doc_ref["pdf_ref"]
    assert metadata["pdf_sha256"] == doc_ref["pdf_sha256"]
    assert metadata["document_version_id"] == doc_ref["document_version_id"]


def json_loads(payload: str) -> dict:
    import json

    return json.loads(payload)


def test_evidence_paper_traces_to_literature_row(golden_app) -> None:
    """Golden 场景：EvidenceIR 引用的 paper 必须能在 literature_paper 表
    找到 source 定位（curated source 或 pilot_pdf）。"""
    from apps.topic2_backend.application.literature_fixture import seed_golden_corpus

    app = golden_app
    gap = app.create_application_run(
        mode="research",
        task_spec=GOLDEN_TASK,
        stages=list(Topic2ApplicationService.GAP_STAGES),
        random_seed=42,
    )
    assert gap["status"] == "completed", gap
    run_id = gap["application_run_id"]

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
    resumed = app.continue_application_run(
        run_id, stages=list(Topic2ApplicationService.KNOWLEDGE_STAGES), random_seed=42
    )
    assert resumed["status"] == "completed", resumed

    evidence_id = next(
        a["artifact_id"]
        for a in app.artifacts(run_id)
        if a["artifact_type"] == "EvidenceIRSet"
    )
    evidence = app.artifact(evidence_id)["content"]["content"]["items"]
    paper_ids = {
        str(ref["id"])
        for item in evidence
        for ref in item.get("source_refs") or []
        if ref.get("type") == "Paper"
    }
    assert paper_ids
    from ultrafast_memory.db.session import get_connection as memory_connection

    with memory_connection() as _db:
        rows = {
            row["paper_id"]: dict(row)
            for row in _db.execute(
                "SELECT paper_id, source, url FROM literature_paper "
                "WHERE paper_id IN ({})".format(",".join("?" * len(paper_ids))),
                sorted(paper_ids),
            ).fetchall()
        }
    assert set(paper_ids) <= set(rows), "every evidence paper must trace to literature_paper"
    assert all(
        rows[paper_id]["source"] for paper_id in paper_ids
    ), "every traced paper row must carry a source locator"


# ---------------------------------------------------------------------------
# C. golden 与 blocked 同一 orchestration
# ---------------------------------------------------------------------------


def test_golden_and_blocked_share_orchestration(golden_app) -> None:
    """两个 run 走同一 ApplicationRun/RequirementResolutionService 路径：
    golden 全链完成；blocked（RESEARCH 无文献）同样产出任务层 artifacts 并
    停在 Gate B——只有输入资源不同。"""
    app = golden_app

    # blocked run: RESEARCH + 无文献 + 无独立观测
    blocked_task = dict(GOLDEN_TASK)
    blocked_task["execution_mode"] = "RESEARCH"
    blocked = app.create_application_run(
        mode="research", task_spec=blocked_task, random_seed=42
    )
    assert blocked["status"] == "blocked", blocked
    blocked_run = app.get_run(blocked["application_run_id"])
    blocked_kinds = {
        a["artifact_type"] for a in app.artifacts(blocked["application_run_id"])
    }
    # 同一阶段编排（任务层 artifacts 均已产出）
    assert {
        "TaskState",
        "MachineProfileSnapshot",
        "ScientificCapabilityReport",
        "ScientificNeedSet",
        "KnowledgeRequirementSet",
    } <= blocked_kinds
    assert any(
        event["type"] == "RUN_BLOCKED"
        for event in app.events(blocked["application_run_id"])
    )
    assert "calibrate_physics" not in blocked_run["stage_status"]

    # golden run: 同服务全链完成
    gap = app.create_application_run(
        mode="research",
        task_spec=GOLDEN_TASK,
        stages=list(Topic2ApplicationService.GAP_STAGES),
        random_seed=42,
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
    golden = app.continue_application_run(
        run_id, stages=list(Topic2ApplicationService.KNOWLEDGE_STAGES), random_seed=42
    )
    assert golden["status"] == "completed", golden
    golden_kinds = {a["artifact_type"] for a in app.artifacts(run_id)}
    assert {
        "LocalRemovalModel",
        "MorphologySimulationResult",
        "ToolpathPlan",
    } <= golden_kinds
