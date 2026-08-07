"""O2: DiscoveryBatch construction (contract §2: skeleton batch)."""

from __future__ import annotations

import pytest

from tests.test_discovery_windows import make_doc
from ultrafast_ingestion.discovery.discoverer import DiscoveryBatchBuilder
from ultrafast_ingestion.discovery.models import DiscoveryWindowConfig
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder
from ultrafast_ingestion.models.provenance import stable_hash

pytestmark = pytest.mark.unit


def _doc():
    return make_doc()


def test_batch_deterministic() -> None:
    doc = _doc()
    first = DiscoveryBatchBuilder().build(doc)
    second = DiscoveryBatchBuilder().build(doc)
    assert [b.to_canonical_dict() for b in first] == [b.to_canonical_dict() for b in second]


def test_batch_never_crosses_paper() -> None:
    doc = _doc()
    for batch in DiscoveryBatchBuilder().build(doc):
        assert batch.paper_id == doc.paper_id
        assert batch.document_version_id == doc.document_version_id


def test_default_config_single_batch() -> None:
    doc = _doc()
    batches = DiscoveryBatchBuilder().build(doc)
    assert len(batches) == 1
    assert batches[0].window_refs == ("w0", "w1", "w2", "w3", "w4")
    assert len(batches[0].window_ids) == 5
    # every window appears in the batch text with its numbered header
    for ref in batches[0].window_refs:
        assert f"[{ref}]" in batches[0].text


def test_token_budget_splits_batches() -> None:
    doc = _doc()
    config = DiscoveryWindowConfig(target_batch_tokens=15)
    batches = DiscoveryBatchBuilder(config=config).build(doc)
    assert len(batches) > 1
    for batch in batches:
        assert len(batch.text.split()) <= config.max_batch_tokens


def test_oversized_window_gets_own_batch() -> None:
    doc = _doc()
    big_block = _oversized_block(doc, "word " * 3000)
    config = DiscoveryWindowConfig(max_batch_tokens=1000)
    windows = DiscoveryWindowBuilder(config=config).build(doc)
    big_window = next(w for w in windows if big_block.block_id() in w.block_ids)
    batches = DiscoveryBatchBuilder(config=config).build(doc)
    hits = [b for b in batches if big_window.window_id in b.window_ids]
    assert len(hits) == 1
    assert hits[0].window_ids == (big_window.window_id,)


def test_batch_id_changes_with_config() -> None:
    doc = _doc()
    default = DiscoveryBatchBuilder().build(doc)[0]
    tuned = DiscoveryBatchBuilder(
        config=DiscoveryWindowConfig(target_batch_tokens=10)
    ).build(doc)[0]
    assert default.batch_id != tuned.batch_id
    assert default.window_config_version != tuned.window_config_version


def test_all_windows_covered_by_batches() -> None:
    doc = _doc()
    windows = DiscoveryWindowBuilder().build(doc)
    batches = DiscoveryBatchBuilder().build(doc)
    covered = {wid for b in batches for wid in b.window_ids}
    assert covered == {w.window_id for w in windows}


def _oversized_block(doc, text: str):
    template = doc.pages[0][0]
    block = type(template)(
        paper_id=template.paper_id,
        document_version_id=template.document_version_id,
        page_index=3,
        bbox=template.bbox,
        block_index=999,
        reading_order=999,
        text=text,
        section_path="1/methods/1",
        section_id=stable_hash(template.document_version_id, "big"),
    )
    doc.pages[0].append(block)
    doc.blocks_by_id[block.block_id()] = block
    return block
