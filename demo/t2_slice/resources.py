"""Demo literature resources: archive resolution independent of tests (RF-2).

The demo runner must not depend on pytest fixtures. Archive resolution order:
  1. ULTRAFAST_PILOT_ARCHIVE env (explicit)
  2. sibling "ultrafast agent/ultrafast_laser_memory/data/literature_archive"
Missing archive/PDF -> RuntimeError with actionable message (no pytest.skip).
Tests reuse these resolvers and keep their own skip semantics.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# short paper_id -> archive filename (fixed 5-paper pilot set, Demo Scenario 01)
PILOT_FILES: dict[str, str] = {
    "04_arxiv_2502.16530.pdf": "2dbee78cde23f8f0_04_arxiv_2502.16530.pdf",
    "10_arxiv_2411.18093.pdf": "c896b8bc0f3aac44_10_arxiv_2411.18093.pdf",
    "11_arxiv_2404.09906.pdf": "14bd5786dcb52033_11_arxiv_2404.09906.pdf",
    "13_arxiv_2411.18868.pdf": "2ee9b7fd04167bc5_13_arxiv_2411.18868.pdf",
    "Flat-top picosecond laser texturing of CFRP.pdf": (
        "185a6a0667e0b43d_Flat-top picosecond laser texturing of CFRP.pdf"
    ),
}

PILOT_PAPER_IDS: tuple[str, ...] = tuple(PILOT_FILES)


def resolve_literature_archive() -> Path:
    """Return the literature archive directory or raise RuntimeError."""
    env = os.environ.get("ULTRAFAST_PILOT_ARCHIVE")
    if env:
        archive = Path(env)
        if archive.is_dir():
            return archive
        raise RuntimeError(
            f"ULTRAFAST_PILOT_ARCHIVE is set but not a directory: {env}"
        )
    sibling = REPO_ROOT.parent / "ultrafast agent" / "ultrafast_laser_memory" / "data" / "literature_archive"
    if sibling.is_dir():
        return sibling
    raise RuntimeError(
        "literature archive not found; set ULTRAFAST_PILOT_ARCHIVE=<dir> "
        "or place 'ultrafast agent' as a sibling of the repository"
    )


def resolve_pilot_pdf(paper_id: str) -> Path:
    """Return the archive path of a pilot PDF or raise RuntimeError."""
    archive = resolve_literature_archive()
    try:
        filename = PILOT_FILES[paper_id]
    except KeyError as exc:
        raise RuntimeError(f"unknown pilot paper_id: {paper_id}") from exc
    path = archive / filename
    if not path.exists():
        raise RuntimeError(
            f"pilot PDF missing in archive ({archive}): {filename}"
        )
    return path
