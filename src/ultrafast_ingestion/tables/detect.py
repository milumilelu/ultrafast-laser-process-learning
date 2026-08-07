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


def _is_table_like_block(block: PageBlock) -> bool:
    """Compact numeric table rows inside a caption window.

    Some PDFs render experiment tables as blocks whose first line is a row
    number (e.g. "1 / 1000 / 50 / 950 / 3 / 120 ..."), which section_builder
    mislabels as heading. Such blocks carry mostly-numeric short rows with
    very few unit-attached mentions, so _is_row_block rejects them. We accept
    them inside a caption window only (risk-controlled).
    """
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    tokens = [tok for line in lines for tok in line.split()]
    if not tokens or len(tokens) > 200:
        return False
    numeric = sum(1 for tok in tokens if _NUMERIC_TOKEN_RE.match(tok))
    return numeric / len(tokens) >= 0.5 and all(len(line.split()) <= 24 for line in lines)


_NUMERIC_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?[A-Za-zµ]*$|^[vVxX/]$")


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
        row_blocks: list[PageBlock] = []
        window_start = max(0, i - 5)
        window_end = min(n, i + 1 + _MAX_SCAN)
        for j in range(window_start, window_end):
            if j == i:
                continue
            nb = blocks[j]
            # heading-labelled compact numeric rows inside the caption window
            # are table bodies (section_builder mislabels row-numbered blocks)
            if nb.block_type == "heading" and not _is_table_like_block(nb):
                continue
            if nb.block_id() in used:
                continue
            if _TABLE_CAPTION_RE.match(nb.text.strip()):
                continue
            if _is_row_block(nb) or _is_table_like_block(nb):
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
