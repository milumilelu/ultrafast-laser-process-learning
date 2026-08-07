"""SchemaGap reporting (O8) - contract §10.

SUPPORTED + UNMAPPED candidates aggregate into SchemaGapCandidate records.
Schema evolution is human-in-the-loop only: this module REPORTS gaps, it
never modifies any schema (contract §10: automatic self-modification is
forbidden).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ultrafast_ingestion.candidates.models import (
    CandidateLedger,
    MappingStatus,
    VerificationStatus,
)


@dataclass(frozen=True, slots=True)
class SchemaGapCandidate:
    concept_label: str
    example_candidate_ids: tuple[str, ...]
    occurrence_count: int
    paper_count: int

    def to_dict(self) -> dict:
        return {
            "concept_label": self.concept_label,
            "example_candidate_ids": list(self.example_candidate_ids),
            "occurrence_count": self.occurrence_count,
            "paper_count": self.paper_count,
        }


def schema_gaps(
    ledger: CandidateLedger,
    *,
    verification_statuses: frozenset[VerificationStatus] = frozenset(
        {VerificationStatus.SUPPORTED, VerificationStatus.NOT_RUN}
    ),
) -> list[SchemaGapCandidate]:
    """Aggregate SUPPORTED + UNMAPPED candidates by concept_label.

    NOT_RUN is included: candidates that never needed LLM verification
    (tier-0/1 deterministically grounded ones) still carry scientific value.
    CONTRADICTED / INSUFFICIENT candidates never report schema gaps.
    """
    status_by_id = {c.candidate_id: c.verification_status for c in ledger.candidates}
    mapping_by_id = {m.candidate_id: m for m in ledger.mappings}
    by_label: dict[str, list[str]] = {}
    papers: dict[str, set[str]] = {}
    for candidate in ledger.candidates:
        if status_by_id[candidate.candidate_id] not in verification_statuses:
            continue
        mapping = mapping_by_id.get(candidate.candidate_id)
        if mapping is None or mapping.status != MappingStatus.UNMAPPED:
            continue
        by_label.setdefault(candidate.concept_label, []).append(candidate.candidate_id)
        papers.setdefault(candidate.concept_label, set()).add(candidate.paper_id)
    return [
        SchemaGapCandidate(
            concept_label=label,
            example_candidate_ids=tuple(ids[:3]),
            occurrence_count=len(ids),
            paper_count=len(papers[label]),
        )
        for label, ids in sorted(by_label.items(), key=lambda kv: -len(kv[1]))
    ]


def gap_report(ledgers: list[CandidateLedger]) -> list[dict]:
    """Cross-paper gap ledger: concept -> papers / mentions (contract §10)."""
    by_label: dict[str, list[str]] = {}
    papers: dict[str, set[str]] = {}
    for ledger in ledgers:
        for gap in schema_gaps(ledger):
            by_label.setdefault(gap.concept_label, []).extend(gap.example_candidate_ids)
            papers.setdefault(gap.concept_label, set()).add(ledger.paper_id)
    return [
        {
            "concept": label,
            "papers": len(papers[label]),
            "mentions": Counter(by_label[label]).total(),
            "example_candidate_ids": list(dict.fromkeys(by_label[label]))[:5],
        }
        for label in sorted(by_label, key=lambda l: (-len(papers[l]), l))
    ]
