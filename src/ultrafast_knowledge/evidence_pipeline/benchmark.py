"""Deterministic retrieval and evidence acceptance metrics."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from ultrafast_knowledge.evidence_pipeline.schemas import (
    EvidenceWindow,
    ExtractionStatus,
    PaperCandidate,
    RequirementEvidence,
)
from ultrafast_shared.units import convert, normalize_unit


class RetrievalGold(BaseModel):
    relevant_paper_ids: set[str] = Field(default_factory=set)
    relevant_block_ids: set[str] = Field(default_factory=set)
    expected_value: float | None = None
    expected_lower: float | None = None
    expected_upper: float | None = None
    expected_unit: str | None = None
    expected_conditions: dict[str, Any] = Field(default_factory=dict)


class EvidenceBenchmarkMetrics(BaseModel):
    paper_recall_at_k: float
    evidence_block_recall_at_k: float
    paper_mrr: float
    source_attribution_accuracy: float
    numerical_extraction_precision: float
    numerical_extraction_recall: float
    unit_accuracy: float
    condition_linkage_accuracy: float
    false_satisfied_rate: float


def evaluate_evidence_run(
    candidates: list[PaperCandidate],
    windows_by_paper: dict[str, list[EvidenceWindow]],
    result: RequirementEvidence,
    gold: RetrievalGold,
    *,
    paper_k: int,
    block_k: int,
    negative_results: list[RequirementEvidence] | None = None,
) -> EvidenceBenchmarkMetrics:
    ranked_papers = [item.paper_id for item in candidates[:paper_k]]
    paper_hits = gold.relevant_paper_ids.intersection(ranked_papers)
    paper_recall = len(paper_hits) / max(1, len(gold.relevant_paper_ids))
    reciprocal_rank = 0.0
    for rank, paper_id in enumerate(ranked_papers, 1):
        if paper_id in gold.relevant_paper_ids:
            reciprocal_rank = 1.0 / rank
            break

    ranked_windows = sorted(
        (
            window
            for candidate in candidates[:paper_k]
            for window in windows_by_paper.get(
                f"{candidate.paper_id}::{candidate.document_version_id}", []
            )
        ),
        key=lambda item: item.score,
        reverse=True,
    )[:block_k]
    retrieved_blocks = {
        block.block_id for window in ranked_windows for block in window.blocks
    }
    block_hits = gold.relevant_block_ids.intersection(retrieved_blocks)
    block_recall = len(block_hits) / max(1, len(gold.relevant_block_ids))
    cited = set(result.source_block_refs)
    attribution = (
        len(cited.intersection(gold.relevant_block_ids)) / len(cited)
        if cited
        else 0.0
    )
    negatives = negative_results or []
    false_satisfied = sum(
        item.status in {ExtractionStatus.FOUND, ExtractionStatus.CONFLICT}
        for item in negatives
    ) / max(1, len(negatives))
    predicted_numeric = any(
        value is not None for value in (result.value, result.lower, result.upper)
    )
    expected_numeric = any(
        value is not None
        for value in (gold.expected_value, gold.expected_lower, gold.expected_upper)
    )
    numeric_correct = _numeric_correct(result, gold) if expected_numeric else False
    numeric_precision = float(numeric_correct) if predicted_numeric else 0.0
    numeric_recall = float(numeric_correct) if expected_numeric else 0.0
    actual_unit, _ = normalize_unit(result.unit)
    expected_unit, _ = normalize_unit(gold.expected_unit)
    unit_accuracy = float(
        bool(gold.expected_unit)
        and actual_unit is not None
        and actual_unit == expected_unit
    )
    condition_accuracy = float(
        bool(gold.expected_conditions)
        and all(
            _normalized(result.conditions.get(key)) == _normalized(value)
            for key, value in gold.expected_conditions.items()
        )
    )
    return EvidenceBenchmarkMetrics(
        paper_recall_at_k=paper_recall,
        evidence_block_recall_at_k=block_recall,
        paper_mrr=reciprocal_rank,
        source_attribution_accuracy=attribution,
        numerical_extraction_precision=numeric_precision,
        numerical_extraction_recall=numeric_recall,
        unit_accuracy=unit_accuracy,
        condition_linkage_accuracy=condition_accuracy,
        false_satisfied_rate=false_satisfied,
    )


def _numeric_correct(result: RequirementEvidence, gold: RetrievalGold) -> bool:
    pairs = (
        (result.value, gold.expected_value),
        (result.lower, gold.expected_lower),
        (result.upper, gold.expected_upper),
    )
    for actual, expected in pairs:
        if expected is None:
            if actual is not None:
                return False
            continue
        if actual is None:
            return False
        actual_canonical = convert(actual, result.unit)
        expected_canonical = convert(expected, gold.expected_unit)
        if actual_canonical is None or expected_canonical is None:
            return False
        if not math.isclose(actual_canonical, expected_canonical, rel_tol=1e-6):
            return False
    return True


def _normalized(value: Any) -> Any:
    return " ".join(value.casefold().split()) if isinstance(value, str) else value
