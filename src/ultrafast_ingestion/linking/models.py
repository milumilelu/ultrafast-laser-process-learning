"""Layer 4 linking models: schema-constrained LLM proposals.

LLM decides only LINK / SEPARATE / ASSIGN_SCOPE / ABSTAIN at relation
level. No condition_id, no numeric values, no confidence floats.
Rationale is for humans only - the validator never reads it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LinkDecision(StrEnum):
    LINK = "LINK"
    SEPARATE = "SEPARATE"
    ASSIGN_SCOPE = "ASSIGN_SCOPE"
    ABSTAIN = "ABSTAIN"


class EvidenceStrength(StrEnum):
    EXPLICIT = "EXPLICIT"
    STRUCTURALLY_SUPPORTED = "STRUCTURALLY_SUPPORTED"
    SEMANTICALLY_INFERRED = "SEMANTICALLY_INFERRED"


class RelationType(StrEnum):
    SAME_EXPERIMENT = "SAME_EXPERIMENT"
    SEPARATE_EXPERIMENT = "SEPARATE_EXPERIMENT"
    GLOBAL_SCOPE = "GLOBAL_SCOPE"
    COMPARISON_ONLY = "COMPARISON_ONLY"
    MEASUREMENT_ONLY = "MEASUREMENT_ONLY"
    MUTUALLY_EXCLUSIVE = "MUTUALLY_EXCLUSIVE"


class Scope(StrEnum):
    PAPER_GLOBAL = "PAPER_GLOBAL"
    EXPERIMENT_GROUP = "EXPERIMENT_GROUP"
    TABLE_GLOBAL = "TABLE_GLOBAL"
    ROW_LOCAL = "ROW_LOCAL"
    PARAGRAPH_LOCAL = "PARAGRAPH_LOCAL"


class ConditionRole(StrEnum):
    PROCESSING = "PROCESSING"
    MEASUREMENT = "MEASUREMENT"
    COMPARISON = "COMPARISON"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class LinkProposal:
    proposal_id: str
    decision: LinkDecision
    mention_ids: tuple[str, ...]          # 2 for LINK/SEPARATE; 1 for ASSIGN_SCOPE
    relation: RelationType | None = None
    scope: Scope | None = None
    applies_to: tuple[str, ...] = ()      # ASSIGN_SCOPE: mention ids or ("*processing",)
    target_role: ConditionRole | None = None
    supporting_edge_ids: tuple[str, ...] = ()
    evidence_strength: EvidenceStrength = EvidenceStrength.SEMANTICALLY_INFERRED
    rationale: str = ""                   # human-readable only; never validated

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "decision": str(self.decision),
            "mention_ids": list(self.mention_ids),
            "relation": str(self.relation) if self.relation else None,
            "scope": str(self.scope) if self.scope else None,
            "applies_to": list(self.applies_to),
            "target_role": str(self.target_role) if self.target_role else None,
            "supporting_edge_ids": list(self.supporting_edge_ids),
            "evidence_strength": str(self.evidence_strength),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LinkProposal:
        return cls(
            proposal_id=str(data["proposal_id"]),
            decision=LinkDecision(str(data["decision"])),
            mention_ids=tuple(str(x) for x in data.get("mention_ids") or ()),
            relation=RelationType(str(data["relation"])) if data.get("relation") else None,
            scope=Scope(str(data["scope"])) if data.get("scope") else None,
            applies_to=tuple(str(x) for x in data.get("applies_to") or ()),
            target_role=ConditionRole(str(data["target_role"])) if data.get("target_role") else None,
            supporting_edge_ids=tuple(str(x) for x in data.get("supporting_edge_ids") or ()),
            evidence_strength=EvidenceStrength(str(data.get("evidence_strength") or "SEMANTICALLY_INFERRED")),
            rationale=str(data.get("rationale") or ""),
        )


@dataclass(slots=True)
class LinkingResult:
    paper_id: str
    document_version_id: str
    prompt_version: str
    schema_version: str
    graph_version: str
    model_name: str = ""
    model_parameters: dict[str, Any] = field(default_factory=dict)
    proposals: list[LinkProposal] = field(default_factory=list)
    abstentions: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "document_version_id": self.document_version_id,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "graph_version": self.graph_version,
            "model_name": self.model_name,
            "model_parameters": dict(self.model_parameters),
            "proposals": [p.to_dict() for p in self.proposals],
            "abstentions": list(self.abstentions),
            "warnings": list(self.warnings),
        }
