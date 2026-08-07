"""M8: Canonical Interaction State.

Contract: docs/contracts/CANONICAL_PHYSICS_V0_1.md.

Not "compute as much as possible" - an honest statement of which canonical
coordinates actually hold under verified inputs and formula dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CoordinateAvailability(StrEnum):
    """Unified namespace across Source/Target for M9 comparison."""

    AVAILABLE = "AVAILABLE"
    UNVERIFIED = "UNVERIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_REPORTED = "NOT_REPORTED"
    TEXT_COVERAGE_BLOCKED = "TEXT_COVERAGE_BLOCKED"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    UNAVAILABLE = "UNAVAILABLE"


class Comparability(StrEnum):
    COMPARABLE = "COMPARABLE"
    UNVERIFIED = "UNVERIFIED"  # at least one side unverified - CFA must not consume
    INCOMPARABLE = "INCOMPARABLE"  # at least one side unavailable


@dataclass(frozen=True, slots=True)
class CanonicalCoordinate:
    coordinate: str
    availability: CoordinateAvailability
    value: float | None = None
    unit: str | None = None
    formula_id: str | None = None
    formula_version: str | None = None
    approximate: bool = False
    input_provenance: tuple[str, ...] = ()  # input names that produced it
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "coordinate": self.coordinate,
            "availability": self.availability.value,
            "value": self.value,
            "unit": self.unit,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "approximate": self.approximate,
            "input_provenance": list(self.input_provenance),
            "reason": self.reason,
        }


@dataclass(slots=True)
class CanonicalInteractionState:
    """One interaction state (a source condition or the target) in the
    canonical coordinate namespace."""

    side: str  # "source" | "target"
    condition_id: str = ""
    paper_id: str = ""
    coordinates: dict[str, CanonicalCoordinate] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "condition_id": self.condition_id,
            "paper_id": self.paper_id,
            "coordinates": {
                name: c.to_dict() for name, c in sorted(self.coordinates.items())
            },
        }


def _source_availability(status: str) -> CoordinateAvailability:
    mapping = {
        "RECONSTRUCTIBLE": CoordinateAvailability.AVAILABLE,
        "AMBIGUOUS": CoordinateAvailability.AMBIGUOUS,
        "NOT_REPORTED": CoordinateAvailability.NOT_REPORTED,
        "TEXT_COVERAGE_BLOCKED": CoordinateAvailability.TEXT_COVERAGE_BLOCKED,
        "DEPENDENCY_MISSING": CoordinateAvailability.DEPENDENCY_MISSING,
    }
    return mapping.get(status, CoordinateAvailability.UNAVAILABLE)


def source_state(report) -> CanonicalInteractionState:
    """SourceReconstructibilityReport -> CanonicalInteractionState (M8)."""
    state = CanonicalInteractionState(
        side="source",
        condition_id=report.condition_id,
        paper_id=report.paper_id,
    )
    for result in report.computable_coordinates + report.blocked_coordinates:
        state.coordinates[result.coordinate] = CanonicalCoordinate(
            coordinate=result.coordinate,
            availability=_source_availability(result.status.value),
            value=result.value,
            unit=result.unit,
            formula_id=result.coordinate,
            formula_version=result.formula_version,
            approximate=result.approximate,
            input_provenance=tuple(result.missing_inputs or ()),
            reason=result.blocking_status,
        )
    return state


def _target_availability(status: str) -> CoordinateAvailability:
    if status == "AVAILABLE":
        return CoordinateAvailability.AVAILABLE
    if status == "AVAILABLE_WITH_UNVERIFIED_ASSUMPTION":
        return CoordinateAvailability.UNVERIFIED
    return CoordinateAvailability.UNAVAILABLE


def target_state(report, condition_id: str = "target") -> CanonicalInteractionState:
    """TargetPhysicsReadinessReport -> CanonicalInteractionState (M8)."""
    state = CanonicalInteractionState(side="target", condition_id=condition_id)
    for result in (
        report.available_coordinates
        + report.unverified_assumption_coordinates
        + report.blocked_coordinates
    ):
        state.coordinates[result.coordinate] = CanonicalCoordinate(
            coordinate=result.coordinate,
            availability=_target_availability(result.status.value),
            value=result.value,
            unit=result.unit,
            formula_id=result.coordinate,
            formula_version=result.formula_version,
            approximate=result.approximate,
            input_provenance=tuple(
                list(result.unverified_inputs) + list(result.missing_inputs)
            ),
            reason=(
                "unverified_input"
                if result.status.value
                == "AVAILABLE_WITH_UNVERIFIED_ASSUMPTION"
                else "blocked"
            ),
        )
    return state


def compare_canonical(
    source: CanonicalInteractionState,
    target: CanonicalInteractionState,
) -> dict[str, dict[str, Any]]:
    """Per-coordinate comparability between source and target (M9 input).

    Unknown is never a mismatch: COMPARABLE requires BOTH sides AVAILABLE;
    any UNVERIFIED side -> UNVERIFIED; otherwise INCOMPARABLE.
    """
    names = sorted(set(source.coordinates) | set(target.coordinates))
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        s = source.coordinates.get(name)
        t = target.coordinates.get(name)
        if s is None or t is None:
            out[name] = {
                "comparability": Comparability.INCOMPARABLE.value,
                "source": s.availability.value if s else "MISSING",
                "target": t.availability.value if t else "MISSING",
                "reason": "missing_on_one_side",
            }
            continue
        if (
            s.availability == CoordinateAvailability.AVAILABLE
            and t.availability == CoordinateAvailability.AVAILABLE
        ):
            out[name] = {
                "comparability": Comparability.COMPARABLE.value,
                "source": s.availability.value,
                "target": t.availability.value,
                "reason": "",
            }
            continue
        if (
            s.availability == CoordinateAvailability.UNVERIFIED
            or t.availability == CoordinateAvailability.UNVERIFIED
        ):
            out[name] = {
                "comparability": Comparability.UNVERIFIED.value,
                "source": s.availability.value,
                "target": t.availability.value,
                "reason": "unverified_on_one_side",
            }
            continue
        out[name] = {
            "comparability": Comparability.INCOMPARABLE.value,
            "source": s.availability.value,
            "target": t.availability.value,
            "reason": "unavailable",
        }
    return out
