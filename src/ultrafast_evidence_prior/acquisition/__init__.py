"""Bounded, requirement-specific evidence acquisition."""

from ultrafast_evidence_prior.acquisition.coverage import (
    EvidenceCoverageAssessor,
    RequirementCoverageSpecCompiler,
)
from ultrafast_evidence_prior.acquisition.planner import DeterministicGapQueryPlanner
from ultrafast_evidence_prior.acquisition.session import (
    AcquisitionBudget,
    EvidenceAcquisitionResult,
    EvidenceAcquisitionSession,
)

__all__ = [
    "AcquisitionBudget",
    "DeterministicGapQueryPlanner",
    "EvidenceAcquisitionResult",
    "EvidenceAcquisitionSession",
    "EvidenceCoverageAssessor",
    "RequirementCoverageSpecCompiler",
]
