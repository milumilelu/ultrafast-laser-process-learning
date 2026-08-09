"""Shared fixtures: pilot paper PDFs (env-configured, no absolute paths).

Archive resolution order:
1. env ULTRAFAST_PILOT_ARCHIVE (explicit)
2. sibling directory "ultrafast agent" next to this repository
3. otherwise pilot fixtures skip (never silently pass)
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from demo.t2_slice.resources import PILOT_FILES, resolve_literature_archive


def _archive_path() -> Path | None:
    try:
        return resolve_literature_archive()
    except RuntimeError:
        return None


ARCHIVE = _archive_path()


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
