"""Phase B behavioral-equivalence gate (CANDIDATE_LEDGER_V0_1 §5.1, I12).

The ledger-backed pipeline (ledger -> ConditionLinkView -> graph -> linker
-> validator -> compiler) must be exactly equivalent to the pre-Phase-B
pipeline captured in tests/fixtures/phase_b_legacy_*.json, after
normalizing both sides to source-identity space:

- mentions  -> ConditionMention.mention_id (lineage anchor)
- table cells -> legacy "cell:block:row:param:value" key (audit anchor)

Compared: node set + roles, edge set (type/rule/strength/block_ids/
table_id/row/quote), conditions (role/scope/mention identities/fields),
unassigned mentions, synthetic_condition_count.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import pilot_pdf
from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.candidates.ledger import build_ledger, legacy_cell_key
from ultrafast_ingestion.conditions.compiler import compile_conditions
from ultrafast_ingestion.conditions.models import ValidatedRelationGraph
from ultrafast_ingestion.conditions.validator import validate
from ultrafast_ingestion.graph.builder import build_candidate_graph
from ultrafast_ingestion.linking.linker import run_recorded
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import table_regions

pytestmark = pytest.mark.pilot

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

PAPERS = [
    ("04_arxiv_2502.16530.pdf", None),
    ("10_arxiv_2411.18093.pdf", None),
    ("11_arxiv_2404.09906.pdf", "recorded_linker_paper11.jsonl"),
    ("13_arxiv_2411.18868.pdf", "recorded_linker_paper13.jsonl"),
    ("Flat-top picosecond laser texturing of CFRP.pdf", None),
]


def _load(stem: str) -> dict:
    return json.loads((FIXTURES / f"phase_b_legacy_{stem}.json").read_text(encoding="utf-8"))


def _ledger_backed(paper_id: str, record: str | None):
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    mentions = extract_mentions(doc)
    regions = table_regions(doc)
    ledger = build_ledger(doc, mentions, regions)
    view = ledger.for_condition_linking(doc, regions)
    graph = build_candidate_graph(doc, view)
    return doc, graph, view


def _norm_endpoint(graph, view, cid: str) -> str:
    """Normalize a graph node id to source identity (mention_id / legacy cell key)."""
    if cid in graph.mentions:
        return graph.mentions[cid].mention_id
    node = view.cell_nodes[cid]
    return legacy_cell_key(node.cell)


def _norm_graph(graph, view) -> dict:
    nodes = sorted(
        (graph.mentions[mid].mention_id, graph.roles.get(mid, "UNCLEAR").value)
        for mid in graph.mentions
    )
    edges = sorted(
        (
            e.type.value,
            _norm_endpoint(graph, view, e.source_mention_id),
            _norm_endpoint(graph, view, e.target_mention_id),
            e.source_rule,
            e.edge_strength.value,
            tuple(e.source_block_ids),
            e.source_table_id,
            e.source_row,
            e.source_quote,
        )
        for e in graph.edges
    )
    return {"nodes": nodes, "edges": edges}


def _param_value_unit_pairs(mentions_by_id, member_ids) -> dict[str, list[tuple]]:
    """(value, unit) pairs per parameter from the member mentions.

    The field-level unit of a mixed-unit CONFLICT_PRESERVED field is an
    id-sort artifact (unit = first mention's unit); the underlying
    per-mention (value, unit) pairs are id-independent ground truth.
    """
    pairs: dict[str, list[tuple]] = {}
    for mid in member_ids:
        m = mentions_by_id.get(mid)
        if m is None:
            continue
        for v in m.values:
            pairs.setdefault(m.parameter, []).append((v, m.normalized_unit))
    return pairs


def _param_value_unit_pairs_by_identity(mentions_by_identity, member_identities) -> dict[str, list[tuple]]:
    """(value, unit) pairs per parameter from member mentions keyed by mention_id."""
    pairs: dict[str, list[tuple]] = {}
    for mid in member_identities:
        m = mentions_by_identity.get(mid)
        if m is None:
            continue
        for v in m.values:
            pairs.setdefault(m.parameter, []).append((v, m.normalized_unit))
    return pairs


def _norm_compile(graph, compiled) -> dict:
    mentions_by_id = {mid: m for mid, m in graph.mentions.items()}
    conditions = sorted(
        (
            c.role.value,
            c.scope.value,
            tuple(sorted(mentions_by_id[m].mention_id for m in c.mention_ids if m in mentions_by_id)),
            tuple(
                sorted(
                    (
                        param,
                        f.status.value,
                        tuple(sorted(f.values)),
                        tuple(sorted(_param_value_unit_pairs(mentions_by_id, c.mention_ids).get(param, []))),
                        tuple(sorted(f.provenance_anchor_ids)),
                    )
                    for param, f in c.fields.items()
                )
            ),
        )
        for c in compiled.conditions
    )
    return {
        "conditions": conditions,
        "unassigned": sorted(
            mentions_by_id[m].mention_id for m in compiled.unassigned_mentions if m in mentions_by_id
        ),
        "synthetic_condition_count": compiled.synthetic_condition_count,
    }


@pytest.mark.parametrize("paper_id,record", PAPERS)
def test_graph_equivalent_to_legacy(paper_id: str, record: str | None) -> None:
    fixture = _load(f"graph_{paper_id.replace('.pdf', '')}")
    doc, graph, view = _ledger_backed(paper_id, record)
    assert doc.document_version_id == fixture["document_version_id"], (
        "parser/version drift invalidates the legacy fixture"
    )
    actual = _norm_graph(graph, view)
    expected = {
        "nodes": sorted((n, r) for n, r in fixture["nodes"]),
        "edges": sorted(
            (
                e["type"],
                e["source"],
                e["target"],
                e["rule"],
                e["strength"],
                tuple(e["block_ids"]),
                e["table_id"],
                e["row"],
                e["quote"],
            )
            for e in fixture["edges"]
        ),
    }
    assert actual == expected


@pytest.mark.parametrize("paper_id,record", PAPERS)
def test_compile_equivalent_to_legacy(paper_id: str, record: str | None) -> None:
    fixture = _load(f"compile_{paper_id.replace('.pdf', '')}")
    doc, graph, _view = _ledger_backed(paper_id, record)
    # fixture mention_ids are identities (mention_id); map identity -> mention
    mentions_by_identity = {m.mention_id: m for m in graph.mentions.values()}
    if record is not None:
        result = run_recorded(FIXTURES / record, graph, doc.paper_id, doc.document_version_id)
        vr = ValidatedRelationGraph(graph=graph, accepted=result.proposals)
        validate(vr)
    else:
        vr = ValidatedRelationGraph(graph=graph)
    compiled = compile_conditions(vr)
    actual = _norm_compile(graph, compiled)
    expected = {
        "conditions": sorted(
            (
                c["role"],
                c["scope"],
                tuple(sorted(c["mention_ids"])),
                tuple(
                    sorted(
                        (
                            param,
                            f["status"],
                            tuple(sorted(f["values"])),
                            # unit is id-sort dependent on mixed-unit CONFLICT
                            # fields; compare the underlying (value, unit) pairs
                            # reconstructed from the same member mentions
                            tuple(
                                sorted(
                                    _param_value_unit_pairs_by_identity(
                                        mentions_by_identity, c["mention_ids"]
                                    ).get(param, [])
                                )
                            ),
                            tuple(sorted(f["anchors"])),
                        )
                        for param, f in c["fields"].items()
                    )
                ),
            )
            for c in fixture["conditions"]
        ),
        "unassigned": sorted(fixture["unassigned_mentions"]),
        "synthetic_condition_count": fixture["synthetic_condition_count"],
    }
    assert actual == expected
