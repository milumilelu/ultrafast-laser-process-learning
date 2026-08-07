"""ConditionLinkView — routing view over CandidateLedger (CANDIDATE_LEDGER_V0_1 §8.2).

Routing, never deletion (I11): the ledger keeps every candidate; this view
decides what the condition graph/linker may consume.

- mentions: ALL CONDITION_MENTION candidates (rejected included — they are
  registered as REJECTED-role nodes with zero edges, matching pre-Phase-B
  node-set semantics); eligible (MAPPED/AMBIGUOUS) ids exposed separately.
- cell_nodes: cells of KEY_VALUE_SETUP / EXPERIMENT_ROWS / COMPARISON_TABLE
  regions only — the exact R1-R4 edge sources of the legacy builder.
  FACTOR_LEVELS / RESULT_MATRIX / MIXED / UNKNOWN cells stay in the ledger.
- Identity (I9/I10): every node id is a ledger candidate id; cell ids are
  computed by the ledger identity function and verified to exist in the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from ultrafast_ingestion.candidates.ledger import candidate_id_for_cell
from ultrafast_ingestion.candidates.models import (
    CandidateLedger,
    CandidateSourceType,
    MappingStatus,
    ScientificCandidate,
)
from ultrafast_ingestion.mentions.models import (
    AcceptanceStatus,
    ConditionMention,
    ContextClass,
    MentionValueType,
)
from ultrafast_ingestion.models.document import ScientificDocument
from ultrafast_ingestion.models.provenance import ProvenanceAnchor
from ultrafast_ingestion.tables.models import (
    RowKind,
    TableCell,
    TableRegion,
    TableSemanticType,
)

EDGE_ELIGIBLE_TABLE_TYPES: frozenset[TableSemanticType] = frozenset(
    {
        TableSemanticType.KEY_VALUE_SETUP,
        TableSemanticType.EXPERIMENT_ROWS,
        TableSemanticType.COMPARISON_TABLE,
    }
)

_ROUTING_STATUSES = (MappingStatus.MAPPED, MappingStatus.AMBIGUOUS)

_VIEW_MENTION_SOURCES = frozenset(
    {
        CandidateSourceType.CONDITION_MENTION,
        CandidateSourceType.REJECTED_CONDITION_MENTION,
    }
)


@dataclass(frozen=True, slots=True)
class TableCellNode:
    candidate_id: str
    cell: TableCell
    region: TableRegion
    row_kind: RowKind


class ConditionLinkView(BaseModel):
    """Eligible candidate routing for the condition graph/linker."""

    model_config = ConfigDict(frozen=True)

    paper_id: str
    document_version_id: str
    ledger_version_id: str
    mentions: dict[str, ConditionMention] = Field(default_factory=dict)
    eligible_mention_ids: tuple[str, ...] = ()
    cell_nodes: dict[str, TableCellNode] = Field(default_factory=dict)
    regions: list[TableRegion] = Field(default_factory=list)

    @classmethod
    def from_ledger(
        cls,
        ledger: CandidateLedger,
        document: ScientificDocument,
        regions: list[TableRegion],
    ) -> ConditionLinkView:
        if ledger.paper_id != document.paper_id:
            raise ValueError("ledger/document paper_id mismatch")
        by_id = {c.candidate_id: c for c in ledger.candidates}
        mapping_status = {m.candidate_id: m.status for m in ledger.mappings}

        mentions: dict[str, ConditionMention] = {}
        eligible: list[str] = []
        for candidate in ledger.candidates:
            if candidate.source_type not in _VIEW_MENTION_SOURCES:
                continue
            restored = _restore_mention(candidate)
            mentions[candidate.candidate_id] = restored
            if mapping_status.get(candidate.candidate_id) in _ROUTING_STATUSES:
                eligible.append(candidate.candidate_id)

        cell_nodes: dict[str, TableCellNode] = {}
        for region in regions:
            if region.semantic_type not in EDGE_ELIGIBLE_TABLE_TYPES:
                continue
            for row in region.rows:
                for cell in row.cells:
                    cid = candidate_id_for_cell(document, cell)
                    existing = by_id.get(cid)
                    if existing is None or existing.source_type != CandidateSourceType.TABLE_CELL:
                        raise ValueError(
                            f"cell candidate {cid} not in ledger - ledger/regions mismatch (I9/I10)"
                        )
                    cell_nodes[cid] = TableCellNode(
                        candidate_id=cid,
                        cell=cell,
                        region=region,
                        row_kind=row.kind,
                    )

        return cls(
            paper_id=ledger.paper_id,
            document_version_id=ledger.document_version_id,
            ledger_version_id=ledger.ledger_version_id,
            mentions=mentions,
            eligible_mention_ids=tuple(eligible),
            cell_nodes=cell_nodes,
            regions=list(regions),
        )


def _restore_mention(candidate: ScientificCandidate) -> ConditionMention:
    detail = candidate.source_detail
    anchor = None
    if candidate.provenance_anchors:
        anchor = ProvenanceAnchor.from_dict(candidate.provenance_anchors[0].to_dict())
    return ConditionMention(
        mention_id=str(detail["mention_id"]),
        parameter=str(detail["parameter"]),
        raw_text=candidate.raw_statement,
        values=[float(v) for v in detail["values"]],
        value_type=MentionValueType(detail["value_type"]),
        normalized_unit=str(detail["normalized_unit"]),
        context_class=ContextClass(detail["context_class"]),
        acceptance_status=AcceptanceStatus(detail["acceptance_status"]),
        rejection_reason=str(detail.get("rejection_reason", "")),
        anchor=anchor,
    )
