"""Anchor-based dedupe (O5/O7) - contract §9.

Strong dedupe key: (paper_id, anchored span, candidate_kind).
Same anchored span (overlapping block+char range) + same kind -> merge into
one ScientificCandidate carrying a discovery_methods list.

Cross-span semantic similarity NEVER deletes a candidate (D8): different
spans are kept as separate candidates; duplicate hypotheses are O7
CandidateRelation territory, not candidate properties.
"""

from __future__ import annotations

from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.candidates.models import (
    CandidateKind,
    CandidateLedger,
    CandidateMapping,
    CandidateSourceType,
    ScientificCandidate,
)


def _span_overlap(a: ScientificCandidate, b: ScientificCandidate) -> bool:
    """Same block + overlapping char ranges (anchor-based, contract §9)."""
    if not a.provenance_anchors or not b.provenance_anchors:
        return False
    aa, ba = a.provenance_anchors[0], b.provenance_anchors[0]
    if aa.block_id != ba.block_id:
        return False
    if aa.char_start is None or aa.char_end is None:
        return False
    if ba.char_start is None or ba.char_end is None:
        return False
    return aa.char_start <= ba.char_end and ba.char_start <= aa.char_end


def merge_into_ledger(
    ledger: CandidateLedger,
    discovered: list[ScientificCandidate],
) -> CandidateLedger:
    """Merge LLM-discovered candidates into the ledger with anchor dedupe.

    - Same (span, kind) as an existing candidate -> merged (discovery_methods
      list in source_detail; identity preserved, values untouched).
    - Otherwise appended (placeholder UNMAPPED mapping, O7).
    """
    merged_ids: set[str] = set()
    out_candidates = list(ledger.candidates)
    for candidate in discovered:
        hit = next(
            (
                c
                for c in out_candidates
                if c.candidate_kind == candidate.candidate_kind
                and _span_overlap(c, candidate)
            ),
            None,
        )
        if hit is None:
            out_candidates.append(candidate)
            continue
        methods = list(hit.source_detail.get("discovery_methods") or [hit.discovery_method])
        if candidate.discovery_method not in methods:
            methods.append(candidate.discovery_method)
        replaced = hit.model_copy(
            update={
                "source_detail": {
                    **hit.source_detail,
                    "discovery_methods": methods,
                }
            }
        )
        out_candidates[out_candidates.index(hit)] = replaced
        merged_ids.add(candidate.candidate_id)

    mappings: list[CandidateMapping] = []
    for candidate in out_candidates:
        existing = next(
            (m for m in ledger.mappings if m.candidate_id == candidate.candidate_id),
            None,
        )
        if existing is not None:
            mappings.append(existing)
        else:
            mappings.append(_placeholder_mapping(candidate))
    return CandidateLedger(
        ledger_version_id=ledger.ledger_version_id,
        paper_id=ledger.paper_id,
        document_version_id=ledger.document_version_id,
        schema_version=ledger.schema_version,
        candidates=sorted(
            out_candidates, key=lambda c: (c.source_type.value, c.source_locator)
        ),
        mappings=mappings,
        metrics={
            **ledger.metrics,
            **_compute_metrics(out_candidates, mappings),
            "merged_discovered_count": len(merged_ids),
        },
    )


def _compute_metrics(
    candidates: list[ScientificCandidate],
    mappings: list[CandidateMapping],
) -> dict[str, int]:
    from collections import Counter

    def counts(values: list[str]) -> dict[str, int]:
        return {f"{k}": v for k, v in Counter(values).items()}

    metrics: dict[str, int] = {"candidate_count": len(candidates), "mapping_count": len(mappings)}
    metrics.update(
        {f"source_type_{k}": v for k, v in counts([c.source_type.value for c in candidates]).items()}
    )
    metrics.update(
        {f"mapping_status_{k}": v for k, v in counts([m.status.value for m in mappings]).items()}
    )
    metrics.update(
        {f"candidate_kind_{k}": v for k, v in counts([c.candidate_kind.value for c in candidates]).items()}
    )
    metrics.update(
        {f"promotion_status_{k}": v for k, v in counts([c.promotion_status.value for c in candidates]).items()}
    )
    return metrics


def _placeholder_mapping(candidate: ScientificCandidate) -> CandidateMapping:
    from ultrafast_ingestion.candidates.models import (
        NAMESPACE_CONDITION,
        MappingStatus,
    )

    return CandidateMapping(
        candidate_id=candidate.candidate_id,
        target_namespace=NAMESPACE_CONDITION,
        target_field=None,
        status=MappingStatus.UNMAPPED,
    )


def ledger_with_discovered(
    document,
    mentions,
    regions,
    discovered: list[ScientificCandidate],
    compile_result=None,
) -> CandidateLedger:
    """Convenience: build the deterministic ledger, then anchor-merge discovered."""
    return merge_into_ledger(
        build_ledger(document, mentions, regions, compile_result=compile_result),
        discovered,
    )


def route_ledger(ledger: CandidateLedger) -> CandidateLedger:
    """O7 routing: replace LLM placeholder mappings with real ones.

    - QUANTITY candidates whose concept_label matches the deterministic
      parameter vocabulary -> MAPPED (experimental_condition.<param>)
    - everything else -> UNMAPPED (retained, never deleted - D3/D8)
    - deterministic candidates keep their existing mappings untouched
    """
    from ultrafast_ingestion.candidates.models import (
        NAMESPACE_CONDITION,
        MappingStatus,
    )
    from ultrafast_ingestion.mentions.units import parameter_from_label

    candidates = list(ledger.candidates)
    mappings: list[CandidateMapping] = []
    for candidate in candidates:
        existing = next(
            (m for m in ledger.mappings if m.candidate_id == candidate.candidate_id),
            None,
        )
        if candidate.source_type != CandidateSourceType.LLM_DISCOVERY:
            if existing is not None:
                mappings.append(existing)
            else:
                mappings.append(_placeholder_mapping(candidate))
            continue
        param = parameter_from_label(candidate.concept_label)
        if candidate.candidate_kind == CandidateKind.QUANTITY and param != "unknown":
            mappings.append(
                CandidateMapping(
                    candidate_id=candidate.candidate_id,
                    target_namespace=NAMESPACE_CONDITION,
                    target_field=param,
                    status=MappingStatus.MAPPED,
                )
            )
        else:
            mappings.append(
                CandidateMapping(
                    candidate_id=candidate.candidate_id,
                    target_namespace=NAMESPACE_CONDITION,
                    target_field=None,
                    status=MappingStatus.UNMAPPED,
                )
            )
    return CandidateLedger(
        ledger_version_id=ledger.ledger_version_id,
        paper_id=ledger.paper_id,
        document_version_id=ledger.document_version_id,
        schema_version=ledger.schema_version,
        candidates=candidates,
        mappings=mappings,
        metrics={
            **ledger.metrics,
            **_compute_metrics(candidates, mappings),
        },
    )
