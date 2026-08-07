"""Layer 4 unit tests: hard-constraint validator + deterministic compiler
(crafted graphs, no LLM, no archive)."""

from __future__ import annotations

import pytest

from ultrafast_ingestion.conditions.compiler import compile_conditions
from ultrafast_ingestion.conditions.models import (
    FieldStatus,
    ValidatedRelationGraph,
    ValidationErrorCode,
)
from ultrafast_ingestion.conditions.validator import validate
from ultrafast_ingestion.graph.models import (
    CandidateEdge,
    CandidateGraph,
    EdgeStrength,
    EdgeType,
    MentionRole,
)
from ultrafast_ingestion.linking.models import (
    EvidenceStrength,
    LinkDecision,
    LinkProposal,
    RelationType,
    Scope,
)
from ultrafast_ingestion.mentions.models import AcceptanceStatus, ConditionMention, ContextClass
from ultrafast_ingestion.models.provenance import ProvenanceAnchor

pytestmark = pytest.mark.unit


def _mention(mid: str, param: str, unit: str, value: float, status=AcceptanceStatus.ACCEPTED):
    anchor = ProvenanceAnchor(paper_id="p", document_version_id="d", pdf_page_index=0)
    return ConditionMention(
        mention_id=mid, parameter=param, raw_text=f"{value} {unit}", values=[value],
        value_type="SCALAR", normalized_unit=unit, context_class=ContextClass.PROCESS_CONTEXT,
        acceptance_status=status, anchor=anchor,
    )


def _graph(mentions: list[ConditionMention], edges: list[CandidateEdge]) -> CandidateGraph:
    g = CandidateGraph()
    for m in mentions:
        role = MentionRole.REJECTED if m.acceptance_status == AcceptanceStatus.REJECTED_CONTEXT else MentionRole.PROCESSING
        g.add_mention(m.mention_id, m, role)
    for e in edges:
        g.add_edge(e)
    return g


def _proposal(pid: str, decision: LinkDecision, mids: list[str], relation: RelationType | None, **kw) -> LinkProposal:
    return LinkProposal(
        proposal_id=pid, decision=decision, mention_ids=tuple(mids), relation=relation,
        evidence_strength=kw.pop("strength", EvidenceStrength.EXPLICIT),
        supporting_edge_ids=kw.pop("edges", []), **kw,
    )


def test_unknown_mention_rejected() -> None:
    g = _graph([_mention("a", "wavelength", "nm", 515.0)], [])
    vr = ValidatedRelationGraph(graph=g, accepted=[_proposal("P1", LinkDecision.LINK, ["a", "zz"], RelationType.SAME_EXPERIMENT)])
    validate(vr)
    assert any(r.error_code == ValidationErrorCode.UNKNOWN_MENTION for r in vr.rejected)


def test_mutually_exclusive_blocks_link() -> None:
    a, b = _mention("a", "frequency", "kHz", 200.0), _mention("b", "frequency", "MHz", 40.0)
    g = _graph([a, b], [CandidateEdge("a", "b", EdgeType.MUTUALLY_EXCLUSIVE, "ROLE", EdgeStrength.STRONG)])
    vr = ValidatedRelationGraph(
        graph=g,
        accepted=[_proposal("P1", LinkDecision.LINK, ["a", "b"], RelationType.SAME_EXPERIMENT)],
    )
    validate(vr)
    codes = {r.error_code for r in vr.rejected}
    assert ValidationErrorCode.CONTRADICTS_HARD_STRUCTURAL_CONSTRAINT in codes
    assert vr.accepted == []


def test_rejected_mention_cannot_join_condition() -> None:
    a = _mention("a", "wavelength", "nm", 1132.0, status=AcceptanceStatus.REJECTED_CONTEXT)
    b = _mention("b", "wavelength", "nm", 515.0)
    g = _graph([a, b], [])
    vr = ValidatedRelationGraph(graph=g, accepted=[_proposal("P1", LinkDecision.LINK, ["a", "b"], RelationType.SAME_EXPERIMENT)])
    validate(vr)
    assert any(r.error_code == ValidationErrorCode.REJECTED_MENTION_IN_CONDITION for r in vr.rejected)


def test_comparison_pollution_rejected() -> None:
    a, b = _mention("a", "wavelength", "nm", 790.0), _mention("b", "wavelength", "nm", 515.0)
    g = _graph([a, b], [CandidateEdge("a", "b", EdgeType.COMPARISON_ONLY, "REF", EdgeStrength.STRONG)])
    vr = ValidatedRelationGraph(graph=g, accepted=[_proposal("P1", LinkDecision.LINK, ["a", "b"], RelationType.SAME_EXPERIMENT)])
    validate(vr)
    assert any(r.error_code == ValidationErrorCode.COMPARISON_POLLUTION for r in vr.rejected)


def test_measurement_processing_pollution_rejected() -> None:
    a, b = _mention("a", "wavelength", "nm", 976.0), _mention("b", "wavelength", "nm", 515.0)
    g = CandidateGraph()
    g.add_mention(a.mention_id, a, MentionRole.MEASUREMENT)
    g.add_mention(b.mention_id, b, MentionRole.PROCESSING)
    vr = ValidatedRelationGraph(graph=g, accepted=[_proposal("P1", LinkDecision.LINK, ["a", "b"], RelationType.SAME_EXPERIMENT)])
    validate(vr)
    assert any(r.error_code == ValidationErrorCode.MEASUREMENT_POLLUTION for r in vr.rejected)


def test_conflict_warning_not_resolution() -> None:
    a, b = _mention("a", "pulse_energy", "nJ", 2.0), _mention("b", "pulse_energy", "nJ", 445.0)
    g = _graph([a, b], [])
    vr = ValidatedRelationGraph(graph=g, accepted=[_proposal("P1", LinkDecision.LINK, ["a", "b"], RelationType.SAME_EXPERIMENT)])
    validate(vr)
    assert any("CONFLICT_PRESERVED" in w for w in vr.warnings)
    assert vr.accepted  # LINK allowed; compiler preserves conflict


def test_abstain_always_accepted() -> None:
    a, b = _mention("a", "frequency", "kHz", 10.0), _mention("b", "frequency", "MHz", 1.0)
    g = _graph([a, b], [])
    vr = ValidatedRelationGraph(graph=g, accepted=[_proposal("P1", LinkDecision.ABSTAIN, ["a", "b"], None)])
    validate(vr)
    assert vr.accepted and not vr.rejected


def test_compiler_connected_components_and_conflict() -> None:
    a = _mention("a", "wavelength", "nm", 515.0)
    b = _mention("b", "pulse_width", "fs", 230.0)
    c = _mention("c", "frequency", "kHz", 200.0)
    d = _mention("d", "frequency", "MHz", 40.0)
    g = _graph([a, b, c, d], [])
    vr = ValidatedRelationGraph(
        graph=g,
        accepted=[
            _proposal("P1", LinkDecision.LINK, ["a", "b"], RelationType.SAME_EXPERIMENT),
            _proposal("P2", LinkDecision.LINK, ["b", "c"], RelationType.SAME_EXPERIMENT),
            _proposal("P3", LinkDecision.SEPARATE, ["c", "d"], RelationType.MUTUALLY_EXCLUSIVE),
        ],
    )
    validate(vr)
    result = compile_conditions(vr)
    proc = [cond for cond in result.conditions if cond.role.value == "PROCESSING"]
    assert len(proc) == 1
    assert set(proc[0].fields) == {"wavelength", "pulse_width", "frequency"}
    assert proc[0].fields["wavelength"].values == [515.0]
    assert d.mention_id in result.unassigned_mentions
    assert result.synthetic_condition_count == 0


def test_compiler_conflict_preserved_f4() -> None:
    a = _mention("a", "pulse_energy", "nJ", 2.0)
    b = _mention("b", "pulse_energy", "nJ", 445.0)
    c = _mention("c", "wavelength", "nm", 515.0)
    g = _graph([a, b, c], [])
    vr = ValidatedRelationGraph(
        graph=g,
        accepted=[
            _proposal("P1", LinkDecision.LINK, ["a", "b"], RelationType.SAME_EXPERIMENT),
            _proposal("P2", LinkDecision.LINK, ["b", "c"], RelationType.SAME_EXPERIMENT),
        ],
    )
    validate(vr)
    result = compile_conditions(vr)
    field = result.conditions[0].fields["pulse_energy"]
    assert field.status == FieldStatus.CONFLICT_PRESERVED
    assert sorted(field.values) == [2.0, 445.0]


def test_compiler_global_scope_inheritance() -> None:
    a = _mention("a", "wavelength", "nm", 1030.0)
    b = _mention("b", "pulse_energy", "nJ", 60.0)
    c = _mention("c", "pulse_energy", "nJ", 1850.0)
    g = _graph([a, b, c], [])
    vr = ValidatedRelationGraph(
        graph=g,
        accepted=[
            _proposal("P1", LinkDecision.ASSIGN_SCOPE, ["a"], None, scope=Scope.PAPER_GLOBAL, target_role="PROCESSING"),
            _proposal("P2", LinkDecision.LINK, ["b", "c"], RelationType.SAME_EXPERIMENT),
        ],
    )
    validate(vr)
    result = compile_conditions(vr)
    assert len(result.conditions) == 1
    assert "wavelength" in result.conditions[0].fields  # inherited globally
