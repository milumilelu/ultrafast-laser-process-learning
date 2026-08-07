"""Source Reconstructibility V0.1 (M6)."""

from __future__ import annotations

from ultrafast_reconstructibility.adapter import to_source_condition_spec
from ultrafast_reconstructibility.coordinates import (
    CONDITION_TO_INPUT,
    CoordinateEvaluator,
)
from ultrafast_reconstructibility.models import (
    CoordinateResult,
    CoordinateStatus,
    CoverageStatus,
    FieldAvailability,
    FieldStatus,
    ReconstructibilityStatus,
    SourceConditionSpec,
    SourceField,
    SourcePhysicsReadiness,
    SourceReconstructibilityReport,
)
from ultrafast_reconstructibility.report import build_readiness, build_report

__all__ = [
    "CONDITION_TO_INPUT",
    "CoordinateEvaluator",
    "CoordinateResult",
    "CoordinateStatus",
    "CoverageStatus",
    "FieldAvailability",
    "FieldStatus",
    "ReconstructibilityStatus",
    "SourceConditionSpec",
    "SourceField",
    "SourcePhysicsReadiness",
    "SourceReconstructibilityReport",
    "build_readiness",
    "build_report",
    "to_source_condition_spec",
]
