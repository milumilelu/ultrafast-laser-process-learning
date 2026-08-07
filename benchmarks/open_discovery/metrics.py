"""O9 ablation metrics (contract §14).

Two headline metrics:
  Incremental Open Recall     = LLM-found gold candidates the deterministic
                                path never discovered
  Unsupported Candidate Rate  = system candidates the source cannot support
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GoldCandidate:
    paper_id: str
    candidate_kind: str
    concept_label: str
    verbatim_quote: str
    block_id: str = ""
    char_start: int | None = None
    char_end: int | None = None


def _spans_overlap(
    a_block: str, a_start: int | None, a_end: int | None,
    b_block: str, b_start: int | None, b_end: int | None,
) -> bool:
    if a_block and b_block and a_block != b_block:
        return False
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return False
    return a_start <= b_end and b_start <= a_end


def match_gold(
    gold: GoldCandidate,
    system_candidates: list,
    quote_ok: bool = True,
) -> bool:
    """Span-overlap match (same block + overlapping char range); fall back to
    normalized-quote equality when char offsets are missing on either side."""
    for candidate in system_candidates:
        if candidate.paper_id != gold.paper_id:
            continue
        if quote_ok and not candidate.provenance_anchors:
            if _quote_equal(candidate.raw_statement, gold.verbatim_quote):
                return True
            continue
        anchor = candidate.provenance_anchors[0] if candidate.provenance_anchors else None
        if anchor is None:
            continue
        if _spans_overlap(
            anchor.block_id, anchor.char_start, anchor.char_end,
            gold.block_id, gold.char_start, gold.char_end,
        ):
            return True
    return False


def _quote_equal(a: str, b: str) -> bool:
    from ultrafast_ingestion.models.provenance import normalize_quote

    return bool(a and b) and normalize_quote(a) == normalize_quote(b)


def compute_metrics(
    gold: list[GoldCandidate],
    deterministic_candidates: list,
    hybrid_candidates: list,
    unsupported: list,
) -> dict:
    """Ablation metrics over one paper set.

    deterministic_candidates: candidates from the deterministic path (ledger
        mentions+cells; unassigned included).
    hybrid_candidates: candidates after hybrid merge (deterministic + LLM).
    unsupported: hybrid candidates whose grounding failed / verification
        contradicted (counted as unsupported candidates).
    """
    gold_found_det = sum(1 for g in gold if match_gold(g, deterministic_candidates))
    gold_found_hybrid = sum(1 for g in gold if match_gold(g, hybrid_candidates))

    det_ids = {c.candidate_id for c in deterministic_candidates}
    hybrid_only = [c for c in hybrid_candidates if c.candidate_id not in det_ids]
    incremental_found = sum(
        1 for g in gold if match_gold(g, hybrid_only) and not match_gold(g, deterministic_candidates)
    )

    hybrid_count = len(hybrid_candidates)
    proposed = hybrid_count + len(unsupported)
    unsupported_rate = len(unsupported) / proposed if proposed else 0.0
    total = len(gold)
    return {
        "gold_candidates": total,
        "deterministic_recall": gold_found_det / total if total else 0.0,
        "hybrid_recall": gold_found_hybrid / total if total else 0.0,
        "incremental_open_recall": incremental_found / total if total else 0.0,
        "unsupported_candidate_rate": unsupported_rate,
        "unsupported_count": len(unsupported),
        "proposed_count": proposed,
        "deterministic_candidate_count": len(deterministic_candidates),
        "hybrid_candidate_count": hybrid_count,
    }
