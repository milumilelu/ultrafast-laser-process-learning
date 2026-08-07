"""CandidateMapping derivation rules (CANDIDATE_LEDGER_V0_1.md §1.4/§2.2).

V0.1: exactly one mapping per candidate, target_namespace is always
NAMESPACE_CONDITION. Mapping status is decided by the deterministic
acceptance_status; rejected mentions map to NOT_APPLICABLE for the
condition target while their open concept survives via concept_label.
"""

from __future__ import annotations

from ultrafast_ingestion.candidates.models import (
    NAMESPACE_CONDITION,
    CandidateMapping,
    MappingStatus,
    ScientificCandidate,
)
from ultrafast_ingestion.mentions.models import AcceptanceStatus, ConditionMention
from ultrafast_ingestion.tables.models import TableCell

_STATUS_BY_ACCEPTANCE = {
    AcceptanceStatus.ACCEPTED: MappingStatus.MAPPED,
    AcceptanceStatus.AMBIGUOUS_CONTEXT: MappingStatus.AMBIGUOUS,
    AcceptanceStatus.REJECTED_CONTEXT: MappingStatus.NOT_APPLICABLE,
}


def mapping_for_mention(
    candidate: ScientificCandidate,
    mention: ConditionMention,
) -> CandidateMapping:
    status = _STATUS_BY_ACCEPTANCE[mention.acceptance_status]
    target_field = mention.parameter if status in (MappingStatus.MAPPED, MappingStatus.AMBIGUOUS) else None
    return CandidateMapping(
        candidate_id=candidate.candidate_id,
        target_namespace=NAMESPACE_CONDITION,
        target_field=target_field,
        status=status,
    )


def mapping_for_cell(
    candidate: ScientificCandidate,
    cell: TableCell,
) -> CandidateMapping:
    return CandidateMapping(
        candidate_id=candidate.candidate_id,
        target_namespace=NAMESPACE_CONDITION,
        target_field=cell.parameter,
        status=MappingStatus.MAPPED,
    )
