from __future__ import annotations

import pytest

pytestmark = pytest.mark.pilot


"""False-negative regression fixtures (S0-2B7 mention audit).

Permanent fixtures for the systematic gaps found in the audit:
- dual-unit range spanning block wrap ("2 nJ/pulse to 445 nJ/pulse")
- parameter table cells "Label (unit) value" / range cells
- kJ/cm2 accumulated dose
- length-unit disambiguation (depth/pitch) via nearest context word
- NA dimensionless extraction
- ODMR/spin frequencies rejected; "V1" labels not matched as numbers
"""

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.mentions.models import AcceptanceStatus, MentionValueType
from tests.conftest import pilot_pdf


def _mentions(paper_id: str):
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    return extract_mentions(doc)


def _find(mentions, unit: str, value: float):
    return [
        m
        for m in mentions
        if m.normalized_unit == unit and any(abs(v - value) < 1e-9 for v in m.values)
    ]


def test_cross_block_dual_unit_range_paper13() -> None:
    hits = _find(_mentions("13_arxiv_2411.18868.pdf"), "nJ", 445.0)
    ranges = [m for m in hits if m.value_type == MentionValueType.RANGE and any(abs(v - 2) < 1e-9 for v in m.values)]
    assert ranges, "2-445 nJ must be a single RANGE mention (cross-block wrap)"


def test_depth_and_pitch_disambiguation_paper13() -> None:
    mentions = _mentions("13_arxiv_2411.18868.pdf")
    depth = [m for m in mentions if m.parameter == "depth" and m.normalized_unit == "um" and any(abs(v - 2) < 1e-9 for v in m.values)]
    assert depth, "2 and 4 um depths must classify as depth"
    pitch = [m for m in mentions if m.parameter == "pitch" and any(abs(v - 5) < 1e-9 for v in m.values)]
    assert pitch, "5 um apart must classify as pitch"


def test_na_dimensionless_paper13() -> None:
    hits = _find(_mentions("13_arxiv_2411.18868.pdf"), "NA", 0.9)
    assert hits and all(m.parameter == "na" for m in hits)


def test_kj_cm2_accumulated_dose_paper04() -> None:
    mentions = _mentions("04_arxiv_2502.16530.pdf")
    dose = [
        m
        for m in mentions
        if m.normalized_unit == "kJ/cm2"
        and m.value_type == MentionValueType.RANGE
        and any(abs(v - 1) < 1e-9 for v in m.values)
        and any(abs(v - 500) < 1e-9 for v in m.values)
    ]
    assert dose, "1-500 kJ/cm2 accumulated dose must be a RANGE mention"


def test_table_cells_paper_flat_top() -> None:
    mentions = _mentions("Flat-top picosecond laser texturing of CFRP.pdf")
    spot = [
        m
        for m in mentions
        if m.parameter == "spot_size"
        and m.value_type == MentionValueType.SCALAR
        and any(abs(v - 19) < 1e-9 for v in m.values)
    ]
    assert spot, "table cell 'Spot diameter (um) 19' must extract as spot_size SCALAR"
    speed = [
        m
        for m in mentions
        if m.parameter == "scan_speed" and any(abs(v - 1) < 1e-9 for v in m.values)
    ]
    assert speed, "table cell 'Scanning speed (m/s) 1' must extract as scan_speed"
    fluence = [
        m
        for m in mentions
        if m.parameter == "fluence"
        and m.value_type == MentionValueType.RANGE
        and any(abs(v - 2.3) < 1e-9 for v in m.values)
    ]
    assert fluence, "table cell 'Fluence range (J/cm2) 2.3-7.0' must be RANGE"


def test_odmr_frequencies_rejected_paper11() -> None:
    mentions = _mentions("11_arxiv_2404.09906.pdf")
    for mhz in (4.5, 70.0):
        hits = _find(mentions, "MHz", mhz)
        assert hits
        assert all(
            m.acceptance_status == AcceptanceStatus.REJECTED_CONTEXT for m in hits
        ), f"ODMR zero-field splitting {mhz} MHz must be rejected"


def test_defect_label_not_matched_as_number_paper11() -> None:
    # "V1 and 70 MHz" must NOT produce a "1 and 70 MHz" LIST mention
    mentions = _mentions("11_arxiv_2404.09906.pdf")
    merged = [
        m
        for m in mentions
        if m.value_type == MentionValueType.LIST
        and any(abs(v - 1) < 1e-9 for v in m.values)
        and any(abs(v - 70) < 1e-9 for v in m.values)
    ]
    assert not merged, "'V1 and 70 MHz' must not merge into a LIST mention"
