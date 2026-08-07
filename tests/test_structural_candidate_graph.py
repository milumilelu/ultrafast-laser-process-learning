"""Layer 3 DoD: structural candidate graph edges (not end-to-end JSON).

Phase B: the graph is built over the CandidateLedger routing view; node ids
are ledger candidate ids (I9/I10).

DoD:
1. Paper 11/13 reference edge graph expressible
2. processing / measurement / comparison: no cross-role pollution
3. 200 kHz vs 40 MHz: no SAME_EXPERIMENT candidate, explicit
   MUTUALLY_EXCLUSIVE edge
4. comparison table never enters processing cluster
5. all candidate edges carry deterministic provenance
hard metric: structural synthetic-edge violations == 0
"""

from __future__ import annotations

import pytest

from tests.conftest import pilot_pdf
from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.graph.builder import build_candidate_graph
from ultrafast_ingestion.graph.models import EdgeType, MentionRole
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import RowKind, table_regions

pytestmark = pytest.mark.pilot


def _graph(paper_id: str):
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    mentions = extract_mentions(doc)
    regions = table_regions(doc)
    ledger = build_ledger(doc, mentions, regions)
    view = ledger.for_condition_linking(doc, regions)
    graph = build_candidate_graph(doc, view)
    return graph, view, mentions


def _find_ids(graph, unit: str, value: float) -> list[str]:
    return [
        mid
        for mid, m in graph.mentions.items()
        if m.normalized_unit == unit and any(abs(v - value) < 1e-9 for v in m.values)
    ]


def _find_one(graph, unit: str, value: float) -> str:
    hits = _find_ids(graph, unit, value)
    assert hits, f"no mention {value} {unit}"
    return hits[0]


def test_paper13_processing_cluster_edges() -> None:
    graph, _, _ = _graph("13_arxiv_2411.18868.pdf")
    khz = _find_one(graph, "kHz", 200.0)
    fs = _find_one(graph, "fs", 230.0)
    nm = _find_one(graph, "nm", 515.0)
    assert graph.has_edge(khz, fs, EdgeType.SAME_PARAMETER_GROUP)
    assert graph.has_edge(khz, nm, EdgeType.SAME_PARAMETER_GROUP)
    assert graph.has_edge(fs, nm, EdgeType.SAME_PARAMETER_GROUP)


def test_paper13_dual_regime_mutually_exclusive() -> None:
    graph, _, _ = _graph("13_arxiv_2411.18868.pdf")
    khz = _find_one(graph, "kHz", 200.0)
    mhz = _find_one(graph, "MHz", 40.0)
    # hard requirement: never fused as a condition candidate
    assert not graph.has_edge(khz, mhz, EdgeType.SAME_EXPERIMENT_CANDIDATE)
    assert not graph.has_edge(khz, mhz, EdgeType.SAME_PARAMETER_GROUP)
    # explicit negative constraint edge
    assert graph.has_edge(khz, mhz, EdgeType.MUTUALLY_EXCLUSIVE)


def test_paper13_measurement_optics_no_processing_edges() -> None:
    graph, _, _ = _graph("13_arxiv_2411.18868.pdf")
    proc = _find_one(graph, "nm", 515.0)
    for wl in (976.0, 800.0, 914.0):
        meas = _find_one(graph, "nm", wl)
        assert not graph.has_edge(proc, meas, EdgeType.SAME_PARAMETER_GROUP)
        assert not graph.has_edge(proc, meas, EdgeType.SAME_EXPERIMENT_CANDIDATE)


def test_paper13_rejected_mentions_have_no_edges() -> None:
    graph, view, _ = _graph("13_arxiv_2411.18868.pdf")
    zpl_ids = _find_ids(graph, "nm", 1132.0)
    assert zpl_ids, "1132 nm ZPL mentions must be registered as nodes"
    for mid in zpl_ids:
        # registered with REJECTED role (node-set semantics preserved), zero edges
        assert graph.roles[mid].value == "REJECTED"
        assert view.mentions[mid].acceptance_status.value == "REJECTED_CONTEXT"
        assert all(
            mid not in (e.source_mention_id, e.target_mention_id)
            for e in graph.edges
        )


def test_paper11_capability_not_auto_merged() -> None:
    graph, _, _ = _graph("11_arxiv_2404.09906.pdf")
    khz10 = _find_one(graph, "kHz", 10.0)
    mhz1 = _find_one(graph, "MHz", 1.0)
    assert not graph.has_edge(khz10, mhz1, EdgeType.SAME_EXPERIMENT_CANDIDATE)
    assert not graph.has_edge(khz10, mhz1, EdgeType.SAME_PARAMETER_GROUP)


def test_paper11_global_scope_candidate() -> None:
    graph, _, _ = _graph("11_arxiv_2404.09906.pdf")
    khz100 = _find_one(graph, "kHz", 100.0)
    globals_ = [
        e
        for e in graph.edges
        if khz100 in (e.source_mention_id, e.target_mention_id)
        and e.type == EdgeType.GLOBAL_SCOPE_CANDIDATE
    ]
    assert globals_, "100 kHz must link to the previous processing block via GLOBAL_SCOPE_CANDIDATE"


def test_paper11_comparison_table_isolated() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    mentions = extract_mentions(doc)
    regions = table_regions(doc)
    ledger = build_ledger(doc, mentions, regions)
    view = ledger.for_condition_linking(doc, regions)
    graph = build_candidate_graph(doc, view)
    ref_edges = graph.edges_of_type(EdgeType.COMPARISON_ONLY)
    assert ref_edges, "Table I reference rows must produce COMPARISON_ONLY edges"
    table_id = ref_edges[0].source_table_id
    for e in ref_edges:
        assert e.source_table_id == table_id
        assert e.source_rule == "COMPARISON_TABLE_REFERENCE_ROW"
        assert e.source_row is not None
    # reference-row indices must never seed a processing cluster
    region = next(r for r in regions if r.table_id == table_id)
    ref_rows = {row.index for row in region.rows if row.kind == RowKind.REFERENCE}
    assert not any(
        e.type == EdgeType.SAME_EXPERIMENT_CANDIDATE and e.source_row in ref_rows
        for e in graph.edges
    )
    # this-work rows DO seed candidate clusters
    this_work = {row.index for row in region.rows if row.kind == RowKind.THIS_WORK}
    assert any(
        e.type == EdgeType.SAME_EXPERIMENT_CANDIDATE and e.source_row in this_work
        for e in graph.edges
    )


def test_paper11_measurement_wavelengths_isolated() -> None:
    graph, _, _ = _graph("11_arxiv_2404.09906.pdf")
    proc = _find_one(graph, "nm", 1030.0)
    for wl in (737.19, 785.0):
        meas = _find_one(graph, "nm", wl)
        assert not graph.has_edge(proc, meas, EdgeType.SAME_PARAMETER_GROUP)
        assert not graph.has_edge(proc, meas, EdgeType.SAME_EXPERIMENT_CANDIDATE)


def test_all_candidate_edges_have_provenance() -> None:
    for paper in (
        "13_arxiv_2411.18868.pdf",
        "11_arxiv_2404.09906.pdf",
        "Flat-top picosecond laser texturing of CFRP.pdf",
    ):
        graph, _, _ = _graph(paper)
        for e in graph.edges:
            assert e.source_rule, f"edge without rule: {e}"
            assert e.edge_strength.value


def test_structural_synthetic_edge_violations_zero() -> None:
    """Hard gate: reference-forbidden pairings must never be connected as
    SAME_EXPERIMENT candidates by deterministic rules."""
    g13, _, _ = _graph("13_arxiv_2411.18868.pdf")
    khz = _find_one(g13, "kHz", 200.0)
    mhz = _find_one(g13, "MHz", 40.0)
    g11, _, _ = _graph("11_arxiv_2404.09906.pdf")
    khz10 = _find_one(g11, "kHz", 10.0)
    mhz1 = _find_one(g11, "MHz", 1.0)
    forbidden = [
        (khz, mhz, EdgeType.SAME_EXPERIMENT_CANDIDATE),
        (khz, mhz, EdgeType.SAME_PARAMETER_GROUP),
        (khz10, mhz1, EdgeType.SAME_EXPERIMENT_CANDIDATE),
        (khz10, mhz1, EdgeType.SAME_PARAMETER_GROUP),
    ]
    assert g13.synthetic_edge_violations(forbidden) == 0
    assert g11.synthetic_edge_violations(forbidden) == 0


def test_ledger_identity_authority_no_synthetic_ids() -> None:
    """I9/I10: every graph node id and every edge endpoint is a ledger candidate id."""
    graph, view, _ = _graph("11_arxiv_2404.09906.pdf")
    ledger_ids = set(view.mentions) | set(view.cell_nodes)
    assert set(graph.mentions) == set(view.mentions)
    for e in graph.edges:
        assert e.source_mention_id in ledger_ids, "synthetic node id in graph"
        assert e.target_mention_id in ledger_ids, "synthetic node id in graph"
    assert not any(mid.startswith("cell:") for mid in graph.mentions)
    assert not any(
        e.source_mention_id.startswith("cell:") or e.target_mention_id.startswith("cell:")
        for e in graph.edges
    ), "_cell_key hack must be gone (I10)"


def test_rejected_roles_present_in_graph() -> None:
    """Node-set equivalence: rejected mentions are registered nodes with REJECTED role."""
    graph, view, _ = _graph("13_arxiv_2411.18868.pdf")
    rejected_ids = [
        cid
        for cid, m in view.mentions.items()
        if m.acceptance_status.value == "REJECTED_CONTEXT"
    ]
    assert rejected_ids
    for cid in rejected_ids:
        assert graph.roles[cid] == MentionRole.REJECTED
