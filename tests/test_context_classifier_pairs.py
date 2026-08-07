"""Context classifier pair tests: negative + nearby positive (unit level).

These guard against rule interference: fixing one false-positive class
must not break the adjacent true parameter. Pure-text windows, no PDFs,
no archive dependency (fast, offline).
"""

from __future__ import annotations

import re

import pytest

from ultrafast_ingestion.mentions.context import classify
from ultrafast_ingestion.mentions.models import AcceptanceStatus

pytestmark = pytest.mark.unit

CASES = [
    # (window_text, unit, expected_status, expected_parameter)
    # emission vs laser wavelength
    ("an emission peak at 1038 nm was observed", "nm", AcceptanceStatus.REJECTED_CONTEXT, "wavelength"),
    ("the 1030 nm femtosecond laser was used", "nm", AcceptanceStatus.ACCEPTED, "wavelength"),
    ("PL6 divacancies (1038 nm) were also observed", "nm", AcceptanceStatus.REJECTED_CONTEXT, "wavelength"),
    ("a CW 976 nm diode laser excited the sample", "nm", AcceptanceStatus.ACCEPTED, "wavelength"),
    # equipment model vs real power
    ("the ZHL-25W-272+ amplifier was used", "W", AcceptanceStatus.REJECTED_CONTEXT, "average_power"),
    ("the average laser power was set to 25 W", "W", AcceptanceStatus.ACCEPTED, "average_power"),
    # capability spec vs actual processing frequency
    ("the system supports a repetition rate up to 1 MHz", "MHz", AcceptanceStatus.AMBIGUOUS_CONTEXT, "frequency"),
    ("a repetition rate of 200 kHz was used for writing", "kHz", AcceptanceStatus.ACCEPTED, "frequency"),
    # ODMR/spin frequency vs laser frequency
    ("the zero field splitting of 4.5 MHz for V1", "MHz", AcceptanceStatus.REJECTED_CONTEXT, "frequency"),
    ("the laser pulse repetition rate was 40 MHz", "MHz", AcceptanceStatus.ACCEPTED, "frequency"),
    # length disambiguation
    ("the focal spot diameter was 15 um at 1/e", "um", AcceptanceStatus.ACCEPTED, "spot_size"),
    ("the dots were written 5 um apart", "um", AcceptanceStatus.ACCEPTED, "pitch"),
    ("written at 2 and 4 um depths", "um", AcceptanceStatus.ACCEPTED, "depth"),
    # dimensionless
    ("the writing objective has NA = 0.90", "NA", AcceptanceStatus.ACCEPTED, "na"),
]


def _mention_pos(text: str) -> tuple[int, int]:
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    assert m, f"no numeric token in {text!r}"
    return m.start(), m.end()


@pytest.mark.parametrize("text,unit,expected_status,expected_parameter", CASES)
def test_context_pairs(text: str, unit: str, expected_status: str, expected_parameter: str) -> None:
    start, end = _mention_pos(text)
    status, _cls, param, _reason = classify("", unit, start, end, window=text)
    assert status == expected_status, f"status mismatch for {text!r}"
    assert param == expected_parameter, f"parameter mismatch for {text!r}"
