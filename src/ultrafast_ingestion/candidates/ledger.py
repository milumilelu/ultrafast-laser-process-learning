"""Phase A passive CandidateLedger builder (CANDIDATE_LEDGER_V0_1.md).

Existing Layer 1-4 pipeline is untouched: this module reads
ScientificDocument + ConditionMention[] + TableRegion[] +
CompileResult (optional) and produces a lossless candidate artifact.

Identity (contract §1.1):

    candidate_id = stable_hash(
        document_version_id,
        source_type.value,
        source_locator,
        normalize_quote(raw_statement),
    )

Invariants enforced: every mention (any acceptance status) maps to
exactly one candidate; unassigned is a lifecycle state, never a
duplicate candidate; table cells get formal candidate ids while
source_ref keeps the legacy "cell:..." key for the Phase B switch.
"""

from __future__ import annotations

from typing import Any

from ultrafast_ingestion.candidates.mapping import mapping_for_cell, mapping_for_mention
from ultrafast_ingestion.candidates.models import (
    DISCOVERY_METHOD_CELL,
    DISCOVERY_METHOD_MENTION,
    DISCOVERY_VERSION,
    LEDGER_PREFIX,
    SCHEMA_VERSION,
    CandidateKind,
    CandidateLedger,
    CandidateMapping,
    CandidateSourceType,
    GroundingStatus,
    MappingStatus,
    PromotionStatus,
    ScientificCandidate,
)
from ultrafast_ingestion.conditions.compiler import CompileResult
from ultrafast_ingestion.mentions.models import AcceptanceStatus, ConditionMention, ContextClass
from ultrafast_ingestion.models.document import PageBlock, ScientificDocument
from ultrafast_ingestion.models.provenance import ProvenanceAnchor, normalize_quote, stable_hash
from ultrafast_ingestion.tables.models import TableCell, TableRegion

_OPEN_LABEL_BY_CONTEXT: dict[ContextClass, str] = {
    ContextClass.EMISSION_WAVELENGTH: "emission/ZPL wavelength",
    ContextClass.EQUIPMENT_MODEL: "equipment model specification",
    ContextClass.CAPABILITY_SPEC: "capability/system specification",
}

_PROMOTION_REASON_BY_STATUS: dict[AcceptanceStatus, str] = {
    AcceptanceStatus.ACCEPTED: "not_linked",
    AcceptanceStatus.AMBIGUOUS_CONTEXT: "ambiguous_context",
    AcceptanceStatus.REJECTED_CONTEXT: "rejected_context",
}


def legacy_cell_key(cell: TableCell) -> str:
    """Legacy graph cell-key format (pre-Phase-B audit anchor, I10 keeps it out of the graph)."""
    return f"cell:{cell.source_block_id}:{cell.source_row}:{cell.parameter}:{cell.value}"


def _mention_locator(mention: ConditionMention) -> str:
    anchor = mention.anchor
    if anchor is None:
        return f"noanchor:{mention.mention_id}"
    return f"{anchor.block_id}:{anchor.char_start}:{anchor.char_end}"


def _cell_locator(cell: TableCell) -> str:
    locator = f"{cell.source_block_id}:row:{cell.source_row}:{cell.parameter}:{cell.value!r}"
    if cell.value2 is not None:
        locator += f":{cell.value2!r}"
    return locator


def _candidate_id(
    document: ScientificDocument,
    source_type: CandidateSourceType,
    locator: str,
    raw_text: str,
) -> str:
    return stable_hash(
        document.document_version_id,
        source_type.value,
        locator,
        normalize_quote(raw_text),
    )


def candidate_id_for_mention(document: ScientificDocument, mention: ConditionMention) -> str:
    """Ledger identity for a CONDITION_MENTION/REJECTED_CONDITION_MENTION candidate (I9)."""
    return _candidate_id(
        document,
        _source_type(mention),
        _mention_locator(mention),
        mention.raw_text,
    )


def candidate_id_for_cell(document: ScientificDocument, cell: TableCell) -> str:
    """Ledger identity for a TABLE_CELL candidate (I9)."""
    return _candidate_id(
        document,
        CandidateSourceType.TABLE_CELL,
        _cell_locator(cell),
        cell.raw_text,
    )


def _concept_label(mention: ConditionMention) -> str:
    if mention.acceptance_status == AcceptanceStatus.REJECTED_CONTEXT:
        return _OPEN_LABEL_BY_CONTEXT.get(mention.context_class, "rejected-context quantity")
    return mention.parameter or "unknown"


def _source_detail(mention: ConditionMention) -> dict[str, Any]:
    return {
        "mention_id": mention.mention_id,
        "parameter": mention.parameter,
        "acceptance_status": mention.acceptance_status.value,
        "context_class": mention.context_class.value,
        "value_type": mention.value_type.value,
        "values": list(mention.values),
        "normalized_unit": mention.normalized_unit,
        "rejection_reason": mention.rejection_reason,
    }


def _source_type(mention: ConditionMention) -> CandidateSourceType:
    if mention.acceptance_status == AcceptanceStatus.REJECTED_CONTEXT:
        return CandidateSourceType.REJECTED_CONDITION_MENTION
    return CandidateSourceType.CONDITION_MENTION


def _promotion_for(
    mention: ConditionMention,
    candidate_id: str,
    promotion_by_candidate: dict[str, tuple[str, str]],
    compiled: bool,
) -> tuple[PromotionStatus, str, str]:
    """(status, reason, ref) per contract §1.3 lifecycle table.

    Phase B: compiler output is keyed by ledger candidate ids.
    """
    if compiled and candidate_id in promotion_by_candidate:
        reason, ref = promotion_by_candidate[candidate_id]
        if ref:
            return PromotionStatus.PROMOTED, reason, ref
        return PromotionStatus.NOT_PROMOTED, reason, ""
    if mention.acceptance_status == AcceptanceStatus.REJECTED_CONTEXT:
        return PromotionStatus.NOT_PROMOTED, "rejected_context", ""
    if mention.acceptance_status == AcceptanceStatus.AMBIGUOUS_CONTEXT:
        return PromotionStatus.NOT_PROMOTED, "ambiguous_context", ""
    if not compiled:
        return PromotionStatus.NOT_PROMOTED, "no_compilation", ""
    return PromotionStatus.NOT_PROMOTED, _PROMOTION_REASON_BY_STATUS[mention.acceptance_status], ""


def _candidate_from_mention(
    document: ScientificDocument,
    mention: ConditionMention,
    promotion: tuple[PromotionStatus, str, str],
) -> ScientificCandidate:
    source_type = _source_type(mention)
    return ScientificCandidate(
        candidate_id=candidate_id_for_mention(document, mention),
        paper_id=document.paper_id,
        document_version_id=document.document_version_id,
        candidate_kind=CandidateKind.QUANTITY,
        concept_label=_concept_label(mention),
        raw_statement=mention.raw_text,
        source_type=source_type,
        source_ref=mention.mention_id,
        source_locator=_mention_locator(mention),
        source_detail=_source_detail(mention),
        provenance_anchors=[mention.anchor] if mention.anchor else [],
        grounding_status=GroundingStatus.GROUNDED,
        promotion_status=promotion[0],
        promotion_reason=promotion[1],
        promotion_ref=promotion[2],
        discovery_method=DISCOVERY_METHOD_MENTION,
        discovery_version=DISCOVERY_VERSION,
    )


def _candidate_from_cell(
    document: ScientificDocument,
    block: PageBlock,
    cell: TableCell,
    region: TableRegion,
) -> ScientificCandidate:
    locator = _cell_locator(cell)
    return ScientificCandidate(
        candidate_id=candidate_id_for_cell(document, cell),
        paper_id=document.paper_id,
        document_version_id=document.document_version_id,
        candidate_kind=CandidateKind.QUANTITY,
        concept_label=cell.parameter,
        raw_statement=cell.raw_text,
        source_type=CandidateSourceType.TABLE_CELL,
        source_ref=legacy_cell_key(cell),
        source_locator=locator,
        source_detail={
            "table_id": region.table_id,
            "semantic_type": region.semantic_type.value,
            "row_kind": region.rows[cell.source_row].kind.value
            if 0 <= cell.source_row < len(region.rows)
            else "",
            "row_index": cell.source_row,
            "value": cell.value,
            "value2": cell.value2,
            "parameter": cell.parameter,
            "unit": cell.unit,
            "legacy_cell_key": legacy_cell_key(cell),
        },
        provenance_anchors=[
            ProvenanceAnchor.build(
                paper_id=document.paper_id,
                document_version_id=document.document_version_id,
                pdf_page_index=block.page_index,
                printed_page_label="",
                bbox=block.bbox,
                text=cell.raw_text,
                section_path=block.section_path,
                block_id=block.block_id(),
            )
        ],
        grounding_status=GroundingStatus.GROUNDED,
        promotion_status=PromotionStatus.NOT_PROMOTED,
        promotion_reason="cell_not_promoted",
        discovery_method=DISCOVERY_METHOD_CELL,
        discovery_version=DISCOVERY_VERSION,
    )


def _counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return counts


def _mapping_for_discovered(candidate: ScientificCandidate) -> CandidateMapping:
    """UNMAPPED placeholder (O4); O7 routing replaces it."""
    from ultrafast_ingestion.candidates.models import NAMESPACE_CONDITION

    return CandidateMapping(
        candidate_id=candidate.candidate_id,
        target_namespace=NAMESPACE_CONDITION,
        target_field=None,
        status=MappingStatus.UNMAPPED,
    )


def build_ledger(
    document: ScientificDocument,
    mentions: list[ConditionMention],
    regions: list[TableRegion],
    compile_result: CompileResult | None = None,
    discovered_candidates: list[ScientificCandidate] | None = None,
) -> CandidateLedger:
    """Build the passive ledger. Layer 1-4 inputs are never modified."""
    blocks_by_id: dict[str, PageBlock] = {}
    for page in document.pages:
        for block in page:
            blocks_by_id[block.block_id()] = block

    promotion_by_candidate: dict[str, tuple[str, str]] = {}
    if compile_result is not None:
        for condition in compile_result.conditions:
            for mid in condition.mention_ids:
                promotion_by_candidate[mid] = ("", condition.condition_id)
        for mid in compile_result.unassigned_mentions:
            promotion_by_candidate[mid] = ("unassigned_after_linking", "")

    compiled = compile_result is not None
    candidates: list[ScientificCandidate] = []
    mappings: list[CandidateMapping] = []
    for mention in mentions:
        cid = candidate_id_for_mention(document, mention)
        candidate = _candidate_from_mention(
            document,
            mention,
            _promotion_for(mention, cid, promotion_by_candidate, compiled),
        )
        candidates.append(candidate)
        mappings.append(mapping_for_mention(candidate, mention))

    cell_count = 0
    seen_cells: set[str] = set()
    for region in regions:
        for row in region.rows:
            for cell in row.cells:
                cell_block = blocks_by_id.get(cell.source_block_id)
                if cell_block is None:
                    continue
                cid = candidate_id_for_cell(document, cell)
                if cid in seen_cells:
                    continue  # same (block,row,param,value) == same node as legacy graph
                seen_cells.add(cid)
                candidate = _candidate_from_cell(document, cell_block, cell, region)
                candidates.append(candidate)
                mappings.append(mapping_for_cell(candidate, cell))
                cell_count += 1

    discovered_count = 0
    if discovered_candidates:
        for candidate in discovered_candidates:
            candidates.append(candidate)
            mappings.append(_mapping_for_discovered(candidate))
            discovered_count += 1

    candidates.sort(key=lambda c: (c.source_type.value, c.source_locator))
    mappings.sort(key=lambda m: m.candidate_id)

    metrics: dict[str, int] = {
        "candidate_count": len(candidates),
        "mention_count": len(mentions),
        "cell_count": cell_count,
        "discovered_count": discovered_count,
        "unassigned_mention_count": len(compile_result.unassigned_mentions) if compile_result is not None else 0,
        "condition_count": len(compile_result.conditions) if compile_result is not None else 0,
    }
    metrics.update(
        {f"source_type_{k}": v for k, v in _counts([c.source_type.value for c in candidates]).items()}
    )
    metrics.update(
        {f"mapping_status_{k}": v for k, v in _counts([m.status.value for m in mappings]).items()}
    )
    metrics.update(
        {f"candidate_kind_{k}": v for k, v in _counts([c.candidate_kind.value for c in candidates]).items()}
    )
    metrics.update(
        {f"promotion_status_{k}": v for k, v in _counts([c.promotion_status.value for c in candidates]).items()}
    )

    return CandidateLedger(
        ledger_version_id=stable_hash(
            LEDGER_PREFIX,
            document.paper_id,
            document.document_version_id,
            SCHEMA_VERSION,
        ),
        paper_id=document.paper_id,
        document_version_id=document.document_version_id,
        candidates=candidates,
        mappings=mappings,
        metrics=metrics,
    )
