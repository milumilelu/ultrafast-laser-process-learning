"""Scientific table semantics (Layer 3, step 1).

TableSemanticType decides how table content may generate candidate
edges. A COMPARISON_TABLE must never seed a processing-condition
cluster (except explicit "This work" rows).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ultrafast_ingestion.models.document import PageBlock, ScientificDocument


class TableSemanticType(StrEnum):
    KEY_VALUE_SETUP = "KEY_VALUE_SETUP"      # whole table = one condition
    EXPERIMENT_ROWS = "EXPERIMENT_ROWS"      # each row = one condition
    FACTOR_LEVELS = "FACTOR_LEVELS"          # parameter levels / sweep
    RESULT_MATRIX = "RESULT_MATRIX"          # outcomes, not condition source
    COMPARISON_TABLE = "COMPARISON_TABLE"    # refs vs this-work; refs not conditions
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class RowKind(StrEnum):
    THIS_WORK = "THIS_WORK"
    REFERENCE = "REFERENCE"
    HEADER = "HEADER"
    DATA = "DATA"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class TableCell:
    value: float
    unit: str  # canonical
    parameter: str
    raw_text: str
    source_block_id: str
    source_row: int
    value2: float | None = None  # range end (e.g. fluence 2.3-7.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "value2": self.value2,
            "unit": self.unit,
            "parameter": self.parameter,
            "raw_text": self.raw_text,
            "source_block_id": self.source_block_id,
            "source_row": self.source_row,
        }


@dataclass(slots=True)
class TableRow:
    index: int
    kind: RowKind
    raw_text: str
    cells: list[TableCell] = field(default_factory=list)


@dataclass(slots=True)
class TableRegion:
    table_id: str
    semantic_type: TableSemanticType
    caption_block_id: str = ""
    blocks: list[PageBlock] = field(default_factory=list)
    rows: list[TableRow] = field(default_factory=list)
    classification_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "semantic_type": str(self.semantic_type),
            "caption_block_id": self.caption_block_id,
            "block_ids": [b.block_id() for b in self.blocks],
            "rows": [
                {
                    "index": r.index,
                    "kind": str(r.kind),
                    "raw_text": r.raw_text,
                    "cells": [c.to_dict() for c in r.cells],
                }
                for r in self.rows
            ],
            "classification_reasons": self.classification_reasons,
        }


def table_regions(document: ScientificDocument) -> list[TableRegion]:
    """Detect table regions and classify their semantics."""
    from ultrafast_ingestion.tables.classify import classify_table
    from ultrafast_ingestion.tables.detect import detect_table_regions

    regions = detect_table_regions(document)
    return [classify_table(region, document) for region in regions]
