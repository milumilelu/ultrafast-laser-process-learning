"""Structure-aware DiscoveryWindow builder (O1, contract §2).

Structural rules (frozen):
  1. never crosses papers
  2. section boundary preferred cut
  3. paragraph/block boundary preferred
  4. table + caption kept atomic
  5. figure caption kept atomic
  6. oversized single block/table gets its own window (fallback)
  7. token budget never breaks provenance
  8. section_type only routes priority - never excludes text
     (except REFERENCES -> citation routing, out of scientific scope)

Gates G1-G7 verified in tests/test_discovery_windows*.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ultrafast_ingestion.discovery.models import (
    DiscoveryWindow,
    DiscoveryWindowConfig,
)
from ultrafast_ingestion.models.document import ScientificDocument
from ultrafast_ingestion.models.provenance import stable_hash
from ultrafast_ingestion.tables.models import TableRegion

# section_type -> routing_hint (routing, never exclusion)
_ROUTING_BY_SECTION: dict[str, str] = {
    "methods": "processing",
    "results": "effect_mechanism",
    "discussion": "effect_mechanism",
    "conclusion": "effect_mechanism",
    "introduction": "material_comparison",
    "supplementary": "general",
    "misc": "general",
    "preamble": "general",
    "abstract": "general",
    "section": "general",
}

_EXCLUDED_SECTIONS = frozenset({"references"})

# caption/table units always route to structured priority and never merge
# with neighbouring body text (rules 4/5)
_STRUCTURED_HINT = "structured"
_STRUCTURED_KINDS = frozenset({"caption", "table"})


@dataclass(frozen=True, slots=True)
class _AtomicUnit:
    kind: str  # body | heading | caption | table
    block_ids: tuple[str, ...]
    text: str
    section_path: str
    page_range: tuple[int, int]
    routing_hint: str
    caption_block_ids: tuple[str, ...] = ()
    table_refs: tuple[str, ...] = ()


def _section_type(section_path: str) -> str:
    parts = section_path.split("/")
    return parts[1] if len(parts) >= 2 else "section"


def _hint_for(section_path: str, kind: str) -> str:
    if kind in _STRUCTURED_KINDS:
        return _STRUCTURED_HINT
    return _ROUTING_BY_SECTION.get(_section_type(section_path), "general")


def _words(text: str) -> int:
    return len(text.split())


class DiscoveryWindowBuilder:
    """Deterministic structure-aware window builder (G1)."""

    def __init__(
        self,
        config: DiscoveryWindowConfig | None = None,
        regions: list[TableRegion] | None = None,
    ) -> None:
        self.config = config or DiscoveryWindowConfig()
        self.regions = regions or []

    def build(self, document: ScientificDocument) -> list[DiscoveryWindow]:
        units = [u for u in self._atomic_units(document) if self._eligible(u)]
        return [
            self._window_from_units(document, group, units)
            for group in self._group_units(units)
        ]

    def coverage(self, document: ScientificDocument) -> dict[str, Any]:
        """Discovery Text Coverage (contract §13): covered eligible text / all eligible text."""
        units = [u for u in self._atomic_units(document) if self._eligible(u)]
        windows = self.build(document)
        covered_blocks = {b for w in windows for b in w.block_ids}
        covered_words = sum(_words(u.text) for u in units if u.block_ids[0] in covered_blocks)
        total_words = sum(_words(u.text) for u in units)
        return {
            "covered_words": covered_words,
            "eligible_words": total_words,
            "coverage": covered_words / total_words if total_words else 1.0,
            "window_count": len(windows),
        }

    # ---- internal -----------------------------------------------------

    def _atomic_units(self, document: ScientificDocument) -> list[_AtomicUnit]:
        blocks = [block for page in document.pages for block in page]
        region_units: dict[str, _AtomicUnit] = {}
        region_block_ids: set[str] = set()
        for region in self.regions:
            if not region.blocks:
                continue
            ids = tuple(b.block_id() for b in region.blocks)
            first = region.blocks[0]
            region_block_ids.update(ids)
            region_units[first.block_id()] = _AtomicUnit(
                kind="table",
                block_ids=ids,
                text="\n\n".join(b.text for b in region.blocks),
                section_path=first.section_path,
                page_range=(
                    min(b.page_index for b in region.blocks),
                    max(b.page_index for b in region.blocks),
                ),
                routing_hint=_STRUCTURED_HINT,
                table_refs=(region.table_id,),
            )

        units: list[_AtomicUnit] = []
        for block in blocks:
            bid = block.block_id()
            if bid in region_block_ids:
                if bid in region_units:  # emit the atomic table unit once
                    units.append(region_units[bid])
                continue
            units.append(
                _AtomicUnit(
                    kind=block.block_type,
                    block_ids=(bid,),
                    text=block.text,
                    section_path=block.section_path,
                    page_range=(block.page_index, block.page_index),
                    routing_hint=_hint_for(block.section_path, block.block_type),
                    caption_block_ids=(bid,) if block.block_type == "caption" else (),
                )
            )
        return units

    def _eligible(self, unit: _AtomicUnit) -> bool:
        return _section_type(unit.section_path) not in _EXCLUDED_SECTIONS

    def _group_units(self, units: list[_AtomicUnit]) -> list[list[_AtomicUnit]]:
        """Aggregate body/heading units per section up to the token budget;
        caption/table units stay atomic and standalone (rules 2/4/5)."""
        groups: list[list[_AtomicUnit]] = []
        current: list[_AtomicUnit] = []
        current_words = 0
        target = self.config.target_window_tokens
        max_tokens = self.config.max_window_tokens

        def flush() -> None:
            nonlocal current, current_words
            if current:
                groups.append(current)
                current = []
                current_words = 0

        for unit in units:
            if unit.kind in _STRUCTURED_KINDS:
                flush()
                groups.append([unit])
                continue
            words = _words(unit.text)
            if words > max_tokens:
                flush()
                groups.append([unit])  # oversized fallback (rule 6)
                continue
            if current and (
                current[0].section_path != unit.section_path  # rule 2
                or current_words + words > target
            ):
                flush()
            current.append(unit)
            current_words += words
        flush()
        return groups

    def _window_from_units(
        self,
        document: ScientificDocument,
        group: list[_AtomicUnit],
        all_units: list[_AtomicUnit],
    ) -> DiscoveryWindow:
        block_ids = tuple(b for u in group for b in u.block_ids)
        window_id = stable_hash(
            document.document_version_id,
            *block_ids,
            self.config.config_version(),
        )
        first = group[0]
        idx = all_units.index(first)
        prev_unit = all_units[idx - 1] if idx > 0 else None
        next_unit = all_units[idx + len(group)] if idx + len(group) < len(all_units) else None
        return DiscoveryWindow(
            window_id=window_id,
            paper_id=document.paper_id,
            document_version_id=document.document_version_id,
            window_config_version=self.config.config_version(),
            section_path=first.section_path,
            block_ids=block_ids,
            page_range=(
                min(u.page_range[0] for u in group),
                max(u.page_range[1] for u in group),
            ),
            text="\n\n".join(u.text for u in group),
            table_refs=tuple(r for u in group for r in u.table_refs),
            caption_refs=tuple(c for u in group for c in u.caption_block_ids),
            preceding_context=self._context_text(prev_unit, tail=True) if prev_unit else "",
            following_context=self._context_text(next_unit, tail=False) if next_unit else "",
            routing_hint=first.routing_hint,
        )

    def _context_text(self, unit: _AtomicUnit | None, tail: bool) -> str:
        if unit is None:
            return ""
        words = unit.text.split()
        limit = self.config.context_tokens
        if len(words) <= limit:
            return unit.text
        return " ".join(words[-limit:] if tail else words[:limit])
