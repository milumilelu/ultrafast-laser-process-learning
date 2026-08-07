"""CandidateLedger V0.1 (Phase A passive ledger + Phase B consumption hub).

Contract: docs/contracts/CANDIDATE_LEDGER_V0_1.md.
"""

from __future__ import annotations

from ultrafast_ingestion.candidates.ledger import (
    build_ledger,
    candidate_id_for_cell,
    candidate_id_for_mention,
    legacy_cell_key,
)
from ultrafast_ingestion.candidates.mapping import mapping_for_cell, mapping_for_mention
from ultrafast_ingestion.candidates.models import (
    SCHEMA_VERSION,
    CandidateKind,
    CandidateLedger,
    CandidateMapping,
    CandidateSourceType,
    GroundingStatus,
    MappingStatus,
    PromotionStatus,
    ScientificCandidate,
    VerificationStatus,
)
from ultrafast_ingestion.candidates.view import (
    EDGE_ELIGIBLE_TABLE_TYPES,
    ConditionLinkView,
    TableCellNode,
)

__all__ = [
    "EDGE_ELIGIBLE_TABLE_TYPES",
    "SCHEMA_VERSION",
    "CandidateKind",
    "CandidateLedger",
    "CandidateMapping",
    "CandidateSourceType",
    "ConditionLinkView",
    "GroundingStatus",
    "MappingStatus",
    "PromotionStatus",
    "ScientificCandidate",
    "TableCellNode",
    "VerificationStatus",
    "build_ledger",
    "candidate_id_for_cell",
    "candidate_id_for_mention",
    "legacy_cell_key",
    "mapping_for_cell",
    "mapping_for_mention",
]
