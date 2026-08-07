"""Structural candidate graph builder (Layer 3, step 2) — ledger-backed.

Phase B (CANDIDATE_LEDGER_V0_1 §8): input is a ConditionLinkView routed
from the CandidateLedger. All node identities are ledger candidate ids
(I9/I10); the view is routing, never deletion (I11).

Rules (semantics identical to the pre-Phase-B builder):
  R1 KEY_VALUE_SETUP table        -> all cells: SAME_EXPERIMENT_CANDIDATE
  R2 EXPERIMENT_ROWS table        -> same-row cells: SAME_EXPERIMENT_CANDIDATE
  R3 COMPARISON_TABLE this-work   -> same-row cells: SAME_EXPERIMENT_CANDIDATE
  R4 COMPARISON_TABLE reference   -> same-row cells: COMPARISON_ONLY
  R5 prose parameter group        -> mentions in same block (accepted,
                                     non-capability): SAME_PARAMETER_GROUP
  R6 explicit global statement    -> GLOBAL_SCOPE_CANDIDATE links to the
                                     nearest preceding processing block
  R7 processing vs measurement    -> same-parameter: MUTUALLY_EXCLUSIVE
  R8 measurement role             -> MEASUREMENT_ONLY among themselves

REJECTED mentions never produce edges. Capability-spec (AMBIGUOUS)
mentions never produce SAME_PARAMETER_GROUP edges.
"""

from __future__ import annotations

from ultrafast_ingestion.candidates.view import ConditionLinkView
from ultrafast_ingestion.graph.models import (
    CandidateEdge,
    CandidateGraph,
    EdgeStrength,
    EdgeType,
    MentionRole,
)
from ultrafast_ingestion.mentions.models import AcceptanceStatus, ConditionMention, ContextClass
from ultrafast_ingestion.models.document import ScientificDocument
from ultrafast_ingestion.tables.models import (
    RowKind,
    TableSemanticType,
)

PROCESSING_KEYWORDS = (
    "writing", "inscription", "ablation", "machining", "texturing", "processing",
    "slicing", "irradiat", "photoablation", "photo-ablation", "drilling", "scribing",
    "micromachining", "cleaving",
)
MEASUREMENT_KEYWORDS = (
    "lifetime", "measurement", "supercontinuum", "whitelase", "correlator",
    "time-resolved", "decay", "excite", "fluorescence", "microscope", "dichroic",
    "spectrometer", "apd", "snspd", "camera", "odmr", "spin", "rabi", "ramsey",
    "spin echo", "imaging", "spectroscopy", "raman", "confocal", "photon counting",
    "excitation", "detector",
)
GLOBAL_PHRASES = (
    "throughout the experiments", "in all experiments", "for all experiments",
    "same method described in the previous section", "same method as described",
    "same experimental setup", "in all cases", "was used for all",
)

MUTUALLY_EXCLUSIVE_PARAMS = {
    "frequency", "wavelength", "pulse_width", "pulse_energy", "average_power",
    "fluence", "scan_speed", "spot_size", "depth", "pitch", "accumulated_dose",
}

WINDOW_CHARS = 120


def _mention_window(
    page,
    idx: int,
    block,
    raw_start: int,
    raw_end: int,
) -> str:
    prev_tail = page[idx - 1].text[-140:] if idx > 0 else ""
    next_head = page[idx + 1].text[:140] if idx + 1 < len(page) else ""
    context = prev_tail + block.text + next_head
    ctx_offset = len(prev_tail)
    win_start = max(0, raw_start - WINDOW_CHARS)
    win_end = min(len(context), ctx_offset + raw_end + WINDOW_CHARS)
    return context[max(0, ctx_offset + win_start) : win_end]


def _role_from_window(window: str, context_class: ContextClass) -> MentionRole:
    lower = window.lower()
    if any(k in lower for k in MEASUREMENT_KEYWORDS):
        return MentionRole.MEASUREMENT
    if any(k in lower for k in PROCESSING_KEYWORDS) or context_class == ContextClass.PROCESS_CONTEXT:
        return MentionRole.PROCESSING
    return MentionRole.UNCLEAR


def _role_for(mention: ConditionMention, window: str) -> MentionRole:
    if mention.acceptance_status == AcceptanceStatus.REJECTED_CONTEXT:
        return MentionRole.REJECTED
    return _role_from_window(window, mention.context_class)


def build_candidate_graph(
    document: ScientificDocument,
    view: ConditionLinkView,
) -> CandidateGraph:
    """Build the structural candidate graph over the ledger-routed view."""
    graph = CandidateGraph()

    blocks_by_id: dict[str, tuple[list, int]] = {}
    for page in document.pages:
        for idx, block in enumerate(page):
            blocks_by_id[block.block_id()] = (page, idx)

    # legacy mention order: (page, raw_text) with reading-order + char-offset
    # tie-break (block_id lexicographic order is NOT reading order: "b10" < "b2").
    # Keeps R5/R7 edge direction, representatives and source_quote byte-identical
    # to the pre-Phase-B builder (I12).
    def _mention_sort_key(item: tuple[str, ConditionMention]) -> tuple:
        _node_id, mention = item
        anchor = mention.anchor
        if anchor is None:
            return (0, mention.raw_text, -1, -1)
        loc = blocks_by_id.get(anchor.block_id)
        reading_order = loc[1] if loc is not None else -1
        return (
            anchor.pdf_page_index,
            mention.raw_text,
            reading_order,
            anchor.char_start if anchor.char_start is not None else -1,
        )

    ordered_mentions = sorted(view.mentions.items(), key=_mention_sort_key)

    # windows per candidate (same ±120 rule as the extractor)
    windows: dict[str, str] = {}
    for node_id, mention in ordered_mentions:
        loc = blocks_by_id.get(mention.anchor.block_id) if mention.anchor else None
        if loc is None or mention.anchor is None:
            windows[node_id] = ""
            continue
        page, idx = loc
        windows[node_id] = _mention_window(
            page, idx, page[idx], mention.anchor.char_start or 0, mention.anchor.char_end or 0
        )

    for node_id, mention in ordered_mentions:
        graph.add_mention(node_id, mention, _role_for(mention, windows.get(node_id, "")))

    accepted = [
        mid
        for mid, m in ordered_mentions
        if m.acceptance_status == AcceptanceStatus.ACCEPTED
    ]
    active = [mid for mid in accepted if graph.roles[mid] != MentionRole.REJECTED]
    non_capability = [
        mid
        for mid in active
        if view.mentions[mid].context_class != ContextClass.CAPABILITY_SPEC
    ]

    # ---- table rules (R1-R4) -----------------------------------------
    cells_by_table: dict[str, list] = {}
    rows_by_table: dict[str, dict[int, list]] = {}
    for node in view.cell_nodes.values():
        cells_by_table.setdefault(node.region.table_id, []).append(node)
        rows_by_table.setdefault(node.region.table_id, {}).setdefault(
            node.cell.source_row, []
        ).append(node)

    for region in view.regions:
        table_id = region.table_id
        if region.semantic_type == TableSemanticType.KEY_VALUE_SETUP:
            nodes = cells_by_table.get(table_id, [])
            for i, a in enumerate(nodes):
                for b in nodes[i + 1:]:
                    graph.add_edge(
                        CandidateEdge(
                            source_mention_id=a.candidate_id,
                            target_mention_id=b.candidate_id,
                            type=EdgeType.SAME_EXPERIMENT_CANDIDATE,
                            source_rule="KEY_VALUE_TABLE_WHOLE",
                            edge_strength=EdgeStrength.STRONG,
                            source_block_ids=tuple(sorted({n.cell.source_block_id for n in nodes})),
                            source_table_id=table_id,
                            source_quote=nodes[0].cell.raw_text,
                        )
                    )
        elif region.semantic_type in (TableSemanticType.EXPERIMENT_ROWS, TableSemanticType.COMPARISON_TABLE):
            for row in region.rows:
                nodes = rows_by_table.get(table_id, {}).get(row.index, [])
                if not nodes:
                    continue
                if region.semantic_type == TableSemanticType.EXPERIMENT_ROWS:
                    _row_edges(graph, nodes, table_id, rule="SAME_TABLE_ROW", strength=EdgeStrength.STRONG)
                elif nodes[0].row_kind == RowKind.THIS_WORK:
                    _row_edges(graph, nodes, table_id, rule="COMPARISON_TABLE_THIS_WORK_ROW", strength=EdgeStrength.STRONG)
                else:
                    _row_edges(
                        graph,
                        nodes,
                        table_id,
                        rule="COMPARISON_TABLE_REFERENCE_ROW",
                        strength=EdgeStrength.STRONG,
                        edge_type=EdgeType.COMPARISON_ONLY,
                    )

    # ---- prose parameter group (R5) -----------------------------------
    for page in document.pages:
        for idx, block in enumerate(page):
            block_mentions = [
                mid
                for mid in non_capability
                if (anchor := view.mentions[mid].anchor) is not None
                and anchor.block_id == block.block_id()
            ]
            # line-wrap continuation: sentence split across adjacent blocks
            # ("...at 515" | "nm, 230 fs duration, and repetition rate of
            # 200 kHz was used") - group mentions of both blocks together
            continuation = False
            if block_mentions:
                first_char = block.text.strip()[:1]
                prev_block = page[idx - 1] if idx > 0 else None
                if first_char and first_char.islower() and prev_block is not None:
                    prev_end = prev_block.text.rstrip()
                    if prev_end and prev_end[-1] not in ".!?;:":
                        continuation = True
                        block_mentions = block_mentions + [
                            mid
                            for mid in non_capability
                            if (a := view.mentions[mid].anchor) is not None
                            and a.block_id == prev_block.block_id()
                        ]
            if len(block_mentions) < 2:
                continue
            # partition by role: cross-role co-location must never merge
            by_role: dict[MentionRole, list[str]] = {}
            for mid in block_mentions:
                by_role.setdefault(graph.roles[mid], []).append(mid)
            for role, group in by_role.items():
                if len(group) < 2:
                    continue
                if role == MentionRole.MEASUREMENT:
                    edge_type = EdgeType.MEASUREMENT_ONLY
                elif role == MentionRole.PROCESSING:
                    edge_type = EdgeType.SAME_PARAMETER_GROUP
                else:
                    continue
                strength = EdgeStrength.WEAK
                source_ids = [block.block_id()]
                if continuation and prev_block is not None:
                    source_ids.append(prev_block.block_id())
                for i, ma in enumerate(group):
                    for mb in group[i + 1:]:
                        graph.add_edge(
                            CandidateEdge(
                                source_mention_id=ma,
                                target_mention_id=mb,
                                type=edge_type,
                                source_rule="SAME_BLOCK_PARAMETER_GROUP",
                                edge_strength=strength,
                                source_block_ids=tuple(source_ids),
                                source_quote=view.mentions[ma].raw_text,
                            )
                        )

    # ---- global statement (R6) ----------------------------------------
    for page in document.pages:
        for idx, block in enumerate(page):
            lower = block.text.lower()
            if not any(p in lower for p in GLOBAL_PHRASES):
                continue
            block_mentions = [
                mid
                for mid in non_capability
                if (anchor := view.mentions[mid].anchor) is not None
                and anchor.block_id == block.block_id()
            ]
            if not block_mentions:
                continue
            target_block_ids = []
            for j in range(idx - 1, max(-1, idx - 4), -1):
                prev = page[j]
                if any(
                    (a := view.mentions[mid].anchor) is not None
                    and a.block_id == prev.block_id()
                    for mid in active
                ):
                    target_block_ids.append(prev.block_id())
                    break
            if not target_block_ids:
                continue
            targets = [
                mid
                for mid in active
                if (a := view.mentions[mid].anchor) is not None
                and a.block_id in target_block_ids
                and graph.roles[mid] == MentionRole.PROCESSING
            ]
            for mid in block_mentions:
                for t in targets:
                    graph.add_edge(
                        CandidateEdge(
                            source_mention_id=mid,
                            target_mention_id=t,
                            type=EdgeType.GLOBAL_SCOPE_CANDIDATE,
                            source_rule="EXPLICIT_GLOBAL_STATEMENT",
                            edge_strength=EdgeStrength.MEDIUM,
                            source_block_ids=(block.block_id(),),
                            source_quote=view.mentions[mid].raw_text,
                        )
                    )

    # ---- mutually exclusive processing vs measurement (R7) ------------
    # representative per (parameter, unit, value-tuple, role) to avoid
    # duplicate-mention explosion
    reps: dict[tuple, str] = {}
    for mid in active:
        m = view.mentions[mid]
        if (
            m.parameter in MUTUALLY_EXCLUSIVE_PARAMS
            and graph.roles[mid] in (MentionRole.PROCESSING, MentionRole.MEASUREMENT)
        ):
            key = (m.parameter, m.normalized_unit, tuple(m.values), graph.roles[mid])
            reps.setdefault(key, mid)
    by_param: dict[str, list[str]] = {}
    for mid in reps.values():
        by_param.setdefault(view.mentions[mid].parameter, []).append(mid)
    for group in by_param.values():
        processing = [mid for mid in group if graph.roles[mid] == MentionRole.PROCESSING]
        measurement = [mid for mid in group if graph.roles[mid] == MentionRole.MEASUREMENT]
        for p in processing:
            for q in measurement:
                graph.add_edge(
                    CandidateEdge(
                        source_mention_id=p,
                        target_mention_id=q,
                        type=EdgeType.MUTUALLY_EXCLUSIVE,
                        source_rule="PROCESSING_VS_MEASUREMENT_ROLE",
                        edge_strength=EdgeStrength.STRONG,
                        source_block_ids=(),
                        source_quote=view.mentions[p].raw_text,
                    )
                )
    return graph


def _row_edges(
    graph: CandidateGraph,
    nodes: list,
    table_id: str,
    rule: str,
    strength: EdgeStrength,
    edge_type: EdgeType = EdgeType.SAME_EXPERIMENT_CANDIDATE,
) -> None:
    block_ids = sorted({n.cell.source_block_id for n in nodes})
    row_index = nodes[0].cell.source_row
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            graph.add_edge(
                CandidateEdge(
                    source_mention_id=a.candidate_id,
                    target_mention_id=b.candidate_id,
                    type=edge_type,
                    source_rule=rule,
                    edge_strength=strength,
                    source_block_ids=tuple(block_ids),
                    source_table_id=table_id,
                    source_row=row_index,
                    source_quote=a.cell.raw_text,
                )
            )
