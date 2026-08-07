"""Shared fixtures: pilot paper PDFs (env-configured, no absolute paths).

Archive resolution order:
1. env ULTRAFAST_PILOT_ARCHIVE (explicit)
2. sibling directory "ultrafast agent" next to this repository
3. otherwise pilot fixtures skip (never silently pass)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _archive_path() -> Path | None:
    env = os.environ.get("ULTRAFAST_PILOT_ARCHIVE")
    if env:
        return Path(env)
    sibling = REPO_ROOT.parent / "ultrafast agent" / "ultrafast_laser_memory" / "data" / "literature_archive"
    if sibling.is_dir():
        return sibling
    return None


ARCHIVE = _archive_path()

PILOT_FILES = {
    "04_arxiv_2502.16530.pdf": "2dbee78cde23f8f0_04_arxiv_2502.16530.pdf",
    "10_arxiv_2411.18093.pdf": "c896b8bc0f3aac44_10_arxiv_2411.18093.pdf",
    "11_arxiv_2404.09906.pdf": "14bd5786dcb52033_11_arxiv_2404.09906.pdf",
    "13_arxiv_2411.18868.pdf": "2ee9b7fd04167bc5_13_arxiv_2411.18868.pdf",
    "Flat-top picosecond laser texturing of CFRP.pdf": (
        "185a6a0667e0b43d_Flat-top picosecond laser texturing of CFRP.pdf"
    ),
}


def pilot_pdf(paper_id: str) -> Path:
    if ARCHIVE is None:
        pytest.skip(
            "pilot PDF archive not found "
            "(set ULTRAFAST_PILOT_ARCHIVE or place 'ultrafast agent' as sibling)"
        )
    path = ARCHIVE / PILOT_FILES[paper_id]
    if not path.exists():
        pytest.skip(f"pilot PDF missing: {path}")
    return path


@pytest.fixture()
def pilot_11() -> Path:
    return pilot_pdf("11_arxiv_2404.09906.pdf")


@pytest.fixture()
def pilot_13() -> Path:
    return pilot_pdf("13_arxiv_2411.18868.pdf")
