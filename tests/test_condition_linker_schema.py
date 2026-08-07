"""Layer 4 unit tests: schema-constrained response parsing (deterministic,
no LLM, no archive)."""

from __future__ import annotations

import pytest

from ultrafast_ingestion.linking.linker import ResponseParseError, build_linker_prompt, parse_response
from ultrafast_ingestion.linking.models import (
    EvidenceStrength,
    LinkDecision,
    LinkProposal,
    RelationType,
)

pytestmark = pytest.mark.unit


def _valid_response() -> str:
    return (
        '{"proposals": ['
        '{"proposal_id": "P01", "decision": "LINK", "mention_ids": ["a", "b"], '
        '"relation": "SAME_EXPERIMENT", "supporting_edge_ids": ["E0"], '
        '"evidence_strength": "EXPLICIT", "rationale": "same laser inscription"}]}'
    )


def test_parse_valid_response() -> None:
    proposals = parse_response(_valid_response())
    assert len(proposals) == 1
    p = proposals[0]
    assert p.decision == LinkDecision.LINK
    assert p.relation == RelationType.SAME_EXPERIMENT
    assert p.evidence_strength == EvidenceStrength.EXPLICIT
    assert p.mention_ids == ("a", "b")


def test_unknown_relation_rejected() -> None:
    raw = _valid_response().replace("SAME_EXPERIMENT", "BEST_FRIENDS")
    with pytest.raises(ResponseParseError, match="unknown relation"):
        parse_response(raw)


def test_unknown_decision_rejected() -> None:
    raw = _valid_response().replace('"LINK"', '"GUESS"')
    with pytest.raises(ResponseParseError, match="unknown decision"):
        parse_response(raw)


def test_numeric_value_generation_rejected() -> None:
    raw = _valid_response().replace(
        '"rationale": "same laser inscription"',
        '"rationale": "x", "value": 1030',
    )
    with pytest.raises(ResponseParseError, match="numeric fields"):
        parse_response(raw)


def test_missing_supporting_edges_rejected() -> None:
    raw = _valid_response().replace(
        '"supporting_edge_ids": ["E0"], ',
        "",
    )
    with pytest.raises(ResponseParseError, match="missing supporting_edge_ids"):
        parse_response(raw)


def test_abstain_accepted() -> None:
    raw = (
        '{"proposals": [{"proposal_id": "P9", "decision": "ABSTAIN", '
        '"mention_ids": ["a", "b"], "supporting_edge_ids": [], '
        '"rationale": "source text does not establish linkage"}]}'
    )
    proposals = parse_response(raw)
    assert proposals[0].decision == LinkDecision.ABSTAIN


def test_prompt_includes_graph_edges_and_mentions() -> None:
    from ultrafast_ingestion.graph.models import (
        CandidateEdge,
        CandidateGraph,
        EdgeStrength,
        EdgeType,
        MentionRole,
    )
    from ultrafast_ingestion.mentions.models import AcceptanceStatus, ConditionMention, ContextClass
    from ultrafast_ingestion.models.provenance import ProvenanceAnchor

    anchor = ProvenanceAnchor(paper_id="p", document_version_id="d", pdf_page_index=0)
    m1 = ConditionMention(
        mention_id="a", parameter="wavelength", raw_text="515 nm", values=[515.0],
        value_type="SCALAR", normalized_unit="nm", context_class=ContextClass.PROCESS_CONTEXT,
        acceptance_status=AcceptanceStatus.ACCEPTED, anchor=anchor,
    )
    m2 = ConditionMention(
        mention_id="b", parameter="frequency", raw_text="200 kHz", values=[200.0],
        value_type="SCALAR", normalized_unit="kHz", context_class=ContextClass.PROCESS_CONTEXT,
        acceptance_status=AcceptanceStatus.ACCEPTED, anchor=anchor,
    )
    graph = CandidateGraph()
    graph.add_mention(m1, MentionRole.PROCESSING)
    graph.add_mention(m2, MentionRole.PROCESSING)
    graph.add_edge(
        CandidateEdge("a", "b", EdgeType.SAME_PARAMETER_GROUP, "SAME_BLOCK_PARAMETER_GROUP", EdgeStrength.WEAK)
    )
    prompt = build_linker_prompt(graph)
    assert "M a: parameter=wavelength" in prompt
    assert "M b: parameter=frequency" in prompt
    assert "E 0: SAME_PARAMETER_GROUP" in prompt
    assert "SAME_EXPERIMENT | SEPARATE_EXPERIMENT" in prompt  # schema contract visible
