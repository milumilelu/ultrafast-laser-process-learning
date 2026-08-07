from __future__ import annotations

import pytest

pytestmark = pytest.mark.pilot


"""Layer 2 mention extraction on paper 11 (extraction only, no linking)."""

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.mentions.models import AcceptanceStatus
from tests.conftest import pilot_pdf


def _mentions():
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    return extract_mentions(doc)


def _find(mentions, unit: str, value: float):
    return [
        m
        for m in mentions
        if m.normalized_unit == unit and any(abs(v - value) < 1e-9 for v in m.values)
    ]


def test_laser_parameters_extracted() -> None:
    mentions = _mentions()
    assert _find(mentions, "nm", 1030.0), "1030 nm missing"
    assert _find(mentions, "fs", 383.0), "383 fs missing"
    assert _find(mentions, "kHz", 10.0), "10 kHz missing"
    assert _find(mentions, "MHz", 1.0), "1 MHz missing"
    assert _find(mentions, "kHz", 100.0), "100 kHz missing"


def test_system_capability_not_confused_with_processing() -> None:
    mentions = _mentions()
    mhz = _find(mentions, "MHz", 1.0)
    assert mhz, "1 MHz mention missing"
    # 'up to 1 MHz' is capability spec -> not ACCEPTED as plain process
    assert all(
        m.acceptance_status != AcceptanceStatus.ACCEPTED for m in mhz
    ) or any(
        m.context_class.value == "CAPABILITY_SPEC" for m in mhz
    )


def test_no_condition_membership_fields() -> None:
    mentions = _mentions()
    for m in mentions:
        assert not hasattr(m, "condition_id")
        assert not hasattr(m, "group_id")
