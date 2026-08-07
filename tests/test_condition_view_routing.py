"""ConditionLinkView routing semantics (CANDIDATE_LEDGER_V0_1 §8.2, I11)."""

from __future__ import annotations

import pytest

from tests.conftest import DOC_BLOCK_TEXT, make_doc, make_mention, make_region
from ultrafast_ingestion.candidates.ledger import build_ledger, candidate_id_for_cell
from ultrafast_ingestion.candidates.models import MappingStatus
from ultrafast_ingestion.mentions.models import AcceptanceStatus, ContextClass
from ultrafast_ingestion.tables.models import (
    RowKind,
    TableRegion,
    TableSemanticType,
)

pytestmark = pytest.mark.unit


def test_view_includes_all_condition_mentions() -> None:
    doc = make_doc()
    block = doc.pages[0][0]
    start = DOC_BLOCK_TEXT.index("200 kHz")
    accepted = make_mention(
        doc, block=block, parameter="frequency", values=[200.0],
        raw_text="200 kHz", start=start, end=start + 7,
    )
    rejected = make_mention(
        doc, block=block, parameter="wavelength", values=[1132.0],
        raw_text="1132 nm", start=0, end=7, unit="nm",
        status=AcceptanceStatus.REJECTED_CONTEXT,
        context=ContextClass.EMISSION_WAVELENGTH, reason="emission/ZPL wavelength",
    )
    ledger = build_ledger(doc, [accepted, rejected], [])
    view = ledger.for_condition_linking(doc, [])
    assert len(view.mentions) == 2
    # routing: rejected is a node (node-set semantics) but NOT eligible for linking
    assert len(view.eligible_mention_ids) == 1
    assert view.eligible_mention_ids[0] not in {
        c.candidate_id for c in ledger.candidates if c.source_ref == rejected.mention_id
    }


def test_eligible_mentions_are_mapped_or_ambiguous() -> None:
    doc = make_doc()
    block = doc.pages[0][0]
    start = DOC_BLOCK_TEXT.index("200 kHz")
    accepted = make_mention(
        doc, block=block, parameter="frequency", values=[200.0],
        raw_text="200 kHz", start=start, end=start + 7,
    )
    ambiguous = make_mention(
        doc, block=block, parameter="frequency", values=[1.0],
        raw_text="1 MHz", start=0, end=6, unit="MHz",
        status=AcceptanceStatus.AMBIGUOUS_CONTEXT,
    )
    ledger = build_ledger(doc, [accepted, ambiguous], [])
    view = ledger.for_condition_linking(doc, [])
    statuses = {m.candidate_id: m.status for m in ledger.mappings}
    for cid in view.eligible_mention_ids:
        assert statuses[cid] in (MappingStatus.MAPPED, MappingStatus.AMBIGUOUS)
    assert len(view.eligible_mention_ids) == 2


def test_cell_nodes_only_from_edge_eligible_tables() -> None:
    doc = make_doc()
    block = doc.pages[0][0]
    eligible = make_region(block, semantic_type=TableSemanticType.EXPERIMENT_ROWS)
    excluded = make_region(
        block, table_id="t2", semantic_type=TableSemanticType.RESULT_MATRIX
    )
    ledger = build_ledger(doc, [], [eligible, excluded])
    view = ledger.for_condition_linking(doc, [eligible, excluded])
    # identical cells across tables are the same candidate (legacy node semantics:
    # identity = block+row+param+value, table_id not part of it)...
    ledger_cells = {c.candidate_id for c in ledger.candidates if c.source_type.value == "TABLE_CELL"}
    assert len(ledger_cells) == 2
    # ...and only the eligible table's cells are routed into the view
    assert len(view.cell_nodes) == 2
    for cid, node in view.cell_nodes.items():
        assert cid in ledger_cells
        assert node.region.table_id == "t1"
        assert node.cell.source_row == 1


def test_view_identity_matches_ledger_identity() -> None:
    doc = make_doc()
    block = doc.pages[0][0]
    region = make_region(block)
    ledger = build_ledger(doc, [], [region])
    view = ledger.for_condition_linking(doc, [region])
    cell = region.rows[0].cells[0]
    cid = candidate_id_for_cell(doc, cell)
    assert cid in view.cell_nodes
    assert view.cell_nodes[cid].cell == cell


def test_view_never_mutates_ledger() -> None:
    doc = make_doc()
    block = doc.pages[0][0]
    start = DOC_BLOCK_TEXT.index("200 kHz")
    mention = make_mention(
        doc, block=block, parameter="frequency", values=[200.0],
        raw_text="200 kHz", start=start, end=start + 7,
    )
    ledger = build_ledger(doc, [mention], [])
    before = ledger.to_canonical_dict()
    ledger.for_condition_linking(doc, [])
    assert ledger.to_canonical_dict() == before


def test_ledger_regions_mismatch_raises() -> None:
    doc = make_doc()
    block = doc.pages[0][0]
    region = make_region(block)
    ledger = build_ledger(doc, [], [region])
    # a cell never ingested into the ledger must fail loudly (I9/I10):
    # same block, but a row index the ledger never saw
    from ultrafast_ingestion.tables.models import TableCell, TableRow

    foreign = TableRegion(
        table_id="t_foreign",
        semantic_type=TableSemanticType.EXPERIMENT_ROWS,
        rows=[
            TableRow(
                index=9,
                kind=RowKind.THIS_WORK,
                raw_text="",
                cells=[
                    TableCell(
                        value=999.0,
                        unit="nm",
                        parameter="wavelength",
                        raw_text="999 nm",
                        source_block_id=block.block_id(),
                        source_row=9,
                    )
                ],
            )
        ],
    )
    with pytest.raises(ValueError):
        ledger.for_condition_linking(doc, [foreign])
