"""R17: demo report generator - discipline check + determinism."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from scripts.demo_report import build_report, check_report

pytestmark = pytest.mark.unit

FIXTURE = REPO / "outputs" / "t2_slice_run.json"


@pytest.mark.skipif(not FIXTURE.exists(), reason="requires frozen Scenario 01 run output")
def test_report_generates_and_passes_discipline() -> None:
    result = json.loads(FIXTURE.read_text(encoding="utf-8"))
    text = build_report(result)
    assert check_report(text) == []
    for section in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"):
        assert section in text, f"missing story section {section}"
    assert "RSM" in text
    assert "NOT_YET_CALIBRATED" in text


@pytest.mark.skipif(not FIXTURE.exists(), reason="requires frozen Scenario 01 run output")
def test_report_deterministic() -> None:
    result = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first = build_report(result)
    second = build_report(result)
    assert first == second
