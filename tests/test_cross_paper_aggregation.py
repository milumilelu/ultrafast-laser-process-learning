from __future__ import annotations

from ultrafast_knowledge.evidence_pipeline import (
    CrossPaperEvidenceAggregator,
    ExtractionStatus,
    PaperEvidence,
    RequirementEvidence,
)
from ultrafast_requirements import (
    KnowledgeRequirement,
    RequirementSource,
    RequirementStatus,
)


def _requirement() -> KnowledgeRequirement:
    return KnowledgeRequirement(
        requirement_id="req-threshold",
        quantity="ablation_threshold_J_m2",
        role="material_threshold",
        acceptable_sources=[RequirementSource.LITERATURE],
        expected_unit="J/m2",
        conditions={"material": "diamond", "laser_type": "fs"},
        resolution_policy="extract_direct_report",
        status=RequirementStatus.MISSING,
    )


def _paper(
    paper_id: str,
    value: float,
    *,
    conditions: dict | None = None,
    governance_status: str = "unreviewed",
) -> PaperEvidence:
    return PaperEvidence(
        paper_id=paper_id,
        document_version_id=f"version-{paper_id}",
        evidence=RequirementEvidence(
            requirement_id="req-threshold",
            quantity="ablation_threshold_J_m2",
            status=ExtractionStatus.FOUND,
            value=value,
            unit="J/cm2",
            conditions=conditions
            if conditions is not None
            else {"material": "diamond", "laser_type": "fs"},
            source_block_refs=[f"block-{paper_id}"],
            evidence_quote=f"threshold {value} J/cm2",
            confidence=0.9,
            validation_state="validated",
            governance_status=governance_status,
        ),
    )


def test_cross_paper_reduce_reports_conflict_without_mixing_values() -> None:
    result = CrossPaperEvidenceAggregator().aggregate(
        _requirement(), [_paper("a", 3.0), _paper("b", 4.0)]
    )

    assert result.status == ExtractionStatus.CONFLICT
    assert {item["paper_id"] for item in result.conflict_values} == {"a", "b"}
    assert result.value is None


def test_governance_status_never_blocks_scientific_reduction() -> None:
    result = CrossPaperEvidenceAggregator().aggregate(
        _requirement(), [_paper("a", 3.0, governance_status="rejected")]
    )

    assert result.status == ExtractionStatus.FOUND
    assert result.value == 3.0
    assert result.governance_status == "rejected"


def test_missing_condition_is_insufficient_not_found() -> None:
    result = CrossPaperEvidenceAggregator().aggregate(
        _requirement(), [_paper("a", 3.0, conditions={"material": "diamond"})]
    )

    assert result.status == ExtractionStatus.INSUFFICIENT
