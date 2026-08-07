"""Table-cell formal identity (CANDIDATE_LEDGER_V0_1.md §1.1/§4 DoD 3, I5)."""

from __future__ import annotations

from tests.conftest import DOC_BLOCK_TEXT, make_doc, make_mention, make_region
from ultrafast_ingestion.candidates.ledger import build_ledger, legacy_cell_key
from ultrafast_ingestion.candidates.models import (
    DISCOVERY_METHOD_CELL,
    GroundingStatus,
    MappingStatus,
    PromotionStatus,
)
from ultrafast_ingestion.tables.models import TableSemanticType


def _cell_ledger():
    doc = make_doc()
    block = doc.pages[0][0]
    region = make_region(block, semantic_type=TableSemanticType.KEY_VALUE_SETUP)
    return build_ledger(doc, [], [region]), block, region


def test_cell_candidate_has_formal_identity() -> None:
    ledger, _block, region = _cell_ledger()
    cell = region.rows[0].cells[0]
    hits = [c for c in ledger.candidates if c.source_ref == legacy_cell_key(cell)]
    assert len(hits) == 1
    candidate = hits[0]
    # formal identity replaces the pseudo key; the legacy key survives in source_ref
    assert candidate.candidate_id != legacy_cell_key(cell)
    assert not candidate.candidate_id.startswith("cell:")  # stable_hash hex, not the pseudo key
    assert candidate.source_type.value == "TABLE_CELL"
    assert candidate.concept_label == "wavelength"
    assert candidate.raw_statement == "515 nm"
    assert candidate.discovery_method == DISCOVERY_METHOD_CELL


def test_cell_candidate_anchored() -> None:
    ledger, block, region = _cell_ledger()
    cell = region.rows[0].cells[0]
    candidate = next(c for c in ledger.candidates if c.source_ref == legacy_cell_key(cell))
    assert candidate.grounding_status == GroundingStatus.GROUNDED
    assert len(candidate.provenance_anchors) == 1
    assert candidate.provenance_anchors[0].block_id == block.block_id()
    assert candidate.provenance_anchors[0].normalized_quote == "515 nm"
    assert candidate.provenance_anchors[0].bbox == block.bbox


def test_cell_candidate_mapping_mapped() -> None:
    ledger, _, _ = _cell_ledger()
    for candidate in ledger.candidates:
        mapping = [m for m in ledger.mappings if m.candidate_id == candidate.candidate_id]
        assert len(mapping) == 1
        assert mapping[0].status == MappingStatus.MAPPED
        assert mapping[0].target_field == candidate.source_detail["parameter"]
    # both cells of the row present
    assert len(ledger.candidates) == 2


def test_cell_promotion_state() -> None:
    ledger, _, _ = _cell_ledger()
    for candidate in ledger.candidates:
        assert candidate.promotion_status == PromotionStatus.NOT_PROMOTED
        assert candidate.promotion_reason == "cell_not_promoted"


def test_cell_identity_stable_across_builds() -> None:
    first, _, _ = _cell_ledger()
    second, _, _ = _cell_ledger()
    assert [c.candidate_id for c in first.candidates] == [c.candidate_id for c in second.candidates]


def test_cell_source_detail_keeps_table_context() -> None:
    ledger, _, region = _cell_ledger()
    cell = region.rows[0].cells[0]
    detail = next(
        c for c in ledger.candidates if c.source_ref == legacy_cell_key(cell)
    ).source_detail
    assert detail["table_id"] == region.table_id
    assert detail["semantic_type"] == "KEY_VALUE_SETUP"
    assert detail["row_index"] == 1
    assert detail["value"] == 515.0
    assert detail["unit"] == "nm"
    assert detail["legacy_cell_key"] == legacy_cell_key(region.rows[0].cells[0])


def test_mention_and_cell_coexist_without_collision() -> None:
    """I1 + I5 together: same paper, mentions + cells, all preserved."""
    doc = make_doc()
    block = doc.pages[0][0]
    start = DOC_BLOCK_TEXT.index("200 kHz")
    mention = make_mention(
        doc,
        block=block,
        parameter="frequency",
        values=[200.0],
        raw_text="200 kHz",
        start=start,
        end=start + 7,
    )
    ledger = build_ledger(doc, [mention], [make_region(block)])
    source_types = [c.source_type.value for c in ledger.candidates]
    assert sorted(source_types) == ["CONDITION_MENTION", "TABLE_CELL", "TABLE_CELL"]
    ids = [c.candidate_id for c in ledger.candidates]
    assert len(set(ids)) == 3
