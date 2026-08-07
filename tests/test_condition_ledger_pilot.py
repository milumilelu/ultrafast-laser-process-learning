"""Phase A audit over the real pilot pipeline (CANDIDATE_LEDGER_V0_1.md §5).

Invariants I1-I5 against live Layer 1-4 outputs, plus the Phase B identity
checks (I9/I10) and lossless mention restoration (contract §1.2 / §8.2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import pilot_pdf
from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import CandidateSourceType, PromotionStatus
from ultrafast_ingestion.conditions.compiler import compile_conditions
from ultrafast_ingestion.conditions.models import ValidatedRelationGraph
from ultrafast_ingestion.conditions.validator import validate
from ultrafast_ingestion.graph.builder import build_candidate_graph
from ultrafast_ingestion.linking.linker import run_recorded
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import table_regions

pytestmark = pytest.mark.pilot

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

PILOT_PAPERS = [
    ("04_arxiv_2502.16530.pdf", None),
    ("10_arxiv_2411.18093.pdf", None),
    ("11_arxiv_2404.09906.pdf", "recorded_linker_paper11.jsonl"),
    ("13_arxiv_2411.18868.pdf", "recorded_linker_paper13.jsonl"),
    ("Flat-top picosecond laser texturing of CFRP.pdf", None),
]


def _pipeline(paper_id: str, record_name: str | None):
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    mentions = extract_mentions(doc)
    regions = table_regions(doc)
    graph = build_candidate_graph(doc, build_ledger(doc, mentions, regions).for_condition_linking(doc, regions))
    if record_name is None:
        return doc, mentions, regions, graph, None, None
    result = run_recorded(FIXTURES / record_name, graph, doc.paper_id, doc.document_version_id)
    vr = ValidatedRelationGraph(graph=graph, accepted=result.proposals)
    validate(vr)
    compiled = compile_conditions(vr)
    return doc, mentions, regions, graph, vr, compiled


@pytest.mark.parametrize("paper_id,record", PILOT_PAPERS)
def test_ledger_invariants_on_pilot(paper_id: str, record: str | None) -> None:
    doc, mentions, regions, graph, _vr, compiled = _pipeline(paper_id, record)
    ledger = build_ledger(doc, mentions, regions, compile_result=compiled)
    view = ledger.for_condition_linking(doc, regions)

    by_ref: dict[str, list] = {}
    for c in ledger.candidates:
        by_ref.setdefault(c.source_ref, []).append(c)

    # I1/I2/I3: every mention (any status) -> exactly one candidate
    for m in mentions:
        assert m.mention_id in by_ref, f"mention lost: {m.mention_id}"
        assert len(by_ref[m.mention_id]) == 1, f"mention duplicated: {m.mention_id}"

    # I4: every unassigned mention traceable
    if compiled is not None:
        for mid in compiled.unassigned_mentions:
            candidate = next(c for c in ledger.candidates if c.candidate_id == mid)
            assert candidate.promotion_status == PromotionStatus.NOT_PROMOTED
            assert candidate.promotion_reason == "unassigned_after_linking"

    # I5': every graph node id and edge endpoint is a ledger candidate id (I9/I10)
    ledger_ids = {c.candidate_id for c in ledger.candidates}
    assert set(graph.mentions) == set(view.mentions)
    for e in graph.edges:
        assert e.source_mention_id in ledger_ids, f"synthetic id in graph: {e.source_mention_id}"
        assert e.target_mention_id in ledger_ids, f"synthetic id in graph: {e.target_mention_id}"
    # every cell node the graph may reference is a ledger TABLE_CELL candidate
    cell_ids = set(view.cell_nodes)
    ledger_cells = {
        c.candidate_id for c in ledger.candidates if c.source_type == CandidateSourceType.TABLE_CELL
    }
    assert cell_ids <= ledger_cells

    # restoration roundtrip: view mentions are exactly the extractor mentions (lossless)
    restored_by_ref = {m.mention_id: m for m in view.mentions.values()}
    assert set(restored_by_ref) == {m.mention_id for m in mentions}
    original_by_ref = {m.mention_id: m for m in mentions}
    for mid, original in original_by_ref.items():
        assert restored_by_ref[mid] == original, f"restored mention diverges: {mid}"

    # I6/I7: determinism and roundtrip
    rebuilt = build_ledger(doc, mentions, regions, compile_result=compiled)
    assert rebuilt == ledger
    assert rebuilt.to_canonical_dict() == ledger.to_canonical_dict()

    # DoD 1: Layer 1-4 behavior unchanged (no synthetic conditions, honest compile)
    if compiled is not None:
        assert compiled.synthetic_condition_rate() == 0.0


@pytest.mark.parametrize("paper_id,record", PILOT_PAPERS)
def test_ledger_artifact_written_on_pilot(paper_id: str, record: str | None, tmp_path: Path) -> None:
    doc, mentions, regions, _graph, _vr, compiled = _pipeline(paper_id, record)
    ledger = build_ledger(doc, mentions, regions, compile_result=compiled)
    path = ledger.write_artifact(tmp_path)
    assert path.exists()
    assert path.parent.name == doc.paper_id
    payload = path.read_text(encoding="utf-8")
    assert '"schema_version": "candidate-ledger-v0.1"' in payload
    assert f'"candidate_count": {ledger.metrics["candidate_count"]}' in payload
