"""规则层候选检测：正则/词典 → candidate mentions。

只做发现（raw_text/canonical/页码/证据 span），不裁决语义角色。
语义角色由 semantic_roles（LLM）决定；无 LLM 时保持 role=unknown（abstain）。
"""

from __future__ import annotations

import re
from typing import Any

from ultrafast_knowledge.literature.extraction.registry import (
    GEOMETRY_PATTERNS,
    GRADE_PATTERNS,
    LASER_TYPE_PATTERNS,
    MATERIAL_PATTERNS,
    PROCESS_PATTERNS,
    PULSE_WIDTH_RE,
    WAVELENGTH_RE,
)
from ultrafast_knowledge.literature.extraction.schemas import (
    MaterialMention,
    MaterialRole,
    NumericEvidence,
    ProcessMention,
    ProcessRole,
)
from ultrafast_knowledge.literature.schemas import LiteratureSectionData
from ultrafast_shared.ontology import resolve_material

RULE_CONFIDENCE = 0.5


def _section_matches(section: LiteratureSectionData, pattern: re.Pattern[str]) -> list[tuple[int, int, str]]:
    return [(match.start(), match.end(), match.group(0)) for match in pattern.finditer(section.text)]


def detect_material_candidates(sections: list[LiteratureSectionData]) -> list[MaterialMention]:
    mentions: list[MaterialMention] = []
    seen: set[tuple[str, str, int]] = set()
    for section in sections:
        for canonical, pattern in MATERIAL_PATTERNS:
            for start, end, raw in _section_matches(section, pattern):
                key = (canonical, section.section_id, start)
                if key in seen:
                    continue
                seen.add(key)
                mention = MaterialMention(
                    raw_text=raw[:200],
                    canonical_material_id=canonical,
                    role=MaterialRole.UNKNOWN,
                    page=section.page_start,
                    section_id=section.section_id,
                    section_type=section.section_type,
                    evidence_span=(start, end),
                    extraction_method="rule",
                    confidence=RULE_CONFIDENCE,
                )
                mentions.append(mention)
    return _dedupe_by_occurrence(mentions)


def detect_process_candidates(sections: list[LiteratureSectionData]) -> list[ProcessMention]:
    mentions: list[ProcessMention] = []
    seen: set[tuple[str, str, int]] = set()
    for section in sections:
        for canonical, pattern in PROCESS_PATTERNS:
            for start, end, raw in _section_matches(section, pattern):
                key = (canonical, section.section_id, start)
                if key in seen:
                    continue
                seen.add(key)
                mentions.append(
                    ProcessMention(
                        raw_text=raw[:200],
                        canonical_process_id=canonical,
                        role=ProcessRole.UNKNOWN,
                        page=section.page_start,
                        section_id=section.section_id,
                        section_type=section.section_type,
                        evidence_span=(start, end),
                        extraction_method="rule",
                        confidence=RULE_CONFIDENCE,
                    )
                )
    return _dedupe_by_occurrence(mentions)


def _dedupe_by_occurrence(mentions: list[Any]) -> list[Any]:
    """Remove only duplicate detections of the same source occurrence.

    A canonical material/process can legitimately appear more than once on one
    page.  Page-level deduplication erased distinct evidence spans and sections.
    """
    seen: set[tuple[str, int | None, str | None, tuple[int, int] | None]] = set()
    result: list[Any] = []
    for mention in mentions:
        key = (
            mention.canonical_material_id
            if hasattr(mention, "canonical_material_id")
            else mention.canonical_process_id,
            mention.page,
            mention.section_id,
            mention.evidence_span,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(mention)
    return result


def detect_laser_type(text: str) -> str:
    for label, pattern in LASER_TYPE_PATTERNS:
        if pattern.search(text):
            return label
    return ""


def detect_wavelength(text: str) -> NumericEvidence | None:
    for match in WAVELENGTH_RE.finditer(text):
        return NumericEvidence(
            value=float(match.group(1)),
            unit="nm",
            raw_evidence=match.group(0),
        )
    return None


def detect_pulse_width(text: str) -> NumericEvidence | None:
    for match in PULSE_WIDTH_RE.finditer(text):
        unit = match.group(2).lower()
        if unit == "fs" or unit == "ps" or unit == "ns":
            value = float(match.group(1))
        else:
            continue
        return NumericEvidence(value=value, unit=unit, raw_evidence=match.group(0))
    return None


def detect_grades(text: str) -> dict[str, str]:
    grades: dict[str, str] = {}
    for canonical, patterns in GRADE_PATTERNS:
        for pattern in patterns:
            for match in pattern.finditer(text):
                grades[canonical] = match.group(0)
                break
            if canonical in grades:
                break
    return grades


def detect_geometry(text: str) -> str:
    for canonical, pattern in GEOMETRY_PATTERNS:
        if pattern.search(text):
            return canonical
    return ""


def detect_grade_for_material(text: str, canonical_material_id: str) -> str:
    for canonical, patterns in GRADE_PATTERNS:
        if canonical != canonical_material_id:
            continue
        for pattern in patterns:
            for match in pattern.finditer(text):
                return match.group(0)
    return ""


def resolve_mention_canonical(raw_text: str) -> str | None:
    """raw text → canonical material id（候选层兜底，供 LLM 输出归一使用）。"""
    if not raw_text:
        return None
    resolved = resolve_material(raw_text)
    if resolved:
        return resolved
    for canonical, pattern in MATERIAL_PATTERNS:
        if pattern.search(raw_text):
            return canonical
    return None
