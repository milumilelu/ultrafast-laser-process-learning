"""Start the topic2 backend for the frontend HTTP e2e (M6).

Prepares the golden scenario environment in one scratch directory:
  1. fresh memory DB + CURATED literature corpus (seeded with the golden
     task's real requirement-driven intents, pre-recorded analysis cache)
  2. topic2 DB seeded with the golden dataset + equipment fixture store
  3. runs the gap stages in-process to compute the exact requirement set
  4. serves the real backend (uvicorn, in-process) on the requested port

The vitest e2e (apps/topic2_frontend/src/tests/frontend_backend.e2e.test.ts)
spawns this process, waits for READY, drives the real frontend API client,
and terminates the process afterwards.

Usage:
  python scripts/run_frontend_e2e_backend.py --port 8123
"""

from __future__ import annotations

import argparse
import os
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


def prepare_fixtures(root: Path) -> dict[str, str]:
    """Return the env overrides the backend process needs."""
    from dataclasses import replace

    from apps.topic2_backend.application.service import Topic2ApplicationService
    from apps.topic2_backend.service import Topic2Service
    from apps.topic2_backend.settings import Settings
    from ultrafast_shared.config import loader as _loader

    memory_root = root / "memory"
    memory_root.mkdir(parents=True, exist_ok=True)
    os.environ["ULTRAFAST_MEMORY_ROOT"] = str(memory_root)
    _loader._load_revision_cached.cache_clear()

    base = Settings.from_env()
    settings = replace(
        base,
        database_path=root / "topic2.db",
        artifact_dir=root / "artifacts",
        report_dir=root / "reports",
        fixture_path=REPO / "data" / "test_fixture" / "golden_sic_dataset.csv",
        calibration_fixture_path=REPO
        / "data"
        / "test_fixture"
        / "golden_sic_calibration.json",
    )
    service = Topic2Service(settings, approval_verifier=lambda _review_id: False)
    app = Topic2ApplicationService(service, resolution_model="scientific-reading-v1")

    from apps.topic2_backend.application.literature_fixture import seed_golden_corpus

    def prep_and_seed(task_spec: dict, client_request_id: str) -> dict:
        gap = app.create_application_run(
            mode="research",
            task_spec=task_spec,
            stages=list(app.GAP_STAGES),
            random_seed=42,
            client_request_id=client_request_id,
        )
        if gap["status"] != "completed":
            raise RuntimeError(f"fixture prep gap run failed: {gap}")
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
        return seed_golden_corpus(task_scope=scope, requirements=requirements)

    # 1. golden scenario scope (used by the backend e2e)
    prep_and_seed(GOLDEN_TASK, "e2e-fixture-prep")
    # 2. UI-equivalent scope: the workbench draft sends no task_context_id /
    #    task_context_version / target_geometry, which changes the cache key
    ui_task = {key: value for key, value in GOLDEN_TASK.items() if key not in (
        "task_context_id",
        "task_context_version",
        "execution_equipment_ref",
        "target_geometry",
    )}
    seeded = prep_and_seed(ui_task, "e2e-fixture-prep-ui")
    print(
        f"fixture ready: {seeded['papers']} papers, "
        f"{seeded['seeded_analyses']} cached analyses (golden + UI scopes)"
    )

    return {
        "TOPIC2_DB_PATH": str(root / "topic2.db"),
        "TOPIC2_FIXTURE_PATH": str(REPO / "data" / "test_fixture" / "golden_sic_dataset.csv"),
        "TOPIC2_CALIBRATION_FIXTURE": str(
            REPO / "data" / "test_fixture" / "golden_sic_calibration.json"
        ),
        "TOPIC2_EQUIPMENT_PROFILES": str(
            REPO / "data" / "test_fixture" / "topic2_equipment_profiles.json"
        ),
        "TOPIC2_ARTIFACT_DIR": str(root / "artifacts"),
        "TOPIC2_REPORT_DIR": str(root / "reports"),
        "ULTRAFAST_MEMORY_ROOT": str(memory_root),
        "TOPIC2_AUTO_SEED_FIXTURE": "true",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--root", default=None, help="scratch dir (default: temp)")
    args = parser.parse_args()

    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="topic2-e2e-"))
    if not args.root:
        print(f"scratch root: {root}")
    env = prepare_fixtures(root)
    os.environ.update(env)

    from apps.topic2_backend.api.app import create_app

    app = create_app()
    # wait until the server is actually serving before announcing READY
    import threading
    import time
    from multiprocessing import Event as MpEvent

    import httpx
    import uvicorn

    ready = MpEvent()

    def probe() -> None:
        while not ready.is_set():
            try:
                with httpx.Client(timeout=1.0) as client:
                    response = client.get(f"http://127.0.0.1:{args.port}/api/v1/health")
                    if response.status_code == 200:
                        print("READY", flush=True)
                        return
            except Exception:  # noqa: BLE001,S110 - server not up yet, retry
                pass
            time.sleep(0.25)

    threading.Thread(target=probe, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    ready.set()


if __name__ == "__main__":
    main()
