"""Export the golden scenario artifact payloads for frontend fixture testing (M6).

Runs DEMO-P2P-001 end-to-end (gap stages -> seed curated corpus -> knowledge
stages) against a scratch environment and writes every artifact content into
apps/topic2_frontend/src/__fixtures__/goldenRun.json in a stable shape:

    {
      "run": {...},                       # run summary (status/stage_status)
      "artifacts": { "<artifact_type>": { "id", "type", "schema_version", "content" } }
    }

Runtime ids are content-hash-derived and deterministic; run_id is replaced by
a fixed placeholder.  The frontend tests import this file and replay it.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

GOLDEN_TASK = {
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


def main() -> None:
    import os
    from dataclasses import replace

    from apps.topic2_backend.application.service import Topic2ApplicationService
    from apps.topic2_backend.service import Topic2Service
    from apps.topic2_backend.settings import Settings
    from ultrafast_shared.config import loader as _loader

    tmp = Path(tempfile.mkdtemp(prefix="golden-fixture-"))
    memory_root = tmp / "memory"
    memory_root.mkdir()
    os.environ["ULTRAFAST_MEMORY_ROOT"] = str(memory_root)
    _loader._load_revision_cached.cache_clear()

    base = Settings.from_env()
    settings = replace(
        base,
        database_path=tmp / "topic2.db",
        artifact_dir=tmp / "artifacts",
        report_dir=tmp / "reports",
        fixture_path=REPO / "data" / "test_fixture" / "golden_sic_dataset.csv",
        calibration_fixture_path=REPO
        / "data"
        / "test_fixture"
        / "golden_sic_calibration.json",
    )
    service = Topic2Service(settings, approval_verifier=lambda _review_id: False)
    app = Topic2ApplicationService(service, resolution_model="scientific-reading-v1")

    gap = app.create_application_run(
        mode="research",
        task_spec=GOLDEN_TASK,
        stages=list(app.GAP_STAGES),
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

    resumed = app.continue_application_run(
        run_id, stages=list(app.KNOWLEDGE_STAGES), random_seed=42
    )
    assert resumed["status"] == "completed", resumed

    run = app.get_run(run_id)
    artifacts: dict[str, object] = {}
    for meta in app.artifacts(run_id):
        stored = app.artifact(meta["artifact_id"])
        snapshot = stored["content"]
        artifacts[meta["artifact_type"]] = {
            "id": snapshot["id"],
            "type": snapshot["type"],
            "schema_version": snapshot["schema_version"],
            "content": snapshot["content"],
        }

    payload = {
        "run": {
            "application_run_id": "RUN-GOLDEN-FIXTURE",
            "status": run["status"],
            "mode": run["mode"],
            "stage_status": run["stage_status"],
            "task_spec": run.get("task_spec"),
            "result": {
                "runControlState": (run.get("result") or {}).get("runControlState"),
            },
        },
        "artifacts": artifacts,
    }
    out = REPO / "apps" / "topic2_frontend" / "src" / "__fixtures__" / "goldenRun.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out} ({len(artifacts)} artifacts, {out.stat().st_size} bytes)")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
