"""ConditionMention extraction over a ScientificDocument (Layer 2).

Answers only: "is there a possible process-parameter mention in the text?"
Never answers: "which ExperimentalCondition does it belong to?"
"""

from __future__ import annotations

import hashlib
import re

from ultrafast_ingestion.mentions.context import classify
from ultrafast_ingestion.mentions.models import ConditionMention
from ultrafast_ingestion.mentions.patterns import find_mentions
from ultrafast_ingestion.mentions.units import normalize_unit
from ultrafast_ingestion.models.document import PageBlock, ScientificDocument

WINDOW_CHARS = 120


def _mention_id(doc: ScientificDocument, block: PageBlock, start: int, end: int) -> str:
    raw = f"{block.block_id()}:{start}:{end}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def extract_mentions(doc: ScientificDocument) -> list[ConditionMention]:
    mentions: list[ConditionMention] = []
    for page in doc.pages:
        for idx, block in enumerate(page):
            text = block.text
            # cross-block context: previous/next block fragments (sentence
            # may span line-wrapped blocks in two-column layouts)
            prev_tail = page[idx - 1].text[-140:] if idx > 0 else ""
            next_head = page[idx + 1].text[:140] if idx + 1 < len(page) else ""
            context = prev_tail + text + next_head
            ctx_offset = len(prev_tail)
            for raw in find_mentions(text):
                unit = normalize_unit(raw.unit)
                if unit is None:
                    continue
                win_start = max(0, raw.start - WINDOW_CHARS)
                win_end = min(len(text), raw.end + WINDOW_CHARS)
                window = context[max(0, ctx_offset + win_start) : ctx_offset + win_end]
                # offsets relative to the window slice (context matching)
                rel_start = ctx_offset + raw.start - max(0, ctx_offset + win_start)
                rel_end = ctx_offset + raw.end - max(0, ctx_offset + win_start)
                status, context_class, param, reason = classify(
                    raw.raw_text,
                    unit,
                    rel_start,
                    rel_end,
                    window=window,
                )
                anchor = doc.anchor_for(block, raw.start, raw.end)
                mentions.append(
                    ConditionMention(
                        mention_id=_mention_id(doc, block, raw.start, raw.end),
                        parameter=param,
                        raw_text=raw.raw_text,
                        values=raw.values,
                        value_type=raw.value_type,
                        normalized_unit=unit,
                        context_class=context_class,
                        acceptance_status=status,
                        rejection_reason=reason,
                        anchor=anchor,
                    )
                )
    mentions.sort(key=lambda m: (m.anchor.pdf_page_index if m.anchor else 0, m.raw_text))
    return mentions
