"""Start the topic2 backend for frontend HTTP E2E over real resources.

The isolated environment is built only from repository-owned source assets:
original machining CSV/XLSX files and an original pilot paper PDF. It never
generates papers or injects synthetic observations, priors, or demo equipment.

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

def prepare_real_resources(root: Path) -> dict[str, str]:
    """Load traceable experimental records and one original paper."""
    from dataclasses import replace

    from apps.topic2_backend.service import Topic2Service
    from apps.topic2_backend.settings import Settings
    from packages.process_contracts.schemas import ExperimentRecord
    from scripts.import_real_data import build_records
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
        equipment_profiles_path=None,
        calibration_fixture_path=None,
        prior_fixture_path=None,
        auto_seed_fixture=False,
        equipment_profiles={},
    )
    service = Topic2Service(settings, approval_verifier=lambda _review_id: False)
    records = [ExperimentRecord.model_validate(item) for item in build_records()]
    service.repository.import_experiments(records)

    from apps.topic2_backend.application.literature_fixture import seed_from_pdfs

    seeded = seed_from_pdfs(paper_ids=["11_arxiv_2404.09906.pdf"])
    dataset = service.repository.latest_dataset(real_only=True)
    print(
        f"real resources ready: {len(records)} observations, "
        f"dataset={dataset['dataset_version'] if dataset else 'missing'}, "
        f"{seeded['papers']} original PDF",
        flush=True,
    )

    return {
        "TOPIC2_DB_PATH": str(root / "topic2.db"),
        "TOPIC2_EQUIPMENT_PROFILES": str(root / "no-equipment-profiles.json"),
        "TOPIC2_CALIBRATION_FIXTURE": str(root / "no-calibration.json"),
        "TOPIC2_PRIOR_FIXTURE": str(root / "no-priors.json"),
        "TOPIC2_ARTIFACT_DIR": str(root / "artifacts"),
        "TOPIC2_REPORT_DIR": str(root / "reports"),
        "ULTRAFAST_MEMORY_ROOT": str(memory_root),
        "TOPIC2_AUTO_SEED_FIXTURE": "false",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument(
        "--agent-port",
        type=int,
        default=None,
        help="optional local Agent port used by the same-origin proxy",
    )
    parser.add_argument("--root", default=None, help="scratch dir (default: temp)")
    args = parser.parse_args()

    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="topic2-e2e-"))
    if not args.root:
        print(f"scratch root: {root}")
    env = prepare_real_resources(root)
    os.environ.update(env)
    if args.agent_port is not None:
        os.environ["TOPIC2_AGENT_PROXY_TARGET"] = (
            f"http://127.0.0.1:{args.agent_port}"
        )

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
