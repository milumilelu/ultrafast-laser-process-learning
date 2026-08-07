"""Open Scientific Discovery V0.1 models (O1: windows + skeleton).

Contract: docs/contracts/OPEN_SCIENTIFIC_DISCOVERY_V0_1.md (FROZEN).

O1 scope: DiscoveryWindowConfig / DiscoveryWindow / CandidateSkeleton only.
GroundingMatchType / GroundingResult / CandidateDetail / CandidateVerification
are added at O3/O4/O6 (contract §5/§6/§8 reserve their schemas).
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ultrafast_ingestion.candidates.models import (
    CandidateKind,
    GroundingStatus,
    VerificationStatus,
)
from ultrafast_ingestion.models.provenance import ProvenanceAnchor, stable_hash

WINDOW_CONFIG_VERSION = "v0.1"


class DiscoveryWindowConfig(BaseModel):
    """Token budgets are implementation defaults, not scientific constants (D6)."""

    target_window_tokens: int = 800
    max_window_tokens: int = 1200
    target_batch_tokens: int = 2000  # O2 skeleton batch
    max_batch_tokens: int = 2500  # O2 skeleton batch
    context_tokens: int = 300

    def config_version(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return f"{WINDOW_CONFIG_VERSION}:{stable_hash(payload)}"

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class DiscoveryWindow(BaseModel):
    """Structure-aware discovery unit (contract §2)."""

    model_config = ConfigDict(frozen=True)

    window_id: str
    paper_id: str
    document_version_id: str
    window_config_version: str
    section_path: str
    block_ids: tuple[str, ...] = Field(default_factory=tuple)
    page_range: tuple[int, int]
    text: str
    table_refs: tuple[str, ...] = Field(default_factory=tuple)
    caption_refs: tuple[str, ...] = Field(default_factory=tuple)
    preceding_context: str = ""
    following_context: str = ""
    routing_hint: str = "general"

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class GroundingMatchType(StrEnum):
    """How the verbatim quote was located (O3, contract §5).

    Recorded permanently - fuzzy grounding can never masquerade as exact (D7).
    """

    EXACT = "EXACT"
    NORMALIZED_EXACT = "NORMALIZED_EXACT"
    CROSS_BLOCK_EXACT = "CROSS_BLOCK_EXACT"
    FUZZY_UNIQUE = "FUZZY_UNIQUE"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


class GroundingConfig(BaseModel):
    """O3 parameters. fuzzy threshold is a pilot-calibrated default, NOT a
    frozen contract value (contract §5: measure false alignment vs unresolved
    before freezing)."""

    fuzzy_token_coverage: float = 0.85

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class GroundingResult(BaseModel):
    """Deterministic grounding output (contract §5).

    Pipeline: CandidateSkeleton -> GroundingResult -> ScientificCandidate.
    """

    model_config = ConfigDict(frozen=True)

    skeleton_id: str
    match_type: GroundingMatchType
    anchor: ProvenanceAnchor | None = None
    matched_quote: str = ""
    status: GroundingStatus
    detail: dict[str, Any] = Field(default_factory=dict)

    def gate(self) -> str:
        """O3 gate: PASS / CONDITIONAL / FAIL (contract §5)."""
        if self.match_type in (
            GroundingMatchType.EXACT,
            GroundingMatchType.NORMALIZED_EXACT,
            GroundingMatchType.CROSS_BLOCK_EXACT,
        ):
            return "PASS"
        if self.match_type == GroundingMatchType.FUZZY_UNIQUE:
            return "CONDITIONAL"
        return "FAIL"

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class DiscoveryBatch(BaseModel):
    """Skeleton batch: several windows aggregated for one LLM call (contract §2).

    Windows are numbered w0..wn inside the batch; the model must reference
    window_local_ref (never an id across unrelated windows).
    """

    model_config = ConfigDict(frozen=True)

    batch_id: str
    paper_id: str
    document_version_id: str
    window_config_version: str
    window_refs: tuple[str, ...] = Field(default_factory=tuple)
    window_ids: tuple[str, ...] = Field(default_factory=tuple)
    text: str

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SourceSemantics(StrEnum):
    REPORTED = "REPORTED"
    DERIVED = "DERIVED"
    CITED = "CITED"
    INTERPRETIVE = "INTERPRETIVE"
    UNKNOWN = "UNKNOWN"


class CandidateDetail(BaseModel):
    """Candidate Fill output (O4, contract §6). ALL fields optional -
    partial candidates beat invented complete ones."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_surface: str | None = None
    predicate_surface: str | None = None
    object_surface: str | None = None
    raw_value: str | None = None
    raw_unit: str | None = None
    qualifier: str | None = None
    scope_hint: str | None = None
    source_semantics: SourceSemantics = SourceSemantics.UNKNOWN

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class CandidateVerification(BaseModel):
    """Independent verification output (O6, contract §8).

    Field grid per CANDIDATE_LEDGER_V0_1 §2.5 (reserved -> now implemented).
    Verifier never sees the proposer's reasoning - only source + candidate.
    """

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    verification_status: VerificationStatus
    verifier: str = ""
    verification_version: str = ""
    supporting_provenance: list[ProvenanceAnchor] = Field(default_factory=list)
    basis: str = ""

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class CandidateSkeleton(BaseModel):
    """Discovery pass output DTO. Never enters the ledger directly (D1/D2).

    Frozen schema (G8): the model returns exactly these fields; everything
    else (paper_id / window_id / block_id / candidate_id) is bound by code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    local_id: str
    candidate_kind: CandidateKind
    concept_label: str
    verbatim_quote: str
    window_local_ref: str = ""

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
