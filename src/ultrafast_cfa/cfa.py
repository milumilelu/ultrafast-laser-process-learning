"""M9: Uncalibrated CFA V1 - faceted applicability without probability claims.

Contract: docs/contracts/UNCALIBRATED_CFA_V0_1.md.

Five facets: Material / Task / Interaction State / Reconstructibility /
Reachability. Unknown is never a mismatch. No confidence numbers anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ultrafast_interaction.canonical import (
    CanonicalInteractionState,
    CoordinateAvailability,
    compare_canonical,
)

# Single source of truth for the released CFA version (RF-1 traceability).
# Historical benchmark runs may pass explicit older versions
# (e.g. run_b1_dev_v11.py keeps "uncalibrated-cfa-v1.1").
CFA_VERSION = "uncalibrated-cfa-v2.0"


class FacetStatus(StrEnum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True, slots=True)
class MaterialFacet:
    status: FacetStatus
    material_source: str = ""
    material_target: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "facet": "Material",
            "status": self.status.value,
            "material_source": self.material_source,
            "material_target": self.material_target,
        }


@dataclass(frozen=True, slots=True)
class TaskFacet:
    status: FacetStatus
    matches: dict[str, str] = field(default_factory=dict)  # dim -> match|unknown|mismatch

    def to_dict(self) -> dict[str, Any]:
        return {"facet": "Task", "status": self.status.value, "matches": dict(self.matches)}


@dataclass(frozen=True, slots=True)
class InteractionStateFacet:
    status: FacetStatus
    coordinates: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "facet": "InteractionState",
            "status": self.status.value,
            "coordinates": dict(self.coordinates),
        }


@dataclass(frozen=True, slots=True)
class ReconstructibilityFacet:
    status: FacetStatus
    reconstructible: int = 0
    total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "facet": "Reconstructibility",
            "status": self.status.value,
            "reconstructible": self.reconstructible,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True)
class ReachabilityFacet:
    status: FacetStatus
    reachable: int = 0
    total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "facet": "Reachability",
            "status": self.status.value,
            "reachable": self.reachable,
            "total": self.total,
        }


@dataclass(slots=True)
class UncalibratedCFAReport:
    evidence_claim_id: str = ""
    facets: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    version: str = CFA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "calibration_status": "NOT_YET_CALIBRATED",
            "evidence_claim_id": self.evidence_claim_id,
            "facets": [f.to_dict() for f in self.facets],
            "warnings": list(self.warnings),
        }


def _match(task_value: str | None, evidence_value: str | None) -> str:
    """match | mismatch | unknown - unknown is never a mismatch."""
    if task_value is None or evidence_value is None:
        return "unknown"
    return "match" if task_value == evidence_value else "mismatch"


# material family canonicalization (order matters: specific keys first)
_MATERIAL_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sic", ("4h-sic", "6h-sic", "3c-sic", "silicon carbide", "hpsi sic", "n-doped sic", " sic")),
    ("diamond", ("diamond",)),
    ("cfrp", ("cfrp", "carbon fiber", "carbon fibre", "carbon-fiber", "carbon-fibre")),
    ("glass", ("soda-lime", "borosilicate", "fused silica", "silica glass", "tellurite", "alkali-silicate", "glass")),
    ("silicon", ("silicon", "si wafer", "single-crystal silicon")),
    ("steel", ("steel",)),
    ("titanium", ("titanium",)),
    ("aluminum", ("aluminum", "aluminium")),
    ("copper", ("copper", " cu ")),
    ("nickel", ("nickel", "superalloy", "inconel")),
    ("polymer", ("polymer", "pmma", "composite", "resin")),
    ("ceramic", ("ceramic", "alumina", "zirconia")),
)


def _canonical_material(name: Any) -> str | None:
    if name is None:
        return None
    lower = str(name).lower().strip()
    if not lower:
        return None
    for canonical, keys in _MATERIAL_ALIASES:
        if any(key in lower for key in keys):
            return canonical
    return lower


def assess_material(
    task_scope: dict[str, Any], evidence_scope: dict[str, Any]
) -> MaterialFacet:
    source_material = _canonical_material(evidence_scope.get("material_id"))
    target_material = _canonical_material(task_scope.get("material_id"))
    if source_material is None or target_material is None:
        return MaterialFacet(
            status=FacetStatus.UNKNOWN,
            material_source=str(evidence_scope.get("material_id") or ""),
            material_target=str(task_scope.get("material_id") or ""),
        )
    status = (
        FacetStatus.KNOWN
        if source_material == target_material
        else FacetStatus.MISMATCH
    )
    return MaterialFacet(
        status=status,
        material_source=str(evidence_scope.get("material_id") or ""),
        material_target=str(task_scope.get("material_id") or ""),
    )


def assess_task(task_scope: dict[str, Any], evidence_scope: dict[str, Any]) -> TaskFacet:
    dims = (
        ("laser_type", "laser_type"),
        ("process_type", "process_type"),
        ("geometry_type", "geometry_type"),
        ("target_metric", "target_metric"),
    )
    matches: dict[str, str] = {}
    for task_key, evidence_key in dims:
        matches[task_key] = _match(
            task_scope.get(task_key), evidence_scope.get(evidence_key)
        )
    if any(v == "mismatch" for v in matches.values()):
        status = FacetStatus.MISMATCH
    elif any(v == "unknown" for v in matches.values()):
        status = FacetStatus.PARTIAL
    else:
        status = FacetStatus.KNOWN
    return TaskFacet(status=status, matches=matches)


def assess_interaction(
    source: CanonicalInteractionState, target: CanonicalInteractionState
) -> InteractionStateFacet:
    comparison = compare_canonical(source, target)
    statuses = [entry["comparability"] for entry in comparison.values()]
    if not statuses:
        return InteractionStateFacet(status=FacetStatus.UNKNOWN, coordinates=comparison)
    comparable = sum(1 for s in statuses if s == "COMPARABLE")
    if comparable == len(statuses):
        status = FacetStatus.KNOWN
    elif comparable == 0:
        status = FacetStatus.UNKNOWN
    else:
        status = FacetStatus.PARTIAL
    return InteractionStateFacet(status=status, coordinates=comparison)


def assess_reconstructibility(source: CanonicalInteractionState) -> ReconstructibilityFacet:
    coordinates = list(source.coordinates.values())
    total = len(coordinates)
    reconstructible = sum(
        1 for c in coordinates if c.availability == CoordinateAvailability.AVAILABLE
    )
    if total == 0:
        return ReconstructibilityFacet(status=FacetStatus.UNKNOWN, total=0)
    if reconstructible == total:
        status = FacetStatus.KNOWN
    elif reconstructible > 0:
        status = FacetStatus.PARTIAL
    else:
        status = FacetStatus.UNKNOWN
    return ReconstructibilityFacet(
        status=status, reconstructible=reconstructible, total=total
    )


def assess_reachability(target: CanonicalInteractionState) -> ReachabilityFacet:
    coordinates = list(target.coordinates.values())
    total = len(coordinates)
    reachable = sum(
        1 for c in coordinates if c.availability == CoordinateAvailability.AVAILABLE
    )
    if total == 0:
        return ReachabilityFacet(status=FacetStatus.UNKNOWN, total=0)
    if reachable == total:
        status = FacetStatus.KNOWN
    elif reachable > 0:
        status = FacetStatus.PARTIAL
    else:
        status = FacetStatus.UNKNOWN
    return ReachabilityFacet(status=status, reachable=reachable, total=total)


def assess_all(
    *,
    task_scope: dict[str, Any],
    evidence_scope: dict[str, Any],
    source: CanonicalInteractionState,
    target: CanonicalInteractionState,
    evidence_claim_id: str = "",
    version: str = CFA_VERSION,
) -> UncalibratedCFAReport:
    report = UncalibratedCFAReport(evidence_claim_id=evidence_claim_id)
    report.facets = [
        assess_material(task_scope, evidence_scope),
        assess_task(task_scope, evidence_scope),
        assess_interaction(source, target),
        assess_reconstructibility(source),
        assess_reachability(target),
    ]
    report.version = version
    for facet in report.facets:
        if facet.status == FacetStatus.UNKNOWN:
            report.warnings.append(f"{facet.to_dict()['facet']}: UNKNOWN (not a mismatch)")
        if facet.to_dict()["facet"] == "InteractionState":
            unverified = [
                name
                for name, entry in facet.coordinates.items()
                if entry["comparability"] == "UNVERIFIED"
            ]
            if unverified:
                report.warnings.append(
                    f"unverified coordinates not consumable by CFA: {sorted(unverified)}"
                )
    return report
