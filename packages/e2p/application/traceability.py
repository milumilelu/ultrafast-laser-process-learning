"""Reproducibility and E2P run-manifest helpers."""

from __future__ import annotations

import importlib.metadata
import platform
import subprocess
from pathlib import Path
from typing import Any

from ultrafast_e2p.application.traceability import new_run_id, timestamp

from packages.process_data.versioning import canonical_hash

__all__ = [
    "environment_manifest",
    "git_commit",
    "git_worktree_state",
    "new_run_id",
    "timestamp",
]


def git_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def git_worktree_state(root: Path) -> dict[str, Any]:
    try:
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--",
                ".",
                ":(exclude)outputs/topic2_acceptance",
                ":(exclude)model_artifacts",
                ":(exclude)data/*.db",
                ":(exclude)deploy/topic2_test/*.db",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return {"dirty": bool(status.strip()), "status_hash": canonical_hash(status)}
    except (OSError, subprocess.CalledProcessError):
        return {"dirty": None, "status_hash": "unknown"}


def environment_manifest(
    root: Path, random_seed: int, configuration: dict[str, Any]
) -> dict[str, Any]:
    packages = {}
    for name in ("numpy", "pandas", "scikit-learn", "fastapi", "pydantic"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    worktree = git_worktree_state(root)
    return {
        "python_version": platform.python_version(),
        "package_versions": packages,
        "git_commit": git_commit(root),
        "git_dirty": worktree["dirty"],
        "git_status_hash": worktree["status_hash"],
        "configuration": configuration,
        "configuration_hash": canonical_hash(configuration),
        "seed": random_seed,
    }
