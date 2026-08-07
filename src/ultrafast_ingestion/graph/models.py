"""StructuralCandidateGraph models (Layer 3, step 2).

Edges are CANDIDATES with provenance — never promoted to facts here.
LLM linking (Layer 4) consumes this graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ultrafast_ingestion.mentions.models import ConditionMention


class EdgeType(StrEnum):
    SAME_EXPERIMENT_CANDIDATE = "SAME_EXPERIMENT_CANDIDATE"
    SAME_TABLE_ROW = "SAME_TABLE_ROW"
    SAME_PARAMETER_GROUP = "SAME_PARAMETER_GROUP"
    GLOBAL_SCOPE_CANDIDATE = "GLOBAL_SCOPE_CANDIDATE"
    MUTUALLY_EXCLUSIVE = "MUTUALLY_EXCLUSIVE"
    COMPARISON_ONLY = "COMPARISON_ONLY"
    MEASUREMENT_ONLY = "MEASUREMENT_ONLY"
    UNKNOWN_RELATION = "UNKNOWN_RELATION"


class EdgeStrength(StrEnum):
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    WEAK = "WEAK"


class MentionRole(StrEnum):
    PROCESSING = "PROCESSING"
    MEASUREMENT = "MEASUREMENT"
    REJECTED = "REJECTED"
    UNCLEAR = "UNCLEAR"


@dataclass(frozen=True, slots=True)
class CandidateEdge:
    source_mention_id: str
    target_mention_id: str
    type: EdgeType
    source_rule: str
    edge_strength: EdgeStrength
    source_block_ids: tuple[str, ...] = ()
    source_table_id: str = ""
    source_row: int | None = None
    source_quote: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_mention_id": self.source_mention_id,
            "target_mention_id": self.target_mention_id,
            "type": str(self.type),
            "source_rule": self.source_rule,
            "edge_strength": str(self.edge_strength),
            "source_block_ids": list(self.source_block_ids),
            "source_table_id": self.source_table_id,
            "source_row": self.source_row,
            "source_quote": self.source_quote,
        }


@dataclass(slots=True)
class CandidateGraph:
    """Identity-agnostic candidate registry.

    Node keys are supplied by the caller (Phase B: ledger candidate ids).
    Values are ConditionMention carriers; mention_id stays the lineage
    anchor inside the object.
    """

    mentions: dict[str, ConditionMention] = field(default_factory=dict)
    edges: list[CandidateEdge] = field(default_factory=list)
    roles: dict[str, MentionRole] = field(default_factory=dict)

    def add_mention(self, node_id: str, mention: ConditionMention, role: MentionRole) -> None:
        self.mentions[node_id] = mention
        self.roles[node_id] = role

    def add_edge(self, edge: CandidateEdge) -> None:
        if edge.source_mention_id == edge.target_mention_id:
            return
        for existing in self.edges:
            if (
                existing.source_mention_id == edge.source_mention_id
                and existing.target_mention_id == edge.target_mention_id
                and existing.type == edge.type
                and existing.source_rule == edge.source_rule
            ):
                return
        self.edges.append(edge)

    def edges_between(self, a: str, b: str) -> list[CandidateEdge]:
        return [
            e
            for e in self.edges
            if {e.source_mention_id, e.target_mention_id} == {a, b}
        ]

    def has_edge(self, a: str, b: str, edge_type: EdgeType) -> bool:
        return any(e.type == edge_type for e in self.edges_between(a, b))

    def edges_of_type(self, edge_type: EdgeType) -> list[CandidateEdge]:
        return [e for e in self.edges if e.type == edge_type]

    def synthetic_edge_violations(self, forbidden: list[tuple[str, str, EdgeType]]) -> int:
        """Edges of a forbidden kind between mentions the reference forbids
        to connect (hard gate for Layer 4 entry)."""
        count = 0
        for e in self.edges:
            for a, b, etype in forbidden:
                if e.type == etype and {e.source_mention_id, e.target_mention_id} == {a, b}:
                    count += 1
        return count
