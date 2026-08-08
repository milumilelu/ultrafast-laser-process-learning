"""EvidenceIR -> typed PriorObject compilation with explicit conflicts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from packages.e2p.domain.prior_objects import (
    ConflictStatus,
    MechanismModelPrior,
    ParameterPrior,
    PlanningPreferencePrior,
    PriorConflict,
    PriorObjectSet,
    PriorRef,
    PriorStatus,
    PriorUncertainty,
)

_PHYSICAL_PARAMETERS = {
    "F_th",
    "F_th_eff",
    "ablation_threshold",
    "incubation_S",
    "delta",
    "delta_eff",
    "alpha_defocus",
    "thermal_memory_eff",
}


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:16]}"


def _uncertainty(item: dict[str, Any]) -> PriorUncertainty:
    applicability = item.get("applicability") or item.get("applicability_status")
    if isinstance(applicability, dict):
        applicability = applicability.get("status") or applicability.get("transfer_level")
    value = str(applicability or "UNKNOWN").upper()
    if value in {"DIRECT", "KNOWN", "HIGH", "APPLICABLE"}:
        return PriorUncertainty.LOW
    if value in {"PARTIAL", "MEDIUM", "CONDITIONAL"}:
        return PriorUncertainty.MEDIUM
    if value in {"MISMATCH", "LOW"}:
        return PriorUncertainty.HIGH
    return PriorUncertainty.UNKNOWN


def _prior_status(item: dict[str, Any]) -> PriorStatus:
    review = str(item.get("review_status") or item.get("status") or "").lower()
    return (
        PriorStatus.EXTERNAL_PRIOR
        if review in {"approved", "accepted", "governed", "accepted_as_literature_evidence"}
        else PriorStatus.PROVISIONAL_PRIOR
    )


def compile_typed_priors(
    evidence_ir: Iterable[Any],
    *,
    applicability_refs: dict[str, str] | None = None,
) -> PriorObjectSet:
    """Compile typed priors without fitting or pseudo-probability.

    Disjoint parameter ranges are emitted as separate conflicting priors.  They
    are never averaged into a falsely precise range.
    """
    applicability_refs = applicability_refs or {}
    rows = [_dump(item) for item in evidence_ir]
    rows = [row for row in rows if str(row.get("review_status") or "").lower() != "rejected"]
    priors: list[Any] = []
    parameter_priors: dict[str, list[ParameterPrior]] = defaultdict(list)
    input_refs: list[PriorRef] = []

    for item in rows:
        evidence_id = str(
            item.get("evidence_id")
            or item.get("claim_id")
            or item.get("id")
            or _stable_id("evidence", item)
        )
        evidence_ref = PriorRef(type="EvidenceIR", id=evidence_id)
        input_refs.append(evidence_ref)
        app_id = applicability_refs.get(evidence_id) or item.get("applicability_ref")
        app_refs = [PriorRef(type="ApplicabilityReport", id=str(app_id))] if app_id else []
        claim_type = str(item.get("claim_type") or item.get("semantic_role") or "").lower()
        claim = dict(item.get("claim") or item.get("value") or {})
        parameter = str(item.get("parameter") or claim.get("parameter") or "")
        lower = claim.get("lower", item.get("lower"))
        upper = claim.get("upper", item.get("upper"))
        unit = str(claim.get("unit") or item.get("unit") or "dimensionless")
        uncertainty = _uncertainty(item)
        prior_status = _prior_status(item)

        is_numeric_range = (
            isinstance(lower, (int, float))
            and isinstance(upper, (int, float))
            and float(lower) < float(upper)
        )
        if is_numeric_range and (
            claim_type in {"threshold", "material_property", "parameter_prior"}
            or parameter in _PHYSICAL_PARAMETERS
        ):
            assert isinstance(lower, (int, float))
            assert isinstance(upper, (int, float))
            semantics = str(claim.get("parameter_semantics") or "PROVISIONAL").upper()
            if semantics not in {"PHYSICAL", "EFFECTIVE", "PROVISIONAL"}:
                semantics = "PROVISIONAL"
            prior = ParameterPrior(
                prior_id=_stable_id(
                    "parameter-prior",
                    {
                        "evidence": evidence_id,
                        "parameter": parameter,
                        "lower": lower,
                        "upper": upper,
                    },
                ),
                parameter=parameter or "F_th_eff",
                lower=float(lower),
                upper=float(upper),
                unit=unit,
                parameter_semantics=semantics,  # type: ignore[arg-type]
                assumptions=list(claim.get("assumptions") or []),
                input_refs=[evidence_ref],
                evidence_refs=[evidence_ref],
                applicability_refs=app_refs,
                provenance=[evidence_ref, *app_refs],
                uncertainty=uncertainty,
                status=prior_status,
            )
            priors.append(prior)
            parameter_priors[prior.parameter].append(prior)
            continue

        model_family = str(claim.get("model_family") or item.get("model_family") or "")
        if model_family and claim_type in {
            "mechanism_model",
            "functional_shape",
            "formula",
            "mechanism",
        }:
            priors.append(
                MechanismModelPrior(
                    prior_id=_stable_id(
                        "mechanism-prior", {"evidence": evidence_id, "model": model_family}
                    ),
                    model_family=model_family,
                    alternatives=list(claim.get("alternatives") or []),
                    supporting_evidence=[evidence_ref],
                    assumptions=list(claim.get("assumptions") or []),
                    input_refs=[evidence_ref],
                    evidence_refs=[evidence_ref],
                    applicability_refs=app_refs,
                    provenance=[evidence_ref, *app_refs],
                    uncertainty=uncertainty,
                    status=prior_status,
                )
            )
            continue

        if (
            claim_type
            in {"range_preference", "reported_optimum", "path_strategy", "planning_strategy"}
            or is_numeric_range
        ):
            path_families = list(claim.get("path_families") or [])
            preference = str(
                claim.get("preference")
                or item.get("text")
                or item.get("claim_text")
                or f"soft preference for {parameter or 'path strategy'}"
            )
            priors.append(
                PlanningPreferencePrior(
                    prior_id=_stable_id(
                        "planning-prior",
                        {"evidence": evidence_id, "parameter": parameter, "claim": claim},
                    ),
                    path_families=path_families,
                    parameter=parameter or None,
                    lower=(
                        float(lower)
                        if isinstance(lower, (int, float)) and is_numeric_range
                        else None
                    ),
                    upper=(
                        float(upper)
                        if isinstance(upper, (int, float)) and is_numeric_range
                        else None
                    ),
                    unit=unit if is_numeric_range else None,
                    preference=preference,
                    hard_constraint=False,
                    assumptions=[
                        "literature planning ranges are soft guidance, never machine hard bounds"
                    ],
                    input_refs=[evidence_ref],
                    evidence_refs=[evidence_ref],
                    applicability_refs=app_refs,
                    provenance=[evidence_ref, *app_refs],
                    uncertainty=uncertainty,
                    status=prior_status,
                )
            )

    conflicts: list[PriorConflict] = []
    for parameter, candidates in parameter_priors.items():
        involved: set[str] = set()
        for index, left in enumerate(candidates):
            for right in candidates[index + 1 :]:
                if left.upper < right.lower or right.upper < left.lower:
                    involved.update((left.prior_id, right.prior_id))
        if not involved:
            continue
        conflict_id = _stable_id(
            "prior-conflict", {"parameter": parameter, "priors": sorted(involved)}
        )
        for prior in candidates:
            if prior.prior_id in involved:
                prior.conflict_status = ConflictStatus.CONFLICT
                prior.conflict_group_id = conflict_id
        conflicts.append(
            PriorConflict(
                conflict_id=conflict_id,
                parameter=parameter,
                prior_refs=[
                    PriorRef(type="ParameterPrior", id=value) for value in sorted(involved)
                ],
                reason="disjoint evidence ranges",
            )
        )

    payload = [prior.model_dump(mode="json") for prior in priors]
    warnings = (
        ["UNKNOWN applicability remains qualitative UNKNOWN uncertainty"]
        if any(prior.uncertainty == PriorUncertainty.UNKNOWN for prior in priors)
        else []
    )
    if conflicts:
        warnings.append(
            "conflicting evidence preserved separately; human/scientific resolution required"
        )
    return PriorObjectSet(
        prior_set_id=_stable_id("prior-set", payload),
        input_refs=list({ref.id: ref for ref in input_refs}.values()),
        priors=priors,
        conflicts=conflicts,
        warnings=warnings,
        provenance=list({ref.id: ref for ref in input_refs}.values()),
    )
