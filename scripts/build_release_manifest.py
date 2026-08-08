"""RF-7: release manifest generator (artifacts/releases/<tag>/).

Records the exact scientific payload of a frozen demo run so that any future
point in time can answer: which data, which 5 papers, which CFA/BO versions
were shown. The stable payload hash strips run identifiers (bo_run_id /
created_at) so it is byte-stable across replays (R16).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from demo.t2_slice.pipeline import _CSV_PATH
from demo.t2_slice.resources import PILOT_FILES, resolve_pilot_pdf
from ultrafast_cfa.cfa import CFA_VERSION

RUN_JSON = REPO / "outputs" / "t2_slice_run.json"
RUN_ID_FIELDS = ("created_at", "bo_run_id", "bo_run_id_assisted", "bo_run_id_vanilla")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strip_run_ids(value):
    if isinstance(value, dict):
        return {
            k: _strip_run_ids(v)
            for k, v in value.items()
            if k not in RUN_ID_FIELDS and "bo_run_id" not in k
        }
    if isinstance(value, list):
        return [_strip_run_ids(v) for v in value]
    return value


def _stable_payload_hash(run: dict) -> str:
    payload = _strip_run_ids(run)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for module in ("numpy", "pandas", "scikit_learn", "pydantic", "sqlalchemy", "fastapi"):
        try:
            mod = __import__(module)
            versions[module] = getattr(mod, "__version__", "unknown")
        except ImportError:
            versions[module] = "not_installed"
    return versions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="topic2-demo-v1.1")
    parser.add_argument("--run", type=Path, default=RUN_JSON)
    args = parser.parse_args()

    run = json.loads(args.run.read_text(encoding="utf-8"))
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()

    literature = []
    for paper_id, filename in sorted(PILOT_FILES.items()):
        pdf = resolve_pilot_pdf(paper_id)
        literature.append(
            {"paper_id": paper_id, "archive_filename": filename, "archive_sha256": _sha256(pdf)}
        )

    manifest = {
        "release_tag": args.tag,
        "commit_sha": commit,
        "dataset": {
            "path": str(_CSV_PATH.relative_to(REPO)),
            "sha256": _sha256(_CSV_PATH),
        },
        "literature": literature,
        "equipment_profile_id": "EQ-DEMO-FS",
        "equipment_profile": {"spot_radius_um": 5.0, "unverified": True},
        "random_seed": 42,
        "versions": {
            "physics_formula_registry": "v1",
            "cfa": CFA_VERSION,
            "e2p_prior_spec": "e2p-soft-prior-v1",
            "bo": (run["bo"]["evidence_assisted"].get("model_version") or ""),
            "acquisition": ((run["bo"]["evidence_assisted"].get("acquisition") or {}).get("version") or ""),
            "dependencies": _dependency_versions(),
        },
        "stable_scientific_payload_hash": _stable_payload_hash(run),
        "payload": {
            "sample_count": run["target_task"]["sample_count"],
            "selected_model": run["process_learning"]["selected_model"],
            "selected_feature_view": run["process_learning"]["selected_feature_view"],
            "prior_count": run["e2p_prior"]["prior_count"],
            "governed_prior_hash": run["e2p_prior"]["governed_prior"]["content_hash"],
            "assisted_search_prior_applied": run["bo"]["prior_applied_evidence"]["assisted_search_prior_applied"],
            "cfa_status": run["cfa"]["calibration_status"],
            "cfa_facets": run["audit"]["cfa_facets"],
        },
    }

    out_dir = REPO / "artifacts" / "releases" / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    # expected summary = the stable payload subset a fresh run must reproduce
    (out_dir / "expected_summary.json").write_text(
        json.dumps(manifest["payload"], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"manifest written: {out_dir}")
    print("stable payload hash:", manifest["stable_scientific_payload_hash"][:16], "...")
    print("commit:", commit)


if __name__ == "__main__":
    main()
