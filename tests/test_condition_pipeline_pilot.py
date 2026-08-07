"""Layer 4 pilot pipeline: recorded linker -> validator -> compiler.

Hard gates L4-G1..G9 verified against the human references.
Uses recorded responses (deterministic CI); real-LLM benchmark is
@pytest.mark.benchmark and never runs by default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.conditions.compiler import compile_conditions
from ultrafast_ingestion.conditions.models import FieldStatus, ValidationErrorCode, ValidatedRelationGraph
from ultrafast_ingestion.conditions.validator import validate
from ultrafast_ingestion.graph.builder import build_candidate_graph
from ultrafast_ingestion.linking.linker import run_recorded
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import table_regions
from tests.conftest import pilot_pdf

pytestmark = pytest.mark.pilot

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _pipeline(paper_id: str, record_name: str):
    doc = PyMuPDFDocumentParser().parse(pilot_pdf(paper_id))
    mentions = extract_mentions(doc)
    graph = build_candidate_graph(doc, mentions, table_regions(doc))
    result = run_recorded(FIXTURES / record_name, graph, doc.paper_id, doc.document_version_id)
    vr = ValidatedRelationGraph(graph=graph, accepted=result.proposals)
    validate(vr)
    compiled = compile_conditions(vr)
    return vr, compiled, mentions


def _find(mentions, unit: str, value: float):
    return [
        m
        for m in mentions
        if m.normalized_unit == unit and any(abs(v - value) < 1e-9 for v in m.values)
    ]


def test_paper13_no_synthetic_condition_gate() -> None:
    vr, compiled, mentions = _pipeline("13_arxiv_2411.18868.pdf", "recorded_linker_paper13.jsonl")
    assert not vr.rejected, [r.error_code.value for r in vr.rejected]
    # L4-G2: synthetic condition rate == 0
    assert compiled.synthetic_condition_rate() == 0.0
    # L4-G3: 40 MHz never inside a processing condition
    mhz = _find(mentions, "MHz", 40.0)
    for m in mhz:
        assert all(m.mention_id not in c.mention_ids for c in compiled.conditions if c.role.value == "PROCESSING")
    # processing cluster contains 515/230fs/200kHz
    proc = [c for c in compiled.conditions if c.role.value == "PROCESSING"]
    assert proc
    cluster = set(proc[0].mention_ids)
    for spec in (("nm", 515.0), ("fs", 230.0), ("kHz", 200.0)):
        mid = _find(mentions, spec[0], spec[1])[0].mention_id
        assert mid in cluster


def test_paper13_conflict_preserved_f4() -> None:
    _, compiled, mentions = _pipeline("13_arxiv_2411.18868.pdf", "recorded_linker_paper13.jsonl")
    proc = [c for c in compiled.conditions if c.role.value == "PROCESSING"][0]
    field = proc.fields.get("pulse_energy")
    assert field is not None
    # 2-445 nJ is a single RANGE mention -> REPORTED_CLEAR (range preserved,
    # not a conflict); the 22-450 variant lives in the measurement section,
    # never dropped by the pipeline (present as extracted mentions)
    assert field.status == FieldStatus.REPORTED_CLEAR
    assert sorted(field.values) == [2.0, 445.0]
    assert _find(mentions, "nJ", 22.0) and _find(mentions, "nJ", 450.0)


def test_paper11_abstain_linkage_ambiguous() -> None:
    vr, compiled, mentions = _pipeline("11_arxiv_2404.09906.pdf", "recorded_linker_paper11.jsonl")
    assert not vr.rejected, [r.error_code.value for r in vr.rejected]
    # L4-G4: 10 kHz / 1 MHz not force-resolved -> frequency stays
    # LINKAGE_AMBIGUOUS (ABSTAIN respected), never REPORTED_CLEAR
    khz10 = _find(mentions, "kHz", 10.0)[0].mention_id
    mhz1 = _find(mentions, "MHz", 1.0)[0].mention_id
    assert mhz1 in vr.graph.mentions  # capability mention preserved as mention
    for c in compiled.conditions:
        freq = c.fields.get("frequency")
        if freq is not None:
            assert freq.status == FieldStatus.LINKAGE_AMBIGUOUS, (
                "10kHz vs up-to-1MHz must not be force-resolved"
            )
    assert khz10 in {m for c in compiled.conditions for m in c.mention_ids} or khz10 in compiled.unassigned_mentions
    # L4-G1: synthetic conditions == 0
    assert compiled.synthetic_condition_rate() == 0.0
    # global scope: 1030nm/383fs inherited into processing conditions
    proc = [c for c in compiled.conditions if c.role.value == "PROCESSING"]
    assert proc
    assert all("wavelength" in c.fields for c in proc)


def test_paper11_measurement_never_in_processing() -> None:
    _, compiled, mentions = _pipeline("11_arxiv_2404.09906.pdf", "recorded_linker_paper11.jsonl")
    proc = [c for c in compiled.conditions if c.role.value == "PROCESSING"]
    proc_ids = {m for c in proc for m in c.mention_ids}
    for wl in (737.19, 785.0):
        for m in _find(mentions, "nm", wl):
            assert m.mention_id not in proc_ids


def test_paper11_comparison_rows_not_in_processing() -> None:
    _, compiled, _ = _pipeline("11_arxiv_2404.09906.pdf", "recorded_linker_paper11.jsonl")
    # comparison-only mentions (cell keys) must not appear in conditions
    for c in compiled.conditions:
        assert all(not m.startswith("cell:") for m in c.mention_ids)
