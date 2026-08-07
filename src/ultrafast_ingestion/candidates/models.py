"""CandidateLedger V0.1 models (Phase A passive ledger).

Contract: docs/contracts/CANDIDATE_LEDGER_V0_1.md.

Invariant: to_canonical_dict() is the ONLY canonical serialization
(stable hash + artifact persistence). model_dump() is an implementation
utility, not a repository contract.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ultrafast_ingestion.models.provenance import ProvenanceAnchor

SCHEMA_VERSION = "candidate-ledger-v0.1"
DISCOVERY_METHOD_MENTION = "condition-mention-extractor"
DISCOVERY_METHOD_CELL = "table-cell-parser"
DISCOVERY_VERSION = "v0.1"
NAMESPACE_CONDITION = "experimental_condition"

LEDGER_PREFIX = "candidate-ledger"


class CandidateKind(StrEnum):
    """Routing taxonomy only - never a knowledge ontology.

    No *_UNKNOWN variants: unknown is a mapping-state concept, not a
    scientific object type (see CANDIDATE_LEDGER_V0_1.md §3.1).
    """

    QUANTITY = "QUANTITY"
    PROCEDURE = "PROCEDURE"
    PARAMETER_EFFECT = "PARAMETER_EFFECT"
    MATERIAL_PROPERTY = "MATERIAL_PROPERTY"
    MECHANISM = "MECHANISM"
    OUTCOME = "OUTCOME"
    CONSTRAINT = "CONSTRAINT"
    COMPARISON = "COMPARISON"
    MEASUREMENT = "MEASUREMENT"
    OTHER = "OTHER"


class CandidateSourceType(StrEnum):
    """Origin of the candidate (where it came from), NOT lifecycle state.

    Unassigned is a promotion outcome, never a source: the same
    CONDITION_MENTION candidate may later be assigned or unassigned.
    """

    CONDITION_MENTION = "CONDITION_MENTION"
    TABLE_CELL = "TABLE_CELL"
    REJECTED_CONDITION_MENTION = "REJECTED_CONDITION_MENTION"
    LLM_DISCOVERY = "LLM_DISCOVERY"  # V0.2
    HUMAN = "HUMAN"  # V0.2


class MappingStatus(StrEnum):
    MAPPED = "MAPPED"
    UNMAPPED = "UNMAPPED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class GroundingStatus(StrEnum):
    GROUNDED = "GROUNDED"
    GROUNDING_UNRESOLVED = "GROUNDING_UNRESOLVED"
    NOT_RUN = "NOT_RUN"


class VerificationStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT = "INSUFFICIENT"


class PromotionStatus(StrEnum):
    PROMOTED = "PROMOTED"
    NOT_PROMOTED = "NOT_PROMOTED"
    BLOCKED = "BLOCKED"


class ScientificCandidate(BaseModel):
    """A discovered piece of information - never a confirmed scientific fact."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    paper_id: str
    document_version_id: str

    candidate_kind: CandidateKind
    concept_label: str
    raw_statement: str
    raw_value: str | None = None  # V0.1 deterministic path: None (values live in source_detail)
    raw_unit: str | None = None  # V0.1 deterministic path: None

    source_type: CandidateSourceType
    source_ref: str = ""  # mention_id / legacy cell key (Phase B audit)
    source_locator: str
    source_detail: dict[str, Any] = Field(default_factory=dict)

    provenance_anchors: list[ProvenanceAnchor] = Field(default_factory=list)
    grounding_status: GroundingStatus = GroundingStatus.GROUNDED
    verification_status: VerificationStatus = VerificationStatus.NOT_RUN
    promotion_status: PromotionStatus = PromotionStatus.NOT_PROMOTED
    promotion_reason: str = ""
    promotion_ref: str = ""  # condition_id etc.

    discovery_method: str = ""
    discovery_version: str = ""

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_canonical_dict(cls, data: dict[str, Any]) -> ScientificCandidate:
        return cls.model_validate(data)


class CandidateMapping(BaseModel):
    """Mapping target decision - kept separate from the candidate itself."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    target_namespace: str  # V0.1: NAMESPACE_CONDITION only
    target_field: str | None = None  # parameter id
    status: MappingStatus = MappingStatus.UNMAPPED

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_canonical_dict(cls, data: dict[str, Any]) -> CandidateMapping:
        return cls.model_validate(data)


class CandidateLedger(BaseModel):
    """Passive aggregate artifact (Phase A)."""

    ledger_version_id: str
    paper_id: str
    document_version_id: str
    schema_version: str = SCHEMA_VERSION
    candidates: list[ScientificCandidate] = Field(default_factory=list)
    mappings: list[CandidateMapping] = Field(default_factory=list)
    metrics: dict[str, int] = Field(default_factory=dict)

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def write_artifact(self, out_dir: Path) -> Path:
        target = out_dir / self.paper_id
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{self.ledger_version_id}.json"
        payload = json.dumps(
            self.to_canonical_dict(),
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        )
        path.write_text(payload, encoding="utf-8")
        return path

    def for_condition_linking(self, document: Any, regions: list[Any]) -> Any:
        """Routing view for the condition graph/linker (CANDIDATE_LEDGER_V0_1 §8.2)."""
        from ultrafast_ingestion.candidates.view import ConditionLinkView

        return ConditionLinkView.from_ledger(self, document, regions)

    @classmethod
    def from_canonical_dict(cls, data: dict[str, Any]) -> CandidateLedger:
        return cls.model_validate(data)
