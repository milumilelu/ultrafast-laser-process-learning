"""TableSemanticType classification + row/cell parsing (deterministic)."""

from __future__ import annotations

import re

from ultrafast_ingestion.mentions.patterns import _TABLE_CELL_RE, find_mentions
from ultrafast_ingestion.mentions.units import normalize_unit, parameter_from_label
from ultrafast_ingestion.tables.models import (
    RowKind,
    TableCell,
    TableRegion,
    TableRow,
    TableSemanticType,
)

_THIS_WORK_RE = re.compile(r"^\s*(this work|this paper|本文|present work)\b", re.IGNORECASE)
_REF_RE = re.compile(
    r"^\s*(?:ref(?:\.|erence)?\s*\d+|\d{4}\b|[A-Z][A-Za-z]+(?:\s+et al\.?)?\s*,?\s*\d{4}|"
    r"\d{1,3}(?=\s+\d+(?:\.\d+)?\s*(?:nm|kHz|fs|ps|ns|J/cm2|nJ|mJ|uJ)))"
)
_HEADER_RE = re.compile(
    r"^\s*(reference|parameters|values|source|λ|lambda|laser|exp(?:eriment)?|description)\b",
    re.IGNORECASE,
)

# row-lead tokens inside a merged single-line block:
# "This work 1030 nm ..." / "33 1030 nm ..." / "19 790 nm ..."
_ROW_LEAD_RE = re.compile(
    r"(?=(?:^|\s)(?:this work\b|本文|ref(?:erence)?\.?\s*\d+\b|"
    r"\d+\s+\d+(?:\.\d+)?\s*(?:nm|kHz|fs|ps|ns|J/cm2|nJ|mJ|uJ)))",
    re.IGNORECASE,
)

# ---- header-column parsing (A1 fix) -------------------------------------
# Known parameter labels that may appear as separated table headers
# ("Frequency" block + "(Hz)" block + numeric row blocks). Used only as a
# fallback when the standard cell parsing produced no rows.
_HEADER_LABEL_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"repetition\s*(?:rate|frequency)\b", re.IGNORECASE), "frequency"),
    (re.compile(r"^\s*frequency\b", re.IGNORECASE), "frequency"),
    (re.compile(r"scan(?:ning)?\s*speed\b", re.IGNORECASE), "scan_speed"),
    (re.compile(r"hatch\s*(?:distance|spacing)\b", re.IGNORECASE), "hatch_spacing"),
    (re.compile(r"average\s*power\b|laser\s*power\b", re.IGNORECASE), "average_power"),
    (re.compile(r"pulse\s*energy\b", re.IGNORECASE), "pulse_energy"),
    (re.compile(r"spot\s*(?:diameter|size)\b", re.IGNORECASE), "spot_size"),
    (re.compile(r"pulse\s*(?:width|duration)\b", re.IGNORECASE), "pulse_width"),
    (re.compile(r"^\s*pitch\b", re.IGNORECASE), "pitch"),
    (re.compile(r"wavelength\b", re.IGNORECASE), "wavelength"),
    (re.compile(r"^\s*passes\b", re.IGNORECASE), "passes"),
)

_UNIT_TOKEN_RE = re.compile(r"^\(?([A-Za-zµμ/]+(?:/[A-Za-zµμ]+)?)\)?$")


def _header_columns(header_text: str) -> dict[int, tuple[str, str | None]]:
    """Map token index -> (canonical parameter, unit | None) from header text.

    Header may span multiple blocks ("Frequency" / "(Hz)" as separate lines);
    tokens are taken in order, unit tokens immediately following a label are
    consumed as that column's unit.
    """
    tokens = header_text.split()
    columns: dict[int, tuple[str, str | None]] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        matched = None
        for pattern, parameter in _HEADER_LABEL_PATTERNS:
            if pattern.match(token):
                matched = parameter
                break
        if matched is None:
            i += 1
            continue
        unit = None
        if i + 1 < len(tokens):
            m = _UNIT_TOKEN_RE.match(tokens[i + 1])
            if m:
                unit = normalize_unit(m.group(1))
        columns[i] = (matched, unit)
        i += 1 if unit is None else 2
    return columns


def _parse_header_column_rows(
    region: TableRegion, header_blocks: list, data_blocks: list
) -> list[TableRow]:
    """Data rows split by header token columns (fallback parser)."""
    header_text = " ".join(b.text for b in header_blocks)
    columns = _header_columns(header_text)
    if not columns:
        return []
    rows: list[TableRow] = []
    for block in data_blocks:
        for line in block.text.splitlines():
            line = line.strip()
            if not line:
                continue
            tokens = line.split()
            row = TableRow(
                index=len(rows), kind=RowKind.DATA, raw_text=line,
            )
            for col_idx, (parameter, unit) in columns.items():
                if col_idx >= len(tokens):
                    continue
                raw = tokens[col_idx]
                if not re.match(r"^[-+]?\d+(?:[.,]\d+)?$", raw):
                    continue
                row.cells.append(
                    TableCell(
                        value=float(raw.replace(",", ".")),
                        unit=unit or "",
                        parameter=parameter,
                        raw_text=raw,
                        source_block_id=block.block_id(),
                        source_row=len(rows),
                    )
                )
            if row.cells:
                rows.append(row)
    return rows


def _row_kind(first_line: str) -> RowKind:
    if not first_line:
        return RowKind.HEADER
    if _HEADER_RE.match(first_line):
        return RowKind.HEADER
    if _THIS_WORK_RE.match(first_line):
        return RowKind.THIS_WORK
    if _REF_RE.match(first_line):
        return RowKind.REFERENCE
    return RowKind.DATA


def _split_rows(text: str) -> list[str]:
    """Split a table block into row texts: prefer row-lead tokens, fall
    back to newlines."""
    parts = [p for p in _ROW_LEAD_RE.split(text) if p and p.strip()]
    if len(parts) > 1:
        return parts
    return [line for line in text.splitlines() if line.strip()]


def _parse_rows_from_block(block_text: str, block_id: str) -> list[TableRow]:
    row_texts = _split_rows(block_text)
    rows: list[TableRow] = [
        TableRow(index=i, kind=RowKind.UNKNOWN, raw_text=rt.strip())
        for i, rt in enumerate(row_texts)
    ]
    for row in rows:
        row.kind = _row_kind(row.raw_text)

    # key-value cells: scan the WHOLE block (label and value may sit on
    # adjacent lines: "Wavelength(nm)\\n355"); map to row by line number
    covered_lines: dict[int, list[tuple[int, int]]] = {}
    for m in _TABLE_CELL_RE.finditer(block_text):
        hint = parameter_from_label(m.group(1))
        unit = normalize_unit(m.group(2))
        if hint == "unknown" or unit is None:
            continue
        line_no = block_text.count("\n", 0, m.start())
        if line_no >= len(rows):
            continue
        rows[line_no].cells.append(
            TableCell(
                value=float(m.group(3).replace(",", ".")),
                value2=float(m.group(4).replace(",", ".")) if m.group(4) else None,
                unit=unit,
                parameter=hint,
                raw_text=m.group(0),
                source_block_id=block_id,
                source_row=line_no,
            )
        )
        covered_lines.setdefault(line_no, []).append((m.start(), m.end()))

    for row in rows:
        text = row.raw_text
        for mention in find_mentions(text):
            if any(
                mention.start >= s and mention.end <= e
                for s, e in covered_lines.get(row.index, [])
            ):
                continue
            unit = normalize_unit(mention.unit)
            if unit is None:
                continue
            for value in mention.values:
                row.cells.append(
                    TableCell(
                        value=value,
                        unit=unit,
                        parameter=mention.parameter_hint or "unknown",
                        raw_text=mention.raw_text,
                        source_block_id=block_id,
                        source_row=row.index,
                    )
                )
    return [r for r in rows if r.cells or r.kind == RowKind.HEADER]


def classify_table(region: TableRegion, document) -> TableRegion:
    rows: list[TableRow] = []
    for block in region.blocks:
        rows.extend(_parse_rows_from_block(block.text, block.block_id()))

    # A1 fallback: header-column parsing for separated-header tables whose
    # standard cell parsing produced no rows (e.g. "Frequency" header block +
    # "(Hz)" block + row-numbered numeric row blocks). Only applied when the
    # standard path found nothing, so correctly parsed tables are untouched.
    if not any(r.cells for r in rows):
        header_blocks = []
        data_blocks = []
        seen_data = False
        for block in region.blocks:
            from ultrafast_ingestion.tables.detect import _is_table_like_block

            if block.block_type == "caption":
                continue
            is_data = _is_table_like_block(block)
            if is_data:
                seen_data = True
            if seen_data:
                data_blocks.append(block)
            else:
                header_blocks.append(block)
        if data_blocks:
            header_rows = _parse_header_column_rows(region, header_blocks, data_blocks)
            if header_rows:
                rows = header_rows

    region.rows = rows
    cell_rows = [r for r in rows if r.cells]
    reasons: list[str] = []

    has_this_work = any(r.kind == RowKind.THIS_WORK for r in cell_rows)
    has_reference = any(r.kind == RowKind.REFERENCE for r in cell_rows)
    if has_this_work or has_reference:
        region.semantic_type = TableSemanticType.COMPARISON_TABLE
        reasons.append("has_this_work" if has_this_work else "has_reference_rows")
    elif cell_rows and all(
        len(r.cells) == 1 and r.cells[0].parameter != "unknown" for r in cell_rows
    ):
        region.semantic_type = TableSemanticType.KEY_VALUE_SETUP
        reasons.append("single-parameter-cell rows")
    elif cell_rows and all(len(r.cells) >= 2 for r in cell_rows):
        region.semantic_type = TableSemanticType.EXPERIMENT_ROWS
        reasons.append("multi-cell rows")
    else:
        region.semantic_type = TableSemanticType.UNKNOWN
        reasons.append("ambiguous layout")
    region.classification_reasons = reasons
    return region
