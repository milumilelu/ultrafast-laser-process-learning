"""Demo V3 integration gate (M6-M9 wired back into the Topic2 slice).

Five end-to-end assertions per the V3 scope (integration gate, not a
scientific-validity proof):
  1. calibration_status == NOT_YET_CALIBRATED
  2. no probability/confidence/transfer pseudo-calibration fields anywhere
  3. target power missing -> peak_fluence never COMPARABLE (no silent downgrade)
  4. spot UNVERIFIED -> overlap family yields UNVERIFIED/warnings only,
     never treated as valid matching evidence
  5. prior_applied_evidence keeps its M5.5 behavior (CFA must not break E2P->BO)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from demo.t2_slice.pipeline import run_vertical_slice
from tests.test_t2_vertical_slice import CSV_PATH, TASK_SPEC
from ultrafast_ingestion.mentions.extractor import extract_mentions

pytestmark = pytest.mark.unit


def _slice_result():
    doc = _make_demo_doc()
    mentions = extract_mentions(doc)
    return run_vertical_slice(
        csv_path=CSV_PATH,
        documents=[doc],
        mentions_by_paper={doc.paper_id: mentions},
        regions_by_paper={doc.paper_id: []},
        task_spec=TASK_SPEC,
    )


def _make_demo_doc():
    from tests.conftest import DOC_BLOCK_TEXT
    from ultrafast_ingestion.models.document import PageBlock, ScientificDocument, Section

    paper_id = "p_demo_v3"
    version = "dv_demo_v3_000000000000"
    block = PageBlock(
        paper_id=paper_id,
        document_version_id=version,
        page_index=0,
        bbox=(0.0, 0.0, 500.0, 100.0),
        block_index=0,
        reading_order=0,
        text=DOC_BLOCK_TEXT,
        section_id="s1",
        section_path="Methods",
    )
    section = Section(
        section_id="s1",
        title="Methods",
        section_type="methods",
        level=1,
        page_start=0,
        page_end=0,
        path="Methods",
    )
    return ScientificDocument(
        paper_id=paper_id,
        document_version_id=version,
        pdf_path="",
        pdf_sha256="",
        parser_name="test",
        parser_version="0",
        schema_version="test",
        config_hash="test",
        pages=[[block]],
        sections=[section],
        blocks_by_id={block.block_id(): block},
    )


def test_calibration_status_not_yet_calibrated() -> None:
    result = _slice_result()
    assert result["cfa"]["calibration_status"] == "NOT_YET_CALIBRATED"
    assert result["audit"]["cfa_status"] == "NOT_YET_CALIBRATED"


def test_no_pseudo_calibration_fields() -> None:
    result = _slice_result()
    payload = str(result).lower()
    for forbidden in ("probability", "confidence", "transfer_probability", "transfer_class"):
        assert forbidden not in payload, f"pseudo-calibration field leaked: {forbidden}"


def test_power_missing_peak_fluence_never_comparable() -> None:
    result = _slice_result()
    reports = result["cfa"]["reports"]
    assert reports, "CFA must produce per-paper reports"
    for report in reports:
        interaction = next(
            f for f in report["facets"] if f["facet"] == "InteractionState"
        )
        entry = interaction["coordinates"].get("peak_fluence")
        if entry is not None:
            # target lacks power: peak_fluence must never be COMPARABLE
            assert entry["comparability"] != "COMPARABLE", (
                f"peak_fluence wrongly comparable: {entry}"
            )
            assert entry["reason"], "INCOMPARABLE/UNVERIFIED must carry a reason"


def test_spot_unverified_overlap_not_valid_matching_evidence() -> None:
    result = _slice_result()
    for report in result["cfa"]["reports"]:
        interaction = next(
            f for f in report["facets"] if f["facet"] == "InteractionState"
        )
        for name, entry in interaction["coordinates"].items():
            if name in ("pulse_overlap", "hatch_overlap", "pulses_per_spot"):
                # spot=5um UNVERIFIED -> UNVERIFIED or INCOMPARABLE, never COMPARABLE
                assert entry["comparability"] != "COMPARABLE", f"{name} wrongly comparable"
        # the CFA report warns about unverified coordinates
        assert any("unverified" in w.lower() for w in report["warnings"]), (
            "unverified coordinates must be surfaced in warnings"
        )


def test_audit_cfa_facets_are_real_not_placeholder() -> None:
    """audit.cfa_facets must be aggregated from actual assess_all reports
    (the v1 placeholder hardcoded UNKNOWN x5)."""
    result = _slice_result()
    facets = result["audit"]["cfa_facets"]
    assert set(facets) == {
        "Material",
        "Task",
        "InteractionState",
        "Reconstructibility",
        "Reachability",
    }
    assert all(v in ("KNOWN", "PARTIAL", "UNKNOWN", "MISMATCH") for v in facets.values())
    reports = result["cfa"]["reports"]
    first = {f["facet"]: f["status"] for f in reports[0]["facets"]}
    assert facets["Material"] == first["Material"]
    assert facets["Task"] == first["Task"]
    assert facets["Reconstructibility"] == first["Reconstructibility"]
    assert facets["Reachability"] == first["Reachability"]


def test_prior_applied_evidence_unchanged() -> None:
    """G5: CFA integration must not break the M5.5 E2P->prior->BO chain."""
    result = _slice_result()
    evidence = result["bo"]["prior_applied_evidence"]
    assert evidence["assisted_search_prior_applied"] is True
    assert evidence["vanilla_search_prior_applied"] is False
    assert evidence["assisted_prior_guidance"] == "e2p_soft_prior_v1"
    # CFA is audit-only: governed prior still flows unchanged
    assert result["e2p_prior"]["governed_prior"]["content_hash"]
    assert result["bo"]["evidence_assisted"]["recommended_parameters"]
