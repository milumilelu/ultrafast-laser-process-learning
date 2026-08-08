"""Requirement-first retrieval; exact target geometry is only a ranking hint."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from packages.scientific_computation.capability import infer_interaction_topology


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetrievalQueryPlan(StrictModel):
    schema_version: str = "requirement-retrieval-v1"
    query_plan_id: str
    requirement_id: str
    requirement_type: str
    scientific_question: str
    hard_facets: dict[str, list[str]]
    soft_facets: dict[str, list[str]]
    query_terms: list[str]
    geometry_is_hard_filter: bool = False
    reason_codes: list[str] = Field(default_factory=list)


class RetrievalCandidate(StrictModel):
    candidate_id: str
    title: str
    abstract: str = ""
    material: str | None = None
    material_family: str | None = None
    pulse_regime: str | None = None
    interaction_topology: str | None = None
    geometry: str | None = None
    evidence_roles: list[str] = Field(default_factory=list)


class RankedCandidate(StrictModel):
    candidate: RetrievalCandidate
    score: float
    recalled: bool
    matched_facets: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


_TYPE_TERMS: dict[str, list[str]] = {
    "PARAMETER_PRIOR": ["ablation threshold", "fluence threshold", "incubation"],
    "threshold": ["ablation threshold", "fluence threshold", "damage threshold"],
    "MECHANISM_MODEL": ["incubation model", "multi-pulse", "ablation mechanism"],
    "process_mechanism": ["ablation mechanism", "nonlinear absorption", "incubation"],
    "MATERIAL_PROPERTY": ["material property", "ablation threshold"],
    "PATH_STRATEGY": ["toolpath", "scan strategy", "hatch", "raster"],
    "MODEL_VALIDATION": ["validation", "crater morphology", "groove morphology"],
}


def _stable_id(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"query-plan-{hashlib.sha256(raw).hexdigest()[:16]}"


def _as_dict(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)


def plan_retrieval(requirement: Any, task: Any) -> RetrievalQueryPlan:
    req = _as_dict(requirement)
    task_data = _as_dict(task)
    req_type = str(req.get("type") or "OTHER")
    question = str(req.get("scientific_question") or req.get("question") or req_type)
    material = str(task_data.get("material") or "").strip()
    laser = str(task_data.get("laser_type") or task_data.get("pulse_regime") or "").strip()
    target = str(task_data.get("target") or task_data.get("objective_metric") or "").strip()
    geometry = str(task_data.get("geometry_type") or "").strip()
    topology = infer_interaction_topology(geometry).value
    terms = [material, *_TYPE_TERMS.get(req_type, []), *_TYPE_TERMS.get(req_type.upper(), [])]
    terms = list(dict.fromkeys(term for term in terms if term))
    payload = {"requirement": req, "task": task_data, "terms": terms}
    return RetrievalQueryPlan(
        query_plan_id=_stable_id(payload),
        requirement_id=str(req.get("requirement_id") or "requirement"),
        requirement_type=req_type,
        scientific_question=question,
        hard_facets={
            "material_or_family": [material] if material else [],
            "pulse_regime": [laser] if laser else [],
        },
        soft_facets={
            "interaction_topology": [topology] if topology != "UNKNOWN" else [],
            "target_metric": [target] if target else [],
            "target_geometry_hint": [geometry] if geometry else [],
        },
        query_terms=terms,
        geometry_is_hard_filter=False,
        reason_codes=[
            "requirement_type_drives_scientific_terms",
            "exact_geometry_is_ranking_hint_only",
        ],
    )


def rank_candidates(
    plan: RetrievalQueryPlan,
    candidates: list[RetrievalCandidate | dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[RankedCandidate]:
    """Rank candidates while preserving cross-geometry scientific recall."""
    material_terms = {value.lower() for value in plan.hard_facets.get("material_or_family", [])}
    pulse_terms = {value.lower() for value in plan.hard_facets.get("pulse_regime", [])}
    topology_terms = {value.lower() for value in plan.soft_facets.get("interaction_topology", [])}
    geometry_terms = {value.lower() for value in plan.soft_facets.get("target_geometry_hint", [])}
    scientific_terms = {value.lower() for value in plan.query_terms}
    ranked: list[RankedCandidate] = []
    for raw in candidates:
        candidate = (
            raw if isinstance(raw, RetrievalCandidate) else RetrievalCandidate.model_validate(raw)
        )
        text = f"{candidate.title} {candidate.abstract}".lower()
        candidate_materials = {
            value.lower() for value in (candidate.material, candidate.material_family) if value
        }
        material_match = (
            not material_terms
            or bool(material_terms.intersection(candidate_materials))
            or any(term in text for term in material_terms)
        )
        # Missing pulse metadata is UNKNOWN, not MISMATCH.  Keep the candidate
        # recallable and let reconstructibility/applicability govern it later.
        pulse_match = (
            not pulse_terms
            or candidate.pulse_regime is None
            or (candidate.pulse_regime or "").lower() in pulse_terms
            or any(term in text for term in pulse_terms)
            or ("fs" in pulse_terms and "femtosecond" in text)
            or ("ps" in pulse_terms and "picosecond" in text)
        )
        matched: list[str] = []
        score = 0.0
        if material_match:
            score += 5.0
            matched.append("material_or_family")
        if pulse_match:
            score += 1.5
            matched.append("pulse_regime")
        role_terms = {role.lower() for role in candidate.evidence_roles}
        requirement_role = plan.requirement_type.lower()
        term_hits = sum(1 for term in scientific_terms if term and term in text)
        if term_hits:
            score += min(4.0, float(term_hits))
            matched.append("scientific_question")
        if requirement_role in role_terms or any(role in text for role in role_terms):
            score += 2.0
            matched.append("requirement_type")
        if topology_terms and (candidate.interaction_topology or "").lower() in topology_terms:
            score += 1.0
            matched.append("interaction_topology")
        if geometry_terms and (candidate.geometry or "").lower() in geometry_terms:
            score += 0.25
            matched.append("exact_geometry_hint")
        recalled = (
            material_match
            and pulse_match
            and (term_hits > 0 or requirement_role in role_terms or bool(role_terms))
        )
        ranked.append(
            RankedCandidate(
                candidate=candidate,
                score=score,
                recalled=recalled,
                matched_facets=matched,
                reason_codes=[
                    "geometry_not_hard_filtered",
                    "material_mismatch" if not material_match else "material_relevant",
                ],
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.candidate.candidate_id))
    selected = [item for item in ranked if item.recalled]
    return selected[:limit] if limit is not None else selected
