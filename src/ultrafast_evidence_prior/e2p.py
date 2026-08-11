"""EvidenceIR v2 → faceted beliefs → typed, non-gating soft priors."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any

from ultrafast_evidence_prior.schemas import (
    ApplicabilityFacet,
    EvidenceBelief,
    EvidenceBeliefSet,
    EvidenceDirection,
    EvidenceIRSetV2,
    EvidenceIRV2,
    MaterialIdentityContent,
    MechanismContent,
    ModelStructurePrior,
    ParameterEffectContent,
    ParameterPrior,
    ParameterRangeContent,
    ParameterValueContent,
    PreferencePrior,
    PriorConflict,
    PriorObjectSetV2,
    ProcessMethodContent,
    ProcessObservationContent,
    RegionPrior,
    ReportedOptimumContent,
    ResolvedTaskV1,
    TransferLevel,
    UncertaintyLevel,
    ValidationState,
)

_APPROVED_GOVERNANCE = {
    "approved",
    "accepted",
    "accepted_to_rag",
    "accepted_as_literature_evidence",
    "governed",
}


def compile_beliefs(
    task: ResolvedTaskV1,
    evidence_set: EvidenceIRSetV2,
) -> EvidenceBeliefSet:
    beliefs = [
        _belief(task, evidence)
        for evidence in evidence_set.items
        if evidence.validation_state == ValidationState.VALIDATED
    ]
    return EvidenceBeliefSet(
        belief_set_id=_stable_id(
            "belief-set",
            [item.model_dump(mode="json") for item in beliefs],
        ),
        beliefs=beliefs,
    )


def _belief(task: ResolvedTaskV1, evidence: EvidenceIRV2) -> EvidenceBelief:
    validated_conditions = evidence.validated_conditions
    material_value = _evidence_material(evidence)
    grade_value = _first(
        validated_conditions,
        "material_grade",
        "grade",
    )
    if grade_value is None and isinstance(evidence.content, MaterialIdentityContent):
        grade_value = evidence.content.material_grade
    target_value = _evidence_target(evidence)
    facets = [
        _string_facet("material", task.material, material_value, mismatch_score=0.2),
        _grade_facet(task.material_grade, grade_value),
        _string_facet(
            "target_metric",
            task.target_metric.value,
            target_value,
            mismatch_score=0.3,
        ),
        _wavelength_facet(task, evidence),
        _pulse_width_facet(task, evidence),
        _condition_completeness_facet(task, evidence),
        ApplicabilityFacet(
            facet="mechanical_validation",
            status="MATCH",
            score=1.0,
            task_value="VALIDATED",
            evidence_value=evidence.validation_state.value,
            reason="quote, block references, and numeric claims passed deterministic checks",
        ),
        ApplicabilityFacet(
            facet="extraction_confidence",
            status=("MATCH" if evidence.extraction_confidence >= 0.8 else "PARTIAL"),
            score=evidence.extraction_confidence,
            task_value=None,
            evidence_value=evidence.extraction_confidence,
            reason="extractor self-assessment; used only as one bounded factor",
        ),
    ]
    weights = {
        "material": 0.25,
        "material_grade": 0.10,
        "target_metric": 0.15,
        "wavelength_nm": 0.12,
        "pulse_width_fs": 0.13,
        "condition_completeness": 0.10,
        "mechanical_validation": 0.10,
        "extraction_confidence": 0.05,
    }
    score = round(
        sum(facet.score * weights[facet.facet] for facet in facets),
        4,
    )
    transfer = _transfer_level(score)
    unknown_count = sum(facet.status == "UNKNOWN" for facet in facets)
    uncertainty = _uncertainty(score, unknown_count)
    belief_id = _stable_id(
        "belief",
        {
            "evidence_id": evidence.evidence_id,
            "facets": [facet.model_dump(mode="json") for facet in facets],
        },
    )
    return EvidenceBelief(
        belief_id=belief_id,
        evidence_id=evidence.evidence_id,
        evidence_type=evidence.evidence_type,
        applicability_score=score,
        transfer_level=transfer,
        prior_weight=score,
        uncertainty=uncertainty,
        facets=facets,
        support_basis=[
            "paper-local quoted EvidenceIR",
            "mechanically validated source block references",
            "governance state excluded from transfer scoring",
        ],
        governance_status=evidence.governance_status,
    )


def compile_priors(
    evidence_set: EvidenceIRSetV2,
    belief_set: EvidenceBeliefSet,
) -> PriorObjectSetV2:
    evidence_by_id = {item.evidence_id: item for item in evidence_set.items}
    priors: list[Any] = []
    for belief in belief_set.beliefs:
        evidence = evidence_by_id[belief.evidence_id]
        content = evidence.content
        common = {
            "evidence_refs": [evidence.evidence_id],
            "belief_refs": [belief.belief_id],
            "applicability_score": belief.applicability_score,
            "weight": belief.prior_weight,
            "uncertainty": belief.uncertainty,
            "status": (
                "GOVERNED"
                if evidence.governance_status.casefold() in _APPROVED_GOVERNANCE
                else "PROVISIONAL"
            ),
            "assumptions": [
                "soft prior only; it cannot remove equipment-feasible parameter space",
                "weight is a deterministic transfer score, not a calibrated probability",
            ],
        }
        if isinstance(content, ParameterValueContent):
            priors.append(
                ParameterPrior(
                    prior_id=_stable_id("parameter-prior", evidence.evidence_id),
                    parameter=content.parameter,
                    value=content.value,
                    unit=content.unit,
                    **common,
                )
            )
        elif isinstance(content, ParameterRangeContent):
            priors.append(
                ParameterPrior(
                    prior_id=_stable_id("parameter-prior", evidence.evidence_id),
                    parameter=content.parameter,
                    lower=content.lower,
                    upper=content.upper,
                    unit=content.unit,
                    **common,
                )
            )
        elif isinstance(content, ReportedOptimumContent) and content.parameters:
            priors.append(
                RegionPrior(
                    prior_id=_stable_id("region-prior", evidence.evidence_id),
                    target_metric=content.target_metric,
                    parameters=content.parameters,
                    statement=content.statement,
                    **common,
                )
            )
        elif isinstance(content, ParameterEffectContent):
            priors.append(
                PreferencePrior(
                    prior_id=_stable_id("preference-prior", evidence.evidence_id),
                    parameter=content.parameter,
                    direction=content.direction,
                    statement=content.statement,
                    **common,
                )
            )
        elif isinstance(content, MechanismContent):
            priors.append(
                ModelStructurePrior(
                    prior_id=_stable_id("model-prior", evidence.evidence_id),
                    mechanism=content.mechanism,
                    statement=content.statement,
                    **common,
                )
            )
        elif isinstance(content, (ProcessMethodContent, ProcessObservationContent)):
            statement = content.statement
            priors.append(
                PreferencePrior(
                    prior_id=_stable_id("preference-prior", evidence.evidence_id),
                    statement=statement,
                    **common,
                )
            )
        elif isinstance(content, ReportedOptimumContent):
            priors.append(
                PreferencePrior(
                    prior_id=_stable_id("preference-prior", evidence.evidence_id),
                    direction=EvidenceDirection.OPTIMUM,
                    statement=content.statement,
                    **common,
                )
            )
        elif isinstance(content, MaterialIdentityContent):
            # Identity evidence informs transfer facets but is not itself an
            # executable parameter/model preference.
            continue

    priors, conflicts = _mark_conflicts(priors)
    warnings = [
        "prior weights are deterministic transfer scores, not calibrated probabilities",
        "all literature-derived priors are soft and never become equipment constraints",
    ]
    if conflicts:
        warnings.append(
            "disjoint numeric priors were preserved separately; no averaging was applied"
        )
    return PriorObjectSetV2(
        prior_set_id=_stable_id("prior-set", [item.model_dump(mode="json") for item in priors]),
        priors=priors,
        conflicts=conflicts,
        warnings=warnings,
    )


def _mark_conflicts(priors: list[Any]) -> tuple[list[Any], list[PriorConflict]]:
    grouped: defaultdict[str, list[ParameterPrior]] = defaultdict(list)
    for prior in priors:
        if isinstance(prior, ParameterPrior):
            grouped[_canonical(prior.parameter)].append(prior)
    conflict_by_prior: dict[str, str] = {}
    conflicts: list[PriorConflict] = []
    for parameter, candidates in grouped.items():
        involved: set[str] = set()
        for index, left in enumerate(candidates):
            left_range = _prior_range(left)
            if left_range is None:
                continue
            for right in candidates[index + 1 :]:
                right_range = _prior_range(right)
                if right_range is None or left.unit.casefold() != right.unit.casefold():
                    continue
                if left_range[1] < right_range[0] or right_range[1] < left_range[0]:
                    involved.update((left.prior_id, right.prior_id))
        if not involved:
            continue
        conflict_id = _stable_id(
            "prior-conflict", {"parameter": parameter, "priors": sorted(involved)}
        )
        for prior_id in involved:
            conflict_by_prior[prior_id] = conflict_id
        conflicts.append(
            PriorConflict(
                conflict_id=conflict_id,
                parameter=parameter,
                prior_refs=sorted(involved),
                reason="disjoint paper-local numeric evidence in the same original unit",
            )
        )
    marked = [
        prior.model_copy(update={"conflict_group_id": conflict_by_prior[prior.prior_id]})
        if prior.prior_id in conflict_by_prior
        else prior
        for prior in priors
    ]
    return marked, conflicts


def _prior_range(prior: ParameterPrior) -> tuple[float, float] | None:
    if prior.lower is not None and prior.upper is not None:
        return prior.lower, prior.upper
    if prior.value is not None:
        return prior.value, prior.value
    return None


def _evidence_material(evidence: EvidenceIRV2) -> Any:
    if isinstance(evidence.content, MaterialIdentityContent):
        return evidence.content.material
    return _first(evidence.validated_conditions, "material", "material_name")


def _evidence_target(evidence: EvidenceIRV2) -> Any:
    content = evidence.content
    if (
        isinstance(
            content,
            (ProcessObservationContent, ParameterEffectContent, ReportedOptimumContent),
        )
        and content.target_metric
    ):
        return content.target_metric
    return _first(evidence.validated_conditions, "target_metric", "target")


def _string_facet(
    name: str,
    task_value: Any,
    evidence_value: Any,
    *,
    mismatch_score: float,
) -> ApplicabilityFacet:
    if task_value is None:
        return ApplicabilityFacet(
            facet=name,
            status="NOT_APPLICABLE",
            score=1.0,
            task_value=None,
            evidence_value=evidence_value,
            reason="task does not constrain this facet",
        )
    if evidence_value is None or str(evidence_value).strip() == "":
        return ApplicabilityFacet(
            facet=name,
            status="UNKNOWN",
            score=0.65,
            task_value=task_value,
            evidence_value=None,
            reason="evidence does not report this facet",
        )
    matched = _canonical(str(task_value)) == _canonical(str(evidence_value))
    return ApplicabilityFacet(
        facet=name,
        status="MATCH" if matched else "MISMATCH",
        score=1.0 if matched else mismatch_score,
        task_value=task_value,
        evidence_value=evidence_value,
        reason="canonical exact match"
        if matched
        else "explicit values differ; transfer is down-weighted",
    )


def _grade_facet(task_grade: Any, evidence_grade: Any) -> ApplicabilityFacet:
    if task_grade is None:
        return ApplicabilityFacet(
            facet="material_grade",
            status="NOT_APPLICABLE",
            score=1.0,
            task_value=None,
            evidence_value=evidence_grade,
            reason="task does not specify a material grade",
        )
    if evidence_grade is None:
        return ApplicabilityFacet(
            facet="material_grade",
            status="UNKNOWN",
            score=0.65,
            task_value=task_grade,
            evidence_value=None,
            reason="paper does not identify a material grade",
        )
    matched = _canonical(str(task_grade)) == _canonical(str(evidence_grade))
    return ApplicabilityFacet(
        facet="material_grade",
        status="MATCH" if matched else "PARTIAL",
        score=1.0 if matched else 0.55,
        task_value=task_grade,
        evidence_value=evidence_grade,
        reason="grade matches"
        if matched
        else "same-material grade transfer remains possible but uncertain",
    )


def _wavelength_facet(task: ResolvedTaskV1, evidence: EvidenceIRV2) -> ApplicabilityFacet:
    task_value = task.equipment.wavelength_nm
    evidence_value = _number(
        _first(evidence.validated_conditions, "wavelength_nm", "laser_wavelength_nm")
    )
    return _numeric_distance_facet(
        "wavelength_nm",
        task_value,
        evidence_value,
        tolerance=0.05,
    )


def _pulse_width_facet(task: ResolvedTaskV1, evidence: EvidenceIRV2) -> ApplicabilityFacet:
    task_range = _range(task.equipment.pulse_width_min_fs, task.equipment.pulse_width_max_fs)
    evidence_range = _evidence_range(
        evidence.validated_conditions,
        scalar_keys=("pulse_width_fs", "pulse_duration_fs"),
        lower_keys=("pulse_width_min_fs", "pulse_duration_min_fs"),
        upper_keys=("pulse_width_max_fs", "pulse_duration_max_fs"),
    )
    if task_range is None:
        return ApplicabilityFacet(
            facet="pulse_width_fs",
            status="UNKNOWN",
            score=0.7,
            task_value=None,
            evidence_value=evidence_range,
            reason="equipment pulse-width range is missing",
        )
    if evidence_range is None:
        return ApplicabilityFacet(
            facet="pulse_width_fs",
            status="UNKNOWN",
            score=0.65,
            task_value=list(task_range),
            evidence_value=None,
            reason="evidence does not report pulse width",
        )
    if _overlap(task_range, evidence_range):
        return ApplicabilityFacet(
            facet="pulse_width_fs",
            status="MATCH",
            score=1.0,
            task_value=list(task_range),
            evidence_value=list(evidence_range),
            reason="pulse-width ranges overlap",
        )
    task_nearest = task_range[0] if evidence_range[1] < task_range[0] else task_range[1]
    evidence_nearest = evidence_range[1] if evidence_range[1] < task_range[0] else evidence_range[0]
    if task_nearest <= 0 or evidence_nearest <= 0:
        score = 0.2
    else:
        decades = abs(math.log10(task_nearest / evidence_nearest))
        score = max(0.1, math.exp(-1.5 * decades))
    return ApplicabilityFacet(
        facet="pulse_width_fs",
        status="PARTIAL" if score >= 0.5 else "MISMATCH",
        score=round(score, 4),
        task_value=list(task_range),
        evidence_value=list(evidence_range),
        reason="non-overlapping regimes scored by logarithmic pulse-width distance",
    )


def _condition_completeness_facet(
    task: ResolvedTaskV1,
    evidence: EvidenceIRV2,
) -> ApplicabilityFacet:
    expected: list[tuple[str, tuple[str, ...]]] = [
        ("wavelength", ("wavelength_nm", "laser_wavelength_nm")),
        ("pulse_width", ("pulse_width_fs", "pulse_duration_fs", "pulse_width_min_fs")),
        ("frequency", ("frequency_kHz", "repetition_rate_kHz")),
        ("scan_speed", ("scan_speed_mm_s",)),
    ]
    available = {
        "wavelength": task.equipment.wavelength_nm is not None,
        "pulse_width": task.equipment.pulse_width_min_fs is not None,
        "frequency": task.equipment.frequency_min_kHz is not None,
        "scan_speed": task.equipment.scan_speed_min_mm_s is not None,
    }
    relevant = [(name, keys) for name, keys in expected if available[name]]
    if not relevant:
        return ApplicabilityFacet(
            facet="condition_completeness",
            status="UNKNOWN",
            score=0.6,
            task_value=[],
            evidence_value=[],
            reason="equipment profile has no comparable process-condition dimensions",
        )
    present = [
        name
        for name, keys in relevant
        if any(_first(evidence.validated_conditions, key) is not None for key in keys)
    ]
    fraction = len(present) / len(relevant)
    score = 0.5 + 0.5 * fraction
    return ApplicabilityFacet(
        facet="condition_completeness",
        status="MATCH" if fraction >= 0.75 else ("PARTIAL" if present else "UNKNOWN"),
        score=round(score, 4),
        task_value=[name for name, _ in relevant],
        evidence_value=present,
        reason="fraction of equipment-comparable conditions explicitly reported by evidence",
    )


def _numeric_distance_facet(
    name: str,
    task_value: float | None,
    evidence_value: float | None,
    *,
    tolerance: float,
) -> ApplicabilityFacet:
    if task_value is None:
        return ApplicabilityFacet(
            facet=name,
            status="UNKNOWN",
            score=0.7,
            task_value=None,
            evidence_value=evidence_value,
            reason="equipment value is missing",
        )
    if evidence_value is None:
        return ApplicabilityFacet(
            facet=name,
            status="UNKNOWN",
            score=0.65,
            task_value=task_value,
            evidence_value=None,
            reason="evidence value is missing",
        )
    relative = abs(evidence_value - task_value) / max(abs(task_value), 1e-12)
    score = max(0.1, math.exp(-2.0 * relative))
    status = "MATCH" if relative <= tolerance else ("PARTIAL" if score >= 0.5 else "MISMATCH")
    return ApplicabilityFacet(
        facet=name,
        status=status,
        score=round(score, 4),
        task_value=task_value,
        evidence_value=evidence_value,
        reason=f"relative difference={relative:.4f}",
    )


def _transfer_level(score: float) -> TransferLevel:
    if score >= 0.8:
        return TransferLevel.STRONG
    if score >= 0.6:
        return TransferLevel.MEDIUM
    if score >= 0.35:
        return TransferLevel.WEAK
    return TransferLevel.VERY_WEAK


def _uncertainty(score: float, unknown_count: int) -> UncertaintyLevel:
    if score >= 0.8 and unknown_count <= 1:
        return UncertaintyLevel.LOW
    if score >= 0.6 and unknown_count <= 3:
        return UncertaintyLevel.MEDIUM
    return UncertaintyLevel.HIGH


def _first(values: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in values and values[key] is not None:
            return values[key]
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "mean", "center"):
            parsed = _number(value.get(key))
            if parsed is not None:
                return parsed
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _range(lower: Any, upper: Any) -> tuple[float, float] | None:
    low = _number(lower)
    high = _number(upper)
    if low is None and high is None:
        return None
    if low is None:
        low = high
    if high is None:
        high = low
    assert low is not None and high is not None
    return (min(low, high), max(low, high))


def _evidence_range(
    values: dict[str, Any],
    *,
    scalar_keys: tuple[str, ...],
    lower_keys: tuple[str, ...],
    upper_keys: tuple[str, ...],
) -> tuple[float, float] | None:
    scalar = _number(_first(values, *scalar_keys))
    if scalar is not None:
        return scalar, scalar
    return _range(_first(values, *lower_keys), _first(values, *upper_keys))


def _overlap(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return max(left[0], right[0]) <= min(left[1], right[1])


def _canonical(value: str) -> str:
    return re.sub(r"[\s\-_/]+", " ", value.strip().casefold())


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:20]}"
