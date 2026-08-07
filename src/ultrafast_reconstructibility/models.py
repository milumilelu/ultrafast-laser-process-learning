"""Source Reconstructibility V0.1 models (M6, contract §2/§4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CoverageStatus(StrEnum):
    TEXT_COVERAGE_OK = "TEXT_COVERAGE_OK"
    TEXT_COVERAGE_PARTIAL = "TEXT_COVERAGE_PARTIAL"
    TEXT_COVERAGE_UNKNOWN = "TEXT_COVERAGE_UNKNOWN"


class FieldStatus(StrEnum):
    REPORTED_CLEAR = "REPORTED_CLEAR"
    CONFLICT_PRESERVED = "CONFLICT_PRESERVED"
    LINKAGE_AMBIGUOUS = "LINKAGE_AMBIGUOUS"


class FieldAvailability(StrEnum):
    """The five kinds of 'unknown' (contract §1) at field level."""

    REPORTED = "REPORTED"
    NOT_REPORTED = "NOT_REPORTED"
    TEXT_COVERAGE_BLOCKED = "TEXT_COVERAGE_BLOCKED"
    REPORTED_AMBIGUOUS = "REPORTED_AMBIGUOUS"
    PHYSICS_DEPENDENCY_MISSING = "PHYSICS_DEPENDENCY_MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CoordinateStatus(StrEnum):
    RECONSTRUCTIBLE = "RECONSTRUCTIBLE"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_REPORTED = "NOT_REPORTED"
    TEXT_COVERAGE_BLOCKED = "TEXT_COVERAGE_BLOCKED"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReconstructibilityStatus(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class ValueShape(StrEnum):
    """V2-2: reported value shape - a range/set is never a point observation."""

    POINT = "POINT"
    RANGE = "RANGE"
    LIST = "LIST"  # SET / SWEEP forms are captured as LIST by the extractor


@dataclass(frozen=True, slots=True)
class SourceField:
    parameter: str
    values: tuple[float, ...]
    unit: str
    field_status: FieldStatus
    provenance_anchor_ids: tuple[str, ...] = ()
    value_shape: ValueShape = ValueShape.POINT

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "values": list(self.values),
            "unit": self.unit,
            "field_status": self.field_status.value,
            "provenance_anchor_ids": list(self.provenance_anchor_ids),
            "value_shape": self.value_shape.value,
        }


@dataclass(frozen=True, slots=True)
class SourceConditionSpec:
    condition_id: str
    paper_id: str
    document_version_id: str
    role: str = ""
    scope: str = ""
    coverage_status: CoverageStatus = CoverageStatus.TEXT_COVERAGE_OK
    fields: tuple[SourceField, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "paper_id": self.paper_id,
            "document_version_id": self.document_version_id,
            "role": self.role,
            "scope": self.scope,
            "coverage_status": self.coverage_status.value,
            "fields": [f.to_dict() for f in self.fields],
        }


@dataclass(frozen=True, slots=True)
class CoordinateResult:
    coordinate: str
    status: CoordinateStatus
    value: float | None = None
    unit: str | None = None
    formula_version: str | None = None
    approximate: bool = False
    missing_inputs: tuple[str, ...] = ()
    blocking_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "coordinate": self.coordinate,
            "status": self.status.value,
            "value": self.value,
            "unit": self.unit,
            "formula_version": self.formula_version,
            "approximate": self.approximate,
            "missing_inputs": list(self.missing_inputs),
            "blocking_status": self.blocking_status,
        }


@dataclass(slots=True)
class SourceReconstructibilityReport:
    paper_id: str
    condition_id: str
    reported_fields: list[str] = field(default_factory=list)
    ambiguous_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    coverage_blocked_fields: list[str] = field(default_factory=list)
    dependency_missing_fields: list[str] = field(default_factory=list)
    computable_coordinates: list[CoordinateResult] = field(default_factory=list)
    blocked_coordinates: list[CoordinateResult] = field(default_factory=list)
    blocking_dependencies: list[str] = field(default_factory=list)
    reconstructibility_status: ReconstructibilityStatus = ReconstructibilityStatus.BLOCKED
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "condition_id": self.condition_id,
            "reported_fields": list(self.reported_fields),
            "ambiguous_fields": list(self.ambiguous_fields),
            "missing_fields": list(self.missing_fields),
            "coverage_blocked_fields": list(self.coverage_blocked_fields),
            "dependency_missing_fields": list(self.dependency_missing_fields),
            "computable_coordinates": [c.to_dict() for c in self.computable_coordinates],
            "blocked_coordinates": [c.to_dict() for c in self.blocked_coordinates],
            "blocking_dependencies": list(self.blocking_dependencies),
            "reconstructibility_status": self.reconstructibility_status.value,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class SourcePhysicsReadiness:
    """Source-side aggregate, symmetric to the future TargetPhysicsReadiness.

    coordinate_status: {CoordinateStatus -> occurrence count} across the
    aggregated conditions (per-condition coordinate states live in the
    reports themselves).
    """

    reported_field_count: int = 0
    ambiguous_field_count: int = 0
    missing_field_count: int = 0
    coverage_blocked_field_count: int = 0
    computable_coordinate_count: int = 0
    blocked_coordinate_count: int = 0
    coordinate_status: dict[str, int] = field(default_factory=dict)
    reconstructible_conditions: int = 0
    total_conditions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "reported_field_count": self.reported_field_count,
            "ambiguous_field_count": self.ambiguous_field_count,
            "missing_field_count": self.missing_field_count,
            "coverage_blocked_field_count": self.coverage_blocked_field_count,
            "computable_coordinate_count": self.computable_coordinate_count,
            "blocked_coordinate_count": self.blocked_coordinate_count,
            "coordinate_status": dict(self.coordinate_status),
            "reconstructible_conditions": self.reconstructible_conditions,
            "total_conditions": self.total_conditions,
        }
