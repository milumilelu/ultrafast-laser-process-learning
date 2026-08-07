"""Structural candidate graph builder (Layer 3, step 2).

High-confidence deterministic rules only. Weak heuristics (same
paragraph / char distance) are deliberately NOT strong edges.

Rules:
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
    TableRegion,
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
    mentions: list[ConditionMention],
    regions: list[TableRegion],
) -> CandidateGraph:
    graph = CandidateGraph()

    # windows per mention (same ±120 rule as the extractor)
    windows: dict[str, str] = {}
    blocks_by_id: dict[str, tuple[list, int]] = {}
    for page in document.pages:
        for idx, block in enumerate(page):
            blocks_by_id[block.block_id()] = (page, idx)
    for m in mentions:
        loc = blocks_by_id.get(m.anchor.block_id) if m.anchor else None
        if loc is None or m.anchor is None:
            windows[m.mention_id] = ""
            continue
        page, idx = loc
        windows[m.mention_id] = _mention_window(
            page, idx, page[idx], m.anchor.char_start or 0, m.anchor.char_end or 0
        )

    for m in mentions:
        graph.add_mention(m, _role_for(m, windows.get(m.mention_id, "")))

    accepted = [m for m in mentions if m.acceptance_status == AcceptanceStatus.ACCEPTED]
    active = [m for m in accepted if graph.roles[m.mention_id] != MentionRole.REJECTED]
    non_capability = [
        m
        for m in active
        if m.context_class != ContextClass.CAPABILITY_SPEC
    ]

    # ---- table rules (R1-R4) -----------------------------------------
    for region in regions:
        table_id = region.table_id
        rows = [r for r in region.rows if r.cells]
        if region.semantic_type == TableSemanticType.KEY_VALUE_SETUP:
            all_cells = [c for row in rows for c in row.cells]
            keys = [_cell_key(c) for c in all_cells]
            for i, a in enumerate(keys):
                for b in keys[i + 1:]:
                    graph.add_edge(
                        CandidateEdge(
                            source_mention_id=a,
                            target_mention_id=b,
                            type=EdgeType.SAME_EXPERIMENT_CANDIDATE,
                            source_rule="KEY_VALUE_TABLE_WHOLE",
                            edge_strength=EdgeStrength.STRONG,
                            source_block_ids=tuple(sorted({c.source_block_id for c in all_cells})),
                            source_table_id=table_id,
                            source_quote=all_cells[0].raw_text,
                        )
                    )
        elif region.semantic_type == TableSemanticType.EXPERIMENT_ROWS:
            for row in rows:
                _row_edges(graph, row, table_id, rule="SAME_TABLE_ROW", strength=EdgeStrength.STRONG)
        elif region.semantic_type == TableSemanticType.COMPARISON_TABLE:
            for row in rows:
                if row.kind == RowKind.THIS_WORK:
                    _row_edges(graph, row, table_id, rule="COMPARISON_TABLE_THIS_WORK_ROW", strength=EdgeStrength.STRONG)
                elif row.kind == RowKind.REFERENCE:
                    _row_edges(graph, row, table_id, rule="COMPARISON_TABLE_REFERENCE_ROW", strength=EdgeStrength.STRONG, edge_type=EdgeType.COMPARISON_ONLY)

    # ---- prose parameter group (R5) -----------------------------------
    for page in document.pages:
        for idx, block in enumerate(page):
            block_mentions = [
                m
                for m in non_capability
                if m.anchor and m.anchor.block_id == block.block_id()
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
                            m
                            for m in non_capability
                            if m.anchor and m.anchor.block_id == prev_block.block_id()
                        ]
            if len(block_mentions) < 2:
                continue
            # partition by role: cross-role co-location must never merge
            by_role: dict[MentionRole, list] = {}
            for m in block_mentions:
                by_role.setdefault(graph.roles[m.mention_id], []).append(m)
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
                                source_mention_id=ma.mention_id,
                                target_mention_id=mb.mention_id,
                                type=edge_type,
                                source_rule="SAME_BLOCK_PARAMETER_GROUP",
                                edge_strength=strength,
                                source_block_ids=tuple(source_ids),
                                source_quote=ma.raw_text,
                            )
                        )

    # ---- global statement (R6) ----------------------------------------
    for page in document.pages:
        for idx, block in enumerate(page):
            lower = block.text.lower()
            if not any(p in lower for p in GLOBAL_PHRASES):
                continue
            block_mentions = [m for m in non_capability if m.anchor and m.anchor.block_id == block.block_id()]
            if not block_mentions:
                continue
            target_block_ids = []
            for j in range(idx - 1, max(-1, idx - 4), -1):
                prev = page[j]
                if any(m.anchor and m.anchor.block_id == prev.block_id() for m in active):
                    target_block_ids.append(prev.block_id())
                    break
            if not target_block_ids:
                continue
            targets = [
                m
                for m in active
                if m.anchor
                and m.anchor.block_id in target_block_ids
                and graph.roles[m.mention_id] == MentionRole.PROCESSING
            ]
            for m in block_mentions:
                for t in targets:
                    graph.add_edge(
                        CandidateEdge(
                            source_mention_id=m.mention_id,
                            target_mention_id=t.mention_id,
                            type=EdgeType.GLOBAL_SCOPE_CANDIDATE,
                            source_rule="EXPLICIT_GLOBAL_STATEMENT",
                            edge_strength=EdgeStrength.MEDIUM,
                            source_block_ids=(block.block_id(),),
                            source_quote=m.raw_text,
                        )
                    )

    # ---- mutually exclusive processing vs measurement (R7) ------------
    # representative per (parameter, unit, value-tuple, role) to avoid
    # duplicate-mention explosion
    reps: dict[tuple, ConditionMention] = {}
    for m in active:
        if (
            m.parameter in MUTUALLY_EXCLUSIVE_PARAMS
            and graph.roles[m.mention_id] in (MentionRole.PROCESSING, MentionRole.MEASUREMENT)
        ):
            key = (m.parameter, m.normalized_unit, tuple(m.values), graph.roles[m.mention_id])
            reps.setdefault(key, m)
    by_param: dict[str, list[ConditionMention]] = {}
    for m in reps.values():
        by_param.setdefault(m.parameter, []).append(m)
    for group in by_param.values():
        processing = [m for m in group if graph.roles[m.mention_id] == MentionRole.PROCESSING]
        measurement = [m for m in group if graph.roles[m.mention_id] == MentionRole.MEASUREMENT]
        for p in processing:
            for q in measurement:
                graph.add_edge(
                    CandidateEdge(
                        source_mention_id=p.mention_id,
                        target_mention_id=q.mention_id,
                        type=EdgeType.MUTUALLY_EXCLUSIVE,
                        source_rule="PROCESSING_VS_MEASUREMENT_ROLE",
                        edge_strength=EdgeStrength.STRONG,
                        source_block_ids=(),
                        source_quote=p.raw_text,
                    )
                )
    return graph


def _row_edges(
    graph: CandidateGraph,
    row,
    table_id: str,
    rule: str,
    strength: EdgeStrength,
    edge_type: EdgeType = EdgeType.SAME_EXPERIMENT_CANDIDATE,
) -> None:
    block_ids = sorted({c.source_block_id for c in row.cells})
    cells = row.cells
    for i, a in enumerate(cells):
        for b in cells[i + 1:]:
            graph.add_edge(
                CandidateEdge(
                    source_mention_id=_cell_key(a),
                    target_mention_id=_cell_key(b),
                    type=edge_type,
                    source_rule=rule,
                    edge_strength=strength,
                    source_block_ids=tuple(block_ids),
                    source_table_id=table_id,
                    source_row=row.index,
                    source_quote=a.raw_text,
                )
            )


def _cell_key(cell) -> str:
    return f"cell:{cell.source_block_id}:{cell.source_row}:{cell.parameter}:{cell.value}"
