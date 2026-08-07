"""Shared fixtures: pilot paper PDFs from the legacy archive (read-only)."""

from __future__ import annotations

from pathlib import Path

import pytest

ARCHIVE = Path(
    r"C:\Users\RZF\Desktop\博士课题资料\ultrafast agent"
    r"\ultrafast_laser_memory\data\literature_archive"
)

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
    return ARCHIVE / PILOT_FILES[paper_id]


@pytest.fixture()
def pilot_11() -> Path:
    return pilot_pdf("11_arxiv_2404.09906.pdf")


@pytest.fixture()
def pilot_13() -> Path:
    return pilot_pdf("13_arxiv_2411.18868.pdf")
