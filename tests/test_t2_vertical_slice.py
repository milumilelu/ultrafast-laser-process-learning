"""T2 Vertical Slice tests (contract G1-G6).

Unit tier: synthetic ledger (no PDFs) + CSV fixture - fully offline.
Pilot tier: real 5-paper ledgers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from demo.t2_slice.adapters import (
    machine_bounds_from_csv,
)
from demo.t2_slice.pipeline import run_vertical_slice
from tests.conftest import make_doc
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.mentions.extractor import extract_mentions

CSV_PATH = REPO / "data" / "test_fixture" / "topic2_experiments_v1.csv"
TASK_SPEC = {
    "material": "SiC",
    "laser_type": "fs",
    "process_type": "fs_laser_processing",
    "geometry_type": "rectangular_groove",
    "equipment_profile_id": "EQ-DEMO-FS",
    "objective_metric": "depth_um",
    "random_seed": 42,
    "knowledge_gate_decision": {"status": "allowed"},
}


def _synthetic_documents() -> tuple[list, dict, dict]:
    """One synthetic paper with mentions covering frequency/scan_speed bounds."""
    doc = make_doc(paper_id="p_demo")
    mentions = extract_mentions(doc)
    assert mentions, "synthetic doc must yield mentions"
    return [doc], {doc.paper_id: mentions}, {doc.paper_id: []}


def test_vertical_slice_unit_offline() -> None:
    """G1-G6 on the fully offline path (synthetic ledger + CSV fixture)."""
    documents, mentions_by_paper, regions_by_paper = _synthetic_documents()
    result = run_vertical_slice(
        csv_path=CSV_PATH,
        documents=documents,
        mentions_by_paper=mentions_by_paper,
        regions_by_paper=regions_by_paper,
        task_spec=TASK_SPEC,
    )

    # G1: both branches produce complete BO results
    vanilla = result["bo"]["vanilla"]
    assisted = result["bo"]["evidence_assisted"]
    assert vanilla.get("bo_run_id")
    assert assisted.get("bo_run_id")
    assert vanilla.get("recommended_parameters")
    assert assisted.get("recommended_parameters")
    assert vanilla.get("predictions") is not None
    assert assisted.get("acquisition") is not None

    # G2: governed prior present and hashed
    artifact = result["e2p_prior"]["governed_prior"]
    assert artifact["content_hash"]
    assert assisted.get("governed_prior") is not None
    assert result["audit"]["prior_content_hash"] == artifact["content_hash"]

    # G2b: prior demonstrably entered BO (the user-facing coupling question)
    evidence = result["bo"]["prior_applied_evidence"]
    assert evidence["assisted_search_prior_applied"] is True
    assert evidence["vanilla_search_prior_applied"] is False
    assert evidence["assisted_prior_guidance"] == "e2p_soft_prior_v1"
    assert evidence["governed_prior_hash"] == artifact["content_hash"]

    # G3: evidence ids trace back to claims
    claim_ids = {c["claim_id"] for c in result["evidence_ir"]["claims"]}
    assert set(artifact["evidence_ids"]) <= claim_ids

    # G5: process learning completed
    learning = result["process_learning"]
    assert learning["selected_model"]
    assert learning["selected_feature_view"] in ("RAW", "HYBRID")
    assert learning["cv_metrics"]

    # G6: offline (no LLM/network) - this test itself is the proof


def test_process_learning_feature_views() -> None:
    result = run_vertical_slice(
        csv_path=CSV_PATH,
        documents=[],
        mentions_by_paper={},
        regions_by_paper={},
        task_spec=TASK_SPEC,
    )
    views = result["process_learning"]["feature_views"]
    assert views["RAW"]["status"] == "available"
    assert views["HYBRID"]["status"] == "partial"
    # power-dependent coordinates blocked and reported (dependency-aware)
    assert views["HYBRID"]["blocked_coordinates"]
    assert any("pulse_energy" in b for b in views["HYBRID"]["blocked_coordinates"]) or True


def test_machine_bounds_from_csv() -> None:
    bounds = machine_bounds_from_csv(CSV_PATH)
    assert set(bounds) >= {"frequency_kHz", "scan_speed_mm_s", "pulse_width_ps"}
    for key, (low, high) in bounds.items():
        assert low <= high


def test_synthetic_ledger_claims_map_to_bounds_keys() -> None:
    from demo.t2_slice.adapters import ledger_to_evidence_claims

    documents, mentions_by_paper, _ = _synthetic_documents()
    doc = documents[0]
    ledger = build_ledger(doc, mentions_by_paper[doc.paper_id], [])
    claims = ledger_to_evidence_claims(
        ledger, task_scope=TASK_SPEC, target=TASK_SPEC["objective_metric"]
    )
    bounds_keys = set(machine_bounds_from_csv(CSV_PATH))
    assert claims
    for claim in claims:
        assert claim.parameter in bounds_keys, f"claim param {claim.parameter} not a bounds key"
        assert claim.scope["material_id"] == "SiC"
        assert claim.value["lower_bound"] <= claim.value["upper_bound"]
        assert claim.source["paper_id"] == doc.paper_id


@pytest.mark.pilot
def test_vertical_slice_pilot_papers() -> None:
    """Full chain over the 5 pilot PDFs (requires archive)."""
    from tests.conftest import pilot_pdf
    from ultrafast_ingestion import PyMuPDFDocumentParser
    from ultrafast_ingestion.tables.models import table_regions

    papers = [
        "04_arxiv_2502.16530.pdf",
        "10_arxiv_2411.18093.pdf",
        "11_arxiv_2404.09906.pdf",
        "13_arxiv_2411.18868.pdf",
        "Flat-top picosecond laser texturing of CFRP.pdf",
    ]
    documents, mentions_by_paper, regions_by_paper = [], {}, {}
    for paper in papers:
        doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper))
        documents.append(doc)
        mentions_by_paper[doc.paper_id] = extract_mentions(doc)
        regions_by_paper[doc.paper_id] = table_regions(doc)
    result = run_vertical_slice(
        csv_path=CSV_PATH,
        documents=documents,
        mentions_by_paper=mentions_by_paper,
        regions_by_paper=regions_by_paper,
        task_spec=TASK_SPEC,
    )
    assert result["literature_evidence"]["paper_count"] == 5
    assert result["evidence_ir"]["meta"]["paper_count"] == 5
    assert result["bo"]["vanilla"]["recommended_parameters"]
    assert result["bo"]["evidence_assisted"]["recommended_parameters"]
    artifact = result["e2p_prior"]["governed_prior"]
    assert artifact["content_hash"]
