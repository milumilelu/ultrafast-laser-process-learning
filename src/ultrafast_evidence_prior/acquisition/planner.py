"""Deterministic gap-to-query planning and strict query-plan validation."""

from __future__ import annotations

import hashlib
import re

from ultrafast_evidence_prior.schemas import (
    EvidenceCoverageReport,
    KnowledgeRequirementType,
    KnowledgeRequirementV1,
    RequirementCoverageSpec,
    SupplementalQuery,
    SupplementalQueryPlan,
)

_SECTION_POLICY: dict[KnowledgeRequirementType, list[str]] = {
    KnowledgeRequirementType.MATERIAL_PROPERTY: ["table", "methods", "results"],
    KnowledgeRequirementType.PROCESS_OBSERVATION: ["results", "table", "methods"],
    KnowledgeRequirementType.PARAMETER_EFFECT: ["results", "discussion", "conclusion"],
    KnowledgeRequirementType.REPORTED_OPTIMUM: ["results", "table", "discussion"],
    KnowledgeRequirementType.MECHANISM: ["discussion", "results", "conclusion"],
    KnowledgeRequirementType.PROCESS_METHOD: ["methods", "experimental_setup", "table"],
}


class DeterministicGapQueryPlanner:
    version = "deterministic-gap-query-planner-v1"

    def plan(
        self,
        requirement: KnowledgeRequirementV1,
        spec: RequirementCoverageSpec,
        report: EvidenceCoverageReport,
        *,
        round_number: int = 1,
        top_k: int = 3,
        previous_queries: list[str] | None = None,
    ) -> SupplementalQueryPlan:
        if requirement.requirement_type == KnowledgeRequirementType.MATERIAL_IDENTITY:
            gaps = []
        else:
            importance = {item.facet_id: item.importance for item in spec.facets}
            gaps = sorted(
                report.gaps,
                key=lambda item: (importance.get(item.facet_id) != "CORE", item.facet_id),
            )
        previous = {_canonical(item) for item in previous_queries or []}
        queries: list[SupplementalQuery] = []
        for gap in gaps:
            terms = [
                str(requirement.conditions.get("material") or ""),
                requirement.target_metric.value.replace("_", " "),
                *gap.suggested_terms,
            ]
            query_text = " ".join(dict.fromkeys(item.strip() for item in terms if item.strip()))
            if not query_text or _canonical(query_text) in previous:
                continue
            digest = hashlib.sha256(
                f"{requirement.requirement_id}\n{gap.facet_id}\n{query_text}".encode()
            ).hexdigest()[:16]
            queries.append(
                SupplementalQuery(
                    query_id=f"supplemental-query-{digest}",
                    gap_ids=[gap.facet_id],
                    query_text=query_text[:256],
                    preferred_sections=_SECTION_POLICY.get(requirement.requirement_type, []),
                    top_k=top_k,
                )
            )
            previous.add(_canonical(query_text))
            if len(queries) >= 3:
                break
        payload = "\n".join(item.query_id for item in queries)
        plan_digest = hashlib.sha256(
            f"{requirement.requirement_id}\n{round_number}\n{payload}".encode()
        ).hexdigest()[:16]
        return SupplementalQueryPlan(
            plan_id=f"supplemental-plan-{plan_digest}",
            round=round_number,
            planner_type="DETERMINISTIC",
            queries=queries,
            reason_codes=["requirement_specific_coverage_gaps"],
        )


def validate_query_plan(
    plan: SupplementalQueryPlan,
    requirement: KnowledgeRequirementV1,
    report: EvidenceCoverageReport,
    *,
    known_paper_ids: set[str] | None = None,
) -> None:
    if len(plan.queries) > 3:
        raise ValueError("query_plan_exceeds_query_budget")
    gap_ids = {item.facet_id for item in report.gaps}
    material = _canonical(str(requirement.conditions.get("material") or ""))
    seen: set[str] = set()
    for query in plan.queries:
        if not set(query.gap_ids) <= gap_ids:
            raise ValueError("query_plan_references_unknown_gap")
        normalized = _canonical(query.query_text)
        if normalized in seen:
            raise ValueError("query_plan_contains_duplicate_query")
        seen.add(normalized)
        if material and material not in normalized:
            raise ValueError("query_plan_drops_material_anchor")
        if query.paper_ids and not set(query.paper_ids) <= (known_paper_ids or set()):
            raise ValueError("query_plan_references_unknown_paper")


def _canonical(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", value.casefold()).strip()
