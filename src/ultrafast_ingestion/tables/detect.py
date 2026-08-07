"""Deterministic table region detection from page blocks.

A TableRegion = optional "Table ..." caption block + compact numeric
row blocks (high value/unit mention density) within the next blocks.
Prose in between is skipped (paper 11 Table I rows follow prose after the
caption). Implicit tables (no caption, e.g. Flat-top Table I) are detected
by compactness + label first line.
"""

from __future__ import annotations

import re

from ultrafast_ingestion.mentions.patterns import _TABLE_CELL_RE, find_mentions
from ultrafast_ingestion.models.document import PageBlock, ScientificDocument
from ultrafast_ingestion.models.provenance import stable_hash

_TABLE_CAPTION_RE = re.compile(r"^\s*(table|tab\.)\s*[IVX\d]?", re.IGNORECASE)
_MAX_SCAN = 10
_MIN_DENSITY = 6
_MAX_CHARS_PER_MENTION = 40


def _mention_density(text: str) -> int:
    return len(list(find_mentions(text)))


def _is_row_block(block: PageBlock) -> bool:
    text = block.text.strip()
    if not text:
        return False
    density = _mention_density(text)
    if density < _MIN_DENSITY:
        return False
    return len(text) / density <= _MAX_CHARS_PER_MENTION


def _is_implicit_keyvalue_block(block: PageBlock) -> bool:
    first = block.text.strip().splitlines()[0] if block.text.strip() else ""
    return _is_row_block(block) and len(first) <= 60 and len(list(_TABLE_CELL_RE.finditer(block.text))) >= 3


def detect_table_regions(document: ScientificDocument) -> list:
    from ultrafast_ingestion.tables.models import TableRegion, TableSemanticType

    regions: list[TableRegion] = []
    blocks = [b for page in document.pages for b in page]
    n = len(blocks)
    used: set[str] = set()

    def make_region(caption: PageBlock | None, row_blocks: list[PageBlock], tag: str) -> TableRegion:
        region = TableRegion(
            table_id=stable_hash(document.document_version_id, "table", tag),
            semantic_type=TableSemanticType.UNKNOWN,
            caption_block_id=caption.block_id() if caption else "",
        )
        if caption:
            region.blocks.append(caption)
        region.blocks.extend(row_blocks)
        for b in row_blocks:
            used.add(b.block_id())
        return region

    # pass 1: caption-led regions (row blocks may precede the caption:
    # "TABLE I" caption often follows the table body)
    for i, block in enumerate(blocks):
        if block.block_type != "caption" or not _TABLE_CAPTION_RE.match(block.text.strip()):
            continue
        row_blocks = []
        window_start = max(0, i - 5)
        window_end = min(n, i + 1 + _MAX_SCAN)
        for j in range(window_start, window_end):
            if j == i:
                continue
            nb = blocks[j]
            if nb.block_type == "heading":
                continue
            if nb.block_id() in used:
                continue
            if _TABLE_CAPTION_RE.match(nb.text.strip()):
                continue
            if _is_row_block(nb):
                row_blocks.append(nb)
        if row_blocks:
            regions.append(make_region(block, row_blocks, f"caption-{len(regions) + 1}"))

    # pass 2: implicit key-value tables (Flat-top Table I has no caption block)
    for i, block in enumerate(blocks):
        if block.block_id() in used:
            continue
        if _is_implicit_keyvalue_block(block):
            regions.append(make_region(None, [block], f"implicit-{len(regions) + 1}"))
    return regions
