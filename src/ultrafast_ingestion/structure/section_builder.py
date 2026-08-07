"""Section construction from ordered page blocks (Layer 1).

Heading detection is heuristic (English scientific papers, v1):
- unnumbered section keywords (abstract/introduction/methods/experimental/
  results/discussion/conclusion/references/summary/supplementary)
- numbered headings ("1. ", "2.1 ", "I. ", "III. ")
- caption detection for FIG./Table/Fig./Tab. prefixes

Section boundaries never split blocks; reading order is preserved
(blocks stay in their original global sequence; each block belongs to
exactly one section). Paragraph = single body block (v1 granularity).
"""

from __future__ import annotations

import re
from typing import Any

from ultrafast_ingestion.models.document import PageBlock, Paragraph, Section
from ultrafast_ingestion.models.provenance import stable_hash

_SECTION_KEYWORDS = {
    "abstract": "abstract",
    "introduction": "introduction",
    "methods": "methods",
    "method": "methods",
    "experimental": "methods",
    "experiment": "methods",
    "materials and methods": "methods",
    "materials and method": "methods",
    "material and methods": "methods",
    "material and method": "methods",
    "experimental details": "methods",
    "experimental setup": "methods",
    "experimental section": "methods",
    "sample preparation": "methods",
    "sample pre-treatment": "methods",
    "laser inscription": "methods",
    "laser writing": "methods",
    "irradiation": "methods",
    "irradiation of": "methods",
    "characterization": "methods",
    "measurement": "methods",
    "measurements": "methods",
    "spin manipulation": "methods",
    "results": "results",
    "results and discussion": "discussion",
    "discussion": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "summary": "conclusion",
    "references": "references",
    "acknowledgments": "misc",
    "acknowledgements": "misc",
    "supplementary": "supplementary",
}

_NUMBERED_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*|[IVX]+(?:\.\d+)*)[\.\s\)]+\s*(.+?)\s*$", re.IGNORECASE
)
_ABSTRACT_RE = re.compile(r"^\s*(abstract|摘要)\s*$", re.IGNORECASE)
_CAPTION_RE = re.compile(r"^\s*(fig(?:ure)?\.?|table|tab\.)\s*[\dS]?", re.IGNORECASE)
_ROMAN_MARKER_RE = re.compile(r"^\s*[IVX\d]+\.?\s*$")


def _heading_kind(text: str) -> tuple[bool, str, str]:
    """Return (is_heading, section_type, clean_title)."""
    lines = text.splitlines()
    first_line = lines[0].strip()
    # multi-line marker headings: "I.\nINTRODUCTION" or "2.\nMethods"
    if len(first_line) <= 6 and _ROMAN_MARKER_RE.match(first_line) and len(lines) > 1:
        first_line = first_line + " " + lines[1].strip()
        lines = [first_line, *lines[2:]]
    if len(first_line) > 120:
        return False, "", ""
    lower = first_line.lower().strip(".: ")
    if lower in _SECTION_KEYWORDS:
        return True, _SECTION_KEYWORDS[lower], first_line.strip(".: ")
    m = _NUMBERED_RE.match(first_line)
    if m:
        title = m.group(1).strip(".: ")
        kind = _match_keyword(title)
        return True, kind, title
    # unnumbered standalone keyword heading
    if len(first_line.split()) <= 4:
        kind = _match_keyword(first_line)
        if kind != "section":
            return True, kind, first_line.strip(".: ")
    return False, "", ""


def _match_keyword(title: str) -> str:
    """Exact match first, then longest-keyword prefix match."""
    lower = title.lower().strip(".: ")
    if lower in _SECTION_KEYWORDS:
        return _SECTION_KEYWORDS[lower]
    best = ("", "section")
    for key, kind in _SECTION_KEYWORDS.items():
        if lower.startswith(key) and len(key) > len(best[0]):
            best = (key, kind)
    return best[1]


def _is_caption(text: str, prefixes: list[str]) -> bool:
    first = text.strip().splitlines()[0].strip().lower()
    if _CAPTION_RE.match(first):
        return True
    for p in prefixes:
        if first.startswith(p):
            return True
    return False


def build_sections(
    blocks: list[PageBlock],
    *,
    paper_id: str,
    document_version_id: str,
    config: dict[str, Any],
) -> tuple[list[Section], list[PageBlock]]:
    sections: list[Section] = []
    captions: list[PageBlock] = []
    prefix_list = config.get("caption_prefixes") or []

    current: Section | None = None
    ordinal = 0

    def close_section() -> None:
        nonlocal current
        if current is not None and current.block_ids:
            sections.append(current)
        current = None

    # assign section membership in global reading order
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if _is_caption(text, prefix_list):
            block.block_type = "caption"
            captions.append(block)
            continue
        is_heading, kind, title = _heading_kind(text)
        if is_heading:
            close_section()
            ordinal += 1
            section_id = stable_hash(document_version_id, kind, str(ordinal))
            path = f"1/{kind}/{ordinal}"
            current = Section(
                section_id=section_id,
                title=title,
                section_type=kind,
                level=1,
                page_start=block.page_index,
                page_end=block.page_index,
                path=path,
            )
            block.block_type = "heading"
            block.section_id = section_id
            block.section_path = path
            current.block_ids.append(block.block_id())
            continue
        if current is None:
            close_section()
            ordinal += 1
            section_id = stable_hash(document_version_id, "preamble", str(ordinal))
            current = Section(
                section_id=section_id,
                title="preamble",
                section_type="preamble",
                level=0,
                page_start=block.page_index,
                page_end=block.page_index,
                path=f"0/preamble/{ordinal}",
            )
        block.section_id = current.section_id
        block.section_path = current.path
        current.block_ids.append(block.block_id())

    close_section()

    # finalize page_end + paragraphs (one paragraph per body block, v1)
    for sec in sections:
        sec.block_ids = [b for b in sec.block_ids]  # keep order
        last_page = sec.page_start
        for block in blocks:
            if block.block_id() in sec.block_ids:
                last_page = max(last_page, block.page_index)
        sec.page_end = last_page
        for block in blocks:
            if block.block_id() in sec.block_ids and block.block_type == "body":
                pid = stable_hash(document_version_id, sec.path, block.block_id())
                sec.paragraphs.append(
                    Paragraph(
                        paragraph_id=pid,
                        section_path=sec.path,
                        block_ids=[block.block_id()],
                        text=block.text,
                    )
                )

    return sections, captions
