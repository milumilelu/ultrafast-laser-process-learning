"""Validated relation graph + ExperimentalConditionSpec (Layer 4 step 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ultrafast_ingestion.graph.models import CandidateGraph
from ultrafast_ingestion.linking.models import (
    ConditionRole,
    LinkDecision,
    LinkProposal,
    Scope,
)


class ValidationErrorCode(StrEnum):
    UNKNOWN_MENTION = "UNKNOWN_MENTION"
    UNKNOWN_EDGE = "UNKNOWN_EDGE"
    REJECTED_MENTION_IN_CONDITION = "REJECTED_MENTION_IN_CONDITION"
    CONTRADICTS_HARD_STRUCTURAL_CONSTRAINT = "CONTRADICTS_HARD_STRUCTURAL_CONSTRAINT"
    COMPARISON_POLLUTION = "COMPARISON_POLLUTION"
    MEASUREMENT_POLLUTION = "MEASUREMENT_POLLUTION"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    UNGROUNDED_VALUE_GENERATION = "UNGROUNDED_VALUE_GENERATION"
    UNKNOWN_RELATION_FOR_DECISION = "UNKNOWN_RELATION_FOR_DECISION"


class FieldStatus(StrEnum):
    REPORTED_CLEAR = "REPORTED_CLEAR"
    CONFLICT_PRESERVED = "CONFLICT_PRESERVED"
    LINKAGE_AMBIGUOUS = "LINKAGE_AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class ValidationRejection:
    proposal_id: str
    error_code: ValidationErrorCode
    detail: str = ""


@dataclass(slots=True)
class ConditionField:
    parameter: str
    status: FieldStatus
    values: list[float]
    unit: str
    provenance_anchor_ids: list[str] = field(default_factory=list)
    evidence_strength: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "status": str(self.status),
            "values": list(self.values),
            "unit": self.unit,
            "provenance_anchor_ids": list(self.provenance_anchor_ids),
            "evidence_strength": self.evidence_strength,
        }


@dataclass(slots=True)
class ExperimentalConditionSpec:
    condition_id: str
    paper_id: str
    role: ConditionRole
    scope: Scope
    mention_ids: list[str] = field(default_factory=list)
    fields: dict[str, ConditionField] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "paper_id": self.paper_id,
            "role": str(self.role),
            "scope": str(self.scope),
            "mention_ids": list(self.mention_ids),
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
        }


@dataclass(slots=True)
class ValidatedRelationGraph:
    graph: CandidateGraph
    accepted: list[LinkProposal] = field(default_factory=list)
    rejected: list[ValidationRejection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def accepted_decisions(self) -> list[LinkProposal]:
        return [p for p in self.accepted if p.decision != LinkDecision.ABSTAIN]
