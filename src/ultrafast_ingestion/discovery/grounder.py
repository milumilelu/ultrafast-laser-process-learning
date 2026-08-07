"""CandidateGrounder (O3 - first hard gate, contract §5).

Fully deterministic verbatim scan over the discovery window's blocks:

    EXACT               verbatim hit inside one block
    NORMALIZED_EXACT    normalize_quote hit inside one block
    CROSS_BLOCK_EXACT   normalized hit across adjacent window blocks
    FUZZY_UNIQUE        conservative token-window match, unique position
    AMBIGUOUS           multiple candidate positions
    UNRESOLVED          nothing found

Gate: EXACT/NORMALIZED/CROSS_BLOCK -> PASS; FUZZY_UNIQUE -> CONDITIONAL
(mandatory verification); AMBIGUOUS/UNRESOLVED -> FAIL (never promoted).

fuzzy_token_coverage is a pilot-calibrated default - NOT a frozen contract
value (unresolved is safer than a wrong bbox).
"""

from __future__ import annotations

from itertools import pairwise

from ultrafast_ingestion.candidates.models import GroundingStatus
from ultrafast_ingestion.discovery.models import (
    CandidateSkeleton,
    DiscoveryWindow,
    GroundingConfig,
    GroundingMatchType,
    GroundingResult,
)
from ultrafast_ingestion.models.document import PageBlock, ScientificDocument
from ultrafast_ingestion.models.provenance import normalize_quote


class CandidateGrounder:
    def __init__(self, config: GroundingConfig | None = None) -> None:
        self.config = config or GroundingConfig()

    def ground(
        self,
        document: ScientificDocument,
        window: DiscoveryWindow,
        skeleton: CandidateSkeleton,
    ) -> GroundingResult:
        quote = skeleton.verbatim_quote.strip()
        if not quote:
            return self._result(skeleton, GroundingMatchType.UNRESOLVED, "empty quote")

        blocks = [
            document.blocks_by_id[bid]
            for bid in window.block_ids
            if bid in document.blocks_by_id
        ]
        if not blocks:
            return self._result(
                skeleton, GroundingMatchType.UNRESOLVED, "window has no blocks"
            )

        # 1. EXACT (verbatim, char-level) ---------------------------------
        exact_hits: list[tuple[PageBlock, int, int]] = []
        for block in blocks:
            exact_hits.extend(self._exact_hits(block, quote))
        if exact_hits:
            if len(exact_hits) == 1:
                block, start, end = exact_hits[0]
                return self._result(
                    skeleton,
                    GroundingMatchType.EXACT,
                    quote,
                    anchor=document.anchor_for(block, start, end),
                    hit_count=1,
                    block_id=block.block_id(),
                )
            return self._result(
                skeleton,
                GroundingMatchType.AMBIGUOUS,
                quote,
                hit_count=len(exact_hits),
            )

        # 2. NORMALIZED_EXACT (whitespace/case-insensitive) ----------------
        norm_quote = normalize_quote(quote)
        norm_hits = [b for b in blocks if normalize_quote(b.text).find(norm_quote) != -1]
        if norm_hits:
            if len(norm_hits) == 1:
                return self._result(
                    skeleton,
                    GroundingMatchType.NORMALIZED_EXACT,
                    quote,
                    anchor=document.anchor_for(norm_hits[0]),
                    hit_count=1,
                    block_id=norm_hits[0].block_id(),
                )
            return self._result(
                skeleton,
                GroundingMatchType.AMBIGUOUS,
                quote,
                hit_count=len(norm_hits),
            )

        # 3. CROSS_BLOCK_EXACT (adjacent window blocks) --------------------
        cross_hits: list[tuple[PageBlock, PageBlock]] = []
        for a, b in pairwise(blocks):
            joined = normalize_quote(a.text + "\n" + b.text)
            if joined.find(norm_quote) != -1:
                cross_hits.append((a, b))
        if cross_hits:
            if len(cross_hits) == 1:
                a, b = cross_hits[0]
                return self._result(
                    skeleton,
                    GroundingMatchType.CROSS_BLOCK_EXACT,
                    quote,
                    anchor=document.anchor_for(a),
                    hit_count=1,
                    block_id=f"{a.block_id()} + {b.block_id()}",
                )
            return self._result(
                skeleton,
                GroundingMatchType.AMBIGUOUS,
                quote,
                hit_count=len(cross_hits),
            )

        # 4. FUZZY_UNIQUE (conservative token-window match) ----------------
        fuzzy_hits: list[tuple[PageBlock, float]] = []
        for block in blocks:
            score = self._fuzzy_score(block.text, quote)
            if score is not None:
                fuzzy_hits.append((block, score))
        if fuzzy_hits:
            unique_blocks = {b.block_id() for b, _ in fuzzy_hits}
            if len(unique_blocks) == 1 and len(fuzzy_hits) == 1:
                block, score = fuzzy_hits[0]
                return self._result(
                    skeleton,
                    GroundingMatchType.FUZZY_UNIQUE,
                    quote,
                    anchor=document.anchor_for(block),
                    hit_count=1,
                    block_id=block.block_id(),
                    fuzzy_score=round(score, 4),
                )
            return self._result(
                skeleton,
                GroundingMatchType.AMBIGUOUS,
                quote,
                hit_count=len(fuzzy_hits),
            )

        return self._result(skeleton, GroundingMatchType.UNRESOLVED, quote)

    # ---- internals ------------------------------------------------------

    def _exact_hits(self, block: PageBlock, quote: str) -> list[tuple[PageBlock, int, int]]:
        hits: list[tuple[PageBlock, int, int]] = []
        start = 0
        while True:
            i = block.text.find(quote, start)
            if i < 0:
                return hits
            hits.append((block, i, i + len(quote)))
            start = i + 1

    def _fuzzy_score(self, text: str, quote: str) -> float | None:
        """Best token-window overlap ratio; None if below threshold."""
        q_tokens = normalize_quote(quote).split()
        t_tokens = normalize_quote(text).split()
        if not q_tokens or len(t_tokens) < len(q_tokens):
            return None
        best = 0.0
        for i in range(len(t_tokens) - len(q_tokens) + 1):
            window = t_tokens[i : i + len(q_tokens)]
            overlap = sum(1 for a, b in zip(q_tokens, window) if a == b)
            best = max(best, overlap / len(q_tokens))
        return best if best >= self.config.fuzzy_token_coverage else None

    def _result(
        self,
        skeleton: CandidateSkeleton,
        match_type: GroundingMatchType,
        matched_quote: str,
        anchor=None,
        **detail,
    ) -> GroundingResult:
        status = (
            GroundingStatus.GROUNDED
            if match_type in (
                GroundingMatchType.EXACT,
                GroundingMatchType.NORMALIZED_EXACT,
                GroundingMatchType.CROSS_BLOCK_EXACT,
                GroundingMatchType.FUZZY_UNIQUE,
            )
            else GroundingStatus.GROUNDING_UNRESOLVED
        )
        return GroundingResult(
            skeleton_id=skeleton.local_id,
            match_type=match_type,
            anchor=anchor,
            matched_quote=matched_quote,
            status=status,
            detail=detail,
        )
