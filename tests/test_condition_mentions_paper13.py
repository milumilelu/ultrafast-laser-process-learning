from __future__ import annotations

import pytest

pytestmark = pytest.mark.pilot


"""Layer 2 hard regression: paper 13 counter-examples (permanent fixtures).

- 200 kHz (writing) ACCEPT frequency
- 40 MHz (lifetime)   ACCEPT frequency (no relation judgment here)
- 25W inside ZHL-25W-272+ -> REJECTED (equipment model)
- ZPL emission wavelengths (1132/1038/1241 nm) -> REJECTED
- 515 nm laser -> ACCEPT wavelength
"""

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.mentions.models import AcceptanceStatus, ContextClass
from tests.conftest import pilot_pdf


def _mentions():
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("13_arxiv_2411.18868.pdf"))
    return extract_mentions(doc)


def _find(mentions, unit: str, value: float):
    return [
        m
        for m in mentions
        if m.normalized_unit == unit and any(abs(v - value) < 1e-9 for v in m.values)
    ]


def test_writing_frequency_accepted() -> None:
    hits = _find(_mentions(), "kHz", 200.0)
    assert hits
    assert any(m.acceptance_status == AcceptanceStatus.ACCEPTED for m in hits)


def test_lifetime_frequency_accepted_without_relation() -> None:
    hits = _find(_mentions(), "MHz", 40.0)
    assert hits
    assert any(m.acceptance_status == AcceptanceStatus.ACCEPTED for m in hits)
    # no linking: must not carry condition membership
    assert all(not hasattr(m, "condition_id") for m in hits)


def test_amplifier_power_rejected() -> None:
    # ZHL-25W-272+ amplifier model: '25 W' must not be ACCEPTED power
    hits = [m for m in _mentions() if m.normalized_unit == "W" and any(abs(v - 25) < 1e-9 for v in m.values)]
    assert hits, "25 W mention should exist inside model token"
    assert all(m.acceptance_status == AcceptanceStatus.REJECTED_CONTEXT for m in hits)
    assert all(m.context_class == ContextClass.EQUIPMENT_MODEL for m in hits)


def test_emission_wavelengths_rejected() -> None:
    mentions = _mentions()
    for wl in (1132.0, 1038.0, 1241.0, 1108.0, 1078.0):
        hits = _find(mentions, "nm", wl)
        assert all(
            m.acceptance_status == AcceptanceStatus.REJECTED_CONTEXT
            for m in hits
        ), f"emission wavelength {wl} nm must be rejected"


def test_laser_wavelength_accepted() -> None:
    hits = _find(_mentions(), "nm", 515.0)
    assert hits
    assert any(m.acceptance_status == AcceptanceStatus.ACCEPTED for m in hits)


def test_no_synthetic_grouping() -> None:
    # Layer 2 must never emit a complete condition composition
    mentions = _mentions()
    for m in mentions:
        assert not hasattr(m, "condition_id")
