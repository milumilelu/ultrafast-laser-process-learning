"""B1 CFA facet confusion audit unit tests (B1_CHECKPOINT_V0_1 §3)."""

from __future__ import annotations

import pytest

from benchmarks.cfa_confusion.audit import (
    audit_coordinates,
    audit_facets,
    audit_report,
)

pytestmark = pytest.mark.unit

HUMAN = [
    {
        "paper_id": "p1",
        "level3_facets": {
            "Material": "UNKNOWN",
            "Task": "KNOWN",
            "InteractionState": "PARTIAL",
            "Reconstructibility": "PARTIAL",
            "Reachability": "PARTIAL",
        },
        "level2_coordinates": {"peak_fluence": "AVAILABLE"},
    },
    {
        "paper_id": "p2",
        "level3_facets": {
            "Material": "MISMATCH",
            "Task": "PARTIAL",
            "InteractionState": "UNKNOWN",
            "Reconstructibility": "UNKNOWN",
            "Reachability": "UNKNOWN",
        },
        "level2_coordinates": {"peak_fluence": "NOT_REPORTED"},
    },
]

SYSTEM = [
    {
        "paper_id": "p1",
        "level3_cfa": {
            "facet_summary": {
                "Material": "UNKNOWN",
                "Task": "KNOWN",
                "InteractionState": "PARTIAL",
                "Reconstructibility": "PARTIAL",
                "Reachability": "PARTIAL",
            }
        },
        "level2_coordinates": {"peak_fluence": {"availability": "AVAILABLE"}},
    },
    {
        "paper_id": "p2",
        "level3_cfa": {
            "facet_summary": {
                "Material": "UNKNOWN",  # system says UNKNOWN, human says MISMATCH
                "Task": "PARTIAL",
                "InteractionState": "UNKNOWN",
                "Reconstructibility": "UNKNOWN",
                "Reachability": "UNKNOWN",
            }
        },
        "level2_coordinates": {"peak_fluence": {"availability": "AVAILABLE"}},
    },
]


def test_facet_confusion_consistent() -> None:
    facets = audit_facets(HUMAN, SYSTEM)
    by_name = {f.facet: f for f in facets}
    # p1 Material: human UNKNOWN / system UNKNOWN -> consistent
    assert by_name["Material"].matrix[("UNKNOWN", "UNKNOWN")] == 1
    assert by_name["Material"].consistent == 1


def test_conservative_miss_classified() -> None:
    """Human MISMATCH & System UNKNOWN -> conservative miss (safe, not severe)."""
    facets = audit_facets(HUMAN, SYSTEM)
    by_name = {f.facet: f for f in facets}
    assert by_name["Material"].conservative_miss == 1
    assert by_name["Material"].severe == 0
    assert by_name["Material"].matrix[("MISMATCH", "UNKNOWN")] == 1


def test_severe_error_classified() -> None:
    """Human UNKNOWN & System MISMATCH -> severe (negative judgment without evidence)."""
    human = [
        {
            "paper_id": "p3",
            "level3_facets": {
                "Material": "UNKNOWN",
                "Task": "KNOWN",
                "InteractionState": "PARTIAL",
                "Reconstructibility": "PARTIAL",
                "Reachability": "PARTIAL",
            },
        }
    ]
    system = [
        {
            "paper_id": "p3",
            "level3_cfa": {
                "facet_summary": {
                    "Material": "MISMATCH",
                    "Task": "KNOWN",
                    "InteractionState": "PARTIAL",
                    "Reconstructibility": "PARTIAL",
                    "Reachability": "PARTIAL",
                }
            },
        }
    ]
    facets = audit_facets(human, system)
    assert facets[0].severe == 1
    assert facets[0].matrix[("UNKNOWN", "MISMATCH")] == 1


def test_coordinate_confusion() -> None:
    result = audit_coordinates(HUMAN, SYSTEM)
    # p1: AVAILABLE/AVAILABLE consistent; p2: NOT_REPORTED/AVAILABLE -> system FP
    assert result["matrix"]["AVAILABLE/AVAILABLE"] == 1
    assert result["matrix"]["NOT_REPORTED/AVAILABLE"] == 1
    assert result["total"] == 2


def test_full_report_no_probabilities() -> None:
    report = audit_report(HUMAN, SYSTEM)
    payload = str(report).lower()
    assert "probability" not in payload
    assert "confidence" not in payload
    assert len(report["level3_facets"]) == 5
    assert report["severity_summary"]["conservative_miss"] == 1
