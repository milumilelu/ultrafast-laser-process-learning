"""Value+unit mention patterns (Layer 2, deterministic only)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ultrafast_ingestion.mentions.models import MentionValueType
from ultrafast_ingestion.mentions.units import UNIT_PATTERN

_NUM = r"(\d+(?:[.,]\d+)?)"
_RANGE_RE = re.compile(
    rf"{_NUM}\s*(?:-|to|–|—)\s*{_NUM}\s*({UNIT_PATTERN.pattern})", re.IGNORECASE
)
_LIST_RE = re.compile(
    rf"{_NUM}\s*(?:and|&|,)\s*{_NUM}\s*({UNIT_PATTERN.pattern})", re.IGNORECASE
)
_SCALAR_RE = re.compile(rf"{_NUM}\s*({UNIT_PATTERN.pattern})", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RawMention:
    raw_text: str
    values: list[float]
    value_type: MentionValueType
    unit: str  # as written
    start: int
    end: int


def _parse_number(text: str) -> float:
    return float(text.replace(",", "."))


def find_mentions(text: str) -> list[RawMention]:
    """All candidate value+unit mentions, no context filtering.

    Range/list forms are checked first (longer patterns win).
    """
    mentions: list[RawMention] = []

    for m in _RANGE_RE.finditer(text):
        mentions.append(
            RawMention(
                raw_text=m.group(0),
                values=[_parse_number(m.group(1)), _parse_number(m.group(2))],
                value_type=MentionValueType.RANGE,
                unit=m.group(3),
                start=m.start(),
                end=m.end(),
            )
        )
    for m in _LIST_RE.finditer(text):
        mentions.append(
            RawMention(
                raw_text=m.group(0),
                values=[_parse_number(m.group(1)), _parse_number(m.group(2))],
                value_type=MentionValueType.LIST,
                unit=m.group(3),
                start=m.start(),
                end=m.end(),
            )
        )
    for m in _SCALAR_RE.finditer(text):
        mentions.append(
            RawMention(
                raw_text=m.group(0),
                values=[_parse_number(m.group(1))],
                value_type=MentionValueType.SCALAR,
                unit=m.group(2),
                start=m.start(),
                end=m.end(),
            )
        )
    # drop mentions fully contained inside another mention (range/list wins)
    mentions.sort(key=lambda x: (x.start, -(x.end - x.start)))
    filtered: list[RawMention] = []
    for m in mentions:
        if any(m.start >= o.start and m.end <= o.end and m is not o for o in mentions):
            continue
        filtered.append(m)
    return filtered
