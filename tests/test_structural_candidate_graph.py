"""Layer 3 DoD: structural candidate graph edges (not end-to-end JSON).

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

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.graph.builder import build_candidate_graph
from ultrafast_ingestion.graph.models import EdgeType
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import RowKind, table_regions
from tests.conftest import pilot_pdf

pytestmark = pytest.mark.pilot


def _graph(paper_id: str):
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    mentions = extract_mentions(doc)
    graph = build_candidate_graph(doc, mentions, table_regions(doc))
    return graph, mentions


def _find(mentions, unit: str, value: float):
    return [
        m
        for m in mentions
        if m.normalized_unit == unit and any(abs(v - value) < 1e-9 for v in m.values)
    ]


def test_paper13_processing_cluster_edges() -> None:
    graph, mentions = _graph("13_arxiv_2411.18868.pdf")
    khz = _find(mentions, "kHz", 200.0)[0]
    fs = _find(mentions, "fs", 230.0)[0]
    nm = _find(mentions, "nm", 515.0)[0]
    assert graph.has_edge(khz, fs, EdgeType.SAME_PARAMETER_GROUP)
    assert graph.has_edge(khz, nm, EdgeType.SAME_PARAMETER_GROUP)
    assert graph.has_edge(fs, nm, EdgeType.SAME_PARAMETER_GROUP)


def test_paper13_dual_regime_mutually_exclusive() -> None:
    graph, mentions = _graph("13_arxiv_2411.18868.pdf")
    khz = _find(mentions, "kHz", 200.0)[0]
    mhz = _find(mentions, "MHz", 40.0)[0]
    # hard requirement: never fused as a condition candidate
    assert not graph.has_edge(khz, mhz, EdgeType.SAME_EXPERIMENT_CANDIDATE)
    assert not graph.has_edge(khz, mhz, EdgeType.SAME_PARAMETER_GROUP)
    # explicit negative constraint edge
    assert graph.has_edge(khz, mhz, EdgeType.MUTUALLY_EXCLUSIVE)


def test_paper13_measurement_optics_no_processing_edges() -> None:
    graph, mentions = _graph("13_arxiv_2411.18868.pdf")
    proc = _find(mentions, "nm", 515.0)[0]
    for wl in (976.0, 800.0, 914.0):
        meas = _find(mentions, "nm", wl)[0]
        assert not graph.has_edge(proc, meas, EdgeType.SAME_PARAMETER_GROUP)
        assert not graph.has_edge(proc, meas, EdgeType.SAME_EXPERIMENT_CANDIDATE)


def test_paper13_rejected_mentions_have_no_edges() -> None:
    graph, mentions = _graph("13_arxiv_2411.18868.pdf")
    zpl = _find(mentions, "nm", 1132.0)
    for m in zpl:
        assert graph.roles[m.mention_id].value == "REJECTED"
        assert all(
            m.mention_id not in (e.source_mention_id, e.target_mention_id)
            for e in graph.edges
        )


def test_paper11_capability_not_auto_merged() -> None:
    graph, mentions = _graph("11_arxiv_2404.09906.pdf")
    khz10 = _find(mentions, "kHz", 10.0)[0]
    mhz1 = _find(mentions, "MHz", 1.0)[0]
    assert not graph.has_edge(khz10, mhz1, EdgeType.SAME_EXPERIMENT_CANDIDATE)
    assert not graph.has_edge(khz10, mhz1, EdgeType.SAME_PARAMETER_GROUP)


def test_paper11_global_scope_candidate() -> None:
    graph, mentions = _graph("11_arxiv_2404.09906.pdf")
    khz100 = _find(mentions, "kHz", 100.0)[0]
    globals_ = [
        e
        for e in graph.edges
        if khz100.mention_id in (e.source_mention_id, e.target_mention_id)
        and e.type == EdgeType.GLOBAL_SCOPE_CANDIDATE
    ]
    assert globals_, "100 kHz must link to the previous processing block via GLOBAL_SCOPE_CANDIDATE"


def test_paper11_comparison_table_isolated() -> None:
    doc = PyMuPDFDocumentParser().parse(pilot_pdf("11_arxiv_2404.09906.pdf"))
    mentions = extract_mentions(doc)
    regions = table_regions(doc)
    graph = build_candidate_graph(doc, mentions, regions)
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
    graph, mentions = _graph("11_arxiv_2404.09906.pdf")
    proc = _find(mentions, "nm", 1030.0)[0]
    for wl in (737.19, 785.0):
        meas = _find(mentions, "nm", wl)[0]
        assert not graph.has_edge(proc, meas, EdgeType.SAME_PARAMETER_GROUP)
        assert not graph.has_edge(proc, meas, EdgeType.SAME_EXPERIMENT_CANDIDATE)


def test_all_candidate_edges_have_provenance() -> None:
    for paper in (
        "13_arxiv_2411.18868.pdf",
        "11_arxiv_2404.09906.pdf",
        "Flat-top picosecond laser texturing of CFRP.pdf",
    ):
        graph, _ = _graph(paper)
        for e in graph.edges:
            assert e.source_rule, f"edge without rule: {e}"
            assert e.edge_strength.value


def test_structural_synthetic_edge_violations_zero() -> None:
    """Hard gate: reference-forbidden pairings must never be connected as
    SAME_EXPERIMENT candidates by deterministic rules."""
    g13, m13 = _graph("13_arxiv_2411.18868.pdf")
    khz = _find(m13, "kHz", 200.0)[0]
    mhz = _find(m13, "MHz", 40.0)[0]
    g11, m11 = _graph("11_arxiv_2404.09906.pdf")
    khz10 = _find(m11, "kHz", 10.0)[0]
    mhz1 = _find(m11, "MHz", 1.0)[0]
    forbidden = [
        (khz.mention_id, mhz.mention_id, EdgeType.SAME_EXPERIMENT_CANDIDATE),
        (khz.mention_id, mhz.mention_id, EdgeType.SAME_PARAMETER_GROUP),
        (khz10.mention_id, mhz1.mention_id, EdgeType.SAME_EXPERIMENT_CANDIDATE),
        (khz10.mention_id, mhz1.mention_id, EdgeType.SAME_PARAMETER_GROUP),
    ]
    assert g13.synthetic_edge_violations(forbidden) == 0
    assert g11.synthetic_edge_violations(forbidden) == 0
