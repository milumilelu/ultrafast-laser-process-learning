"""Value+unit mention patterns (Layer 2, deterministic only)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ultrafast_ingestion.mentions.models import MentionValueType
from ultrafast_ingestion.mentions.units import UNIT_PATTERN, parameter_from_label

_NUM = r"(\d+(?:[.,]\d+)?)"
_NUM_START = r"(?<![A-Za-z0-9])"
_RANGE_RE = re.compile(
    rf"{_NUM_START}{_NUM}\s*(?:-|to|–|—)\s*{_NUM}\s*({UNIT_PATTERN.pattern})", re.IGNORECASE
)
# "2 nJ/pulse to 445 nJ/pulse" / "2 nJ to 445 nJ": unit on BOTH ends
_DUAL_UNIT_RANGE_RE = re.compile(
    rf"{_NUM_START}{_NUM}\s*({UNIT_PATTERN.pattern})\s*(?:/pulse|per pulse)?\s*(?:-|to|–|—)\s*"
    rf"{_NUM}\s*({UNIT_PATTERN.pattern})",
    re.IGNORECASE,
)
_LIST_RE = re.compile(
    rf"{_NUM_START}{_NUM}\s*(?:and|&|,)\s*{_NUM}\s*({UNIT_PATTERN.pattern})", re.IGNORECASE
)
_SCALAR_RE = re.compile(rf"{_NUM_START}{_NUM}\s*({UNIT_PATTERN.pattern})", re.IGNORECASE)

# dimensionless process parameters (no unit in text)
_NA_RE = re.compile(r"(?:numerical aperture|na)\s*[=:≈~]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_M2_RE = re.compile(r"M\s*[²2]\s*[=:≈~]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_MAGNIFICATION_RE = re.compile(r"(\d+)\s*×\s*(?:magnification)?", re.IGNORECASE)

# parameter tables: "Spot diameter (um) 19" / "Fluence range (J/cm2) 2.3-7.0"
_TABLE_CELL_RE = re.compile(
    rf"([A-Za-z][A-Za-z /\-]{{1,40}})\(({UNIT_PATTERN.pattern})\)\s*[:=]?\s*"
    r"(\d+(?:[.,]\d+)?)(?:\s*(?:-|–|—|to)\s*(\d+(?:[.,]\d+)?))?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RawMention:
    raw_text: str
    values: list[float]
    value_type: MentionValueType
    unit: str  # as written
    start: int
    end: int
    parameter_hint: str = ""


def _parse_number(text: str) -> float:
    return float(text.replace(",", "."))


def find_mentions(text: str) -> list[RawMention]:
    """All candidate value+unit mentions, no context filtering.

    Range/list forms are checked first (longer patterns win).
    Dimensionless parameters (NA / M2 / magnification) have unit sentinels
    that normalize to canonical units in units.py.
    """
    mentions: list[RawMention] = []

    for m in _DUAL_UNIT_RANGE_RE.finditer(text):
        mentions.append(
            RawMention(
                raw_text=m.group(0),
                values=[_parse_number(m.group(1)), _parse_number(m.group(3))],
                value_type=MentionValueType.RANGE,
                unit=m.group(2),
                start=m.start(),
                end=m.end(),
            )
        )
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
    # dimensionless
    for pattern, sentinel in ((_NA_RE, "NA"), (_M2_RE, "M2"), (_MAGNIFICATION_RE, "MAG")):
        for m in pattern.finditer(text):
            mentions.append(
                RawMention(
                    raw_text=m.group(0),
                    values=[_parse_number(m.group(1))],
                    value_type=MentionValueType.SCALAR,
                    unit=sentinel,
                    start=m.start(),
                    end=m.end(),
                )
            )
    # parameter tables: label (unit) value [range]; only known labels
    for m in _TABLE_CELL_RE.finditer(text):
        hint = parameter_from_label(m.group(1))
        if hint == "unknown":
            continue
        values = [_parse_number(m.group(3))]
        value_type = MentionValueType.SCALAR
        if m.group(4):
            values.append(_parse_number(m.group(4)))
            value_type = MentionValueType.RANGE
        mentions.append(
            RawMention(
                raw_text=m.group(0),
                values=values,
                value_type=value_type,
                unit=m.group(2),
                start=m.start(),
                end=m.end(),
                parameter_hint=hint,
            )
        )
    # drop mentions fully contained inside another mention (range/list wins)
    mentions.sort(key=lambda x: (x.start, -(x.end - x.start)))
    filtered: list[RawMention] = []
    for mention in mentions:
        if any(
            mention.start >= other.start
            and mention.end <= other.end
            and mention is not other
            for other in mentions
        ):
            continue
        filtered.append(mention)
    return filtered
