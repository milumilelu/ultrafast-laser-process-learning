"""Deterministic hard-constraint validator (Layer 4 step 2).

Authority: deterministic hard constraints > LLM proposal > weak hints.
"""

from __future__ import annotations

from ultrafast_ingestion.conditions.models import (
    ValidatedRelationGraph,
    ValidationErrorCode,
    ValidationRejection,
)
from ultrafast_ingestion.graph.models import EdgeType, MentionRole
from ultrafast_ingestion.linking.models import LinkDecision, RelationType


def validate(graph: ValidatedRelationGraph) -> ValidatedRelationGraph:
    """Run the 9 checks over all proposals. Mutates and returns graph."""
    for proposal in graph.accepted:
        rejections = _check(proposal, graph)
        for r in rejections:
            graph.rejected.append(r)
    graph.accepted = [
        p
        for p in graph.accepted
        if not any(r.proposal_id == p.proposal_id for r in graph.rejected)
    ]
    return graph


def _check(proposal, graph: ValidatedRelationGraph) -> list[ValidationRejection]:
    pid = proposal.proposal_id
    out: list[ValidationRejection] = []

    def reject(code: ValidationErrorCode, detail: str = "") -> None:
        out.append(ValidationRejection(proposal_id=pid, error_code=code, detail=detail))

    # 1. mention existence
    missing = [m for m in proposal.mention_ids if m not in graph.graph.mentions]
    if missing:
        reject(ValidationErrorCode.UNKNOWN_MENTION, f"unknown mentions: {missing}")

    # 2. supporting edges exist (index-based "E<n>")
    for ref in proposal.supporting_edge_ids:
        if not ref.startswith("E"):
            reject(ValidationErrorCode.UNKNOWN_EDGE, f"malformed edge ref: {ref}")
            continue
        idx = int(ref[1:])
        if idx >= len(graph.graph.edges):
            reject(ValidationErrorCode.UNKNOWN_EDGE, f"edge index out of range: {ref}")

    if proposal.decision == LinkDecision.ABSTAIN:
        return out

    mentions = [
        graph.graph.mentions[m]
        for m in proposal.mention_ids
        if m in graph.graph.mentions
    ]
    roles = {
        m.mention_id: graph.graph.roles.get(m.mention_id, MentionRole.UNCLEAR)
        for m in mentions
    }
    edges = graph.graph.edges

    # 3. rejected mentions never enter conditions
    if proposal.decision in (LinkDecision.LINK, LinkDecision.ASSIGN_SCOPE):
        for m in mentions:
            if roles[m.mention_id] == MentionRole.REJECTED:
                reject(ValidationErrorCode.REJECTED_MENTION_IN_CONDITION, m.mention_id)

    if proposal.decision == LinkDecision.LINK:
        if proposal.relation != RelationType.SAME_EXPERIMENT and proposal.relation != RelationType.SEPARATE_EXPERIMENT:
            reject(ValidationErrorCode.UNKNOWN_RELATION_FOR_DECISION, f"LINK with {proposal.relation}")

        a, b = proposal.mention_ids
        # 4. hard negative: MUTUALLY_EXCLUSIVE edges forbid SAME_EXPERIMENT
        if proposal.relation == RelationType.SAME_EXPERIMENT and any(
            e.type == EdgeType.MUTUALLY_EXCLUSIVE
            and {e.source_mention_id, e.target_mention_id} == {a, b}
            for e in edges
        ):
            reject(
                ValidationErrorCode.CONTRADICTS_HARD_STRUCTURAL_CONSTRAINT,
                f"MUTUALLY_EXCLUSIVE between {a} and {b}",
            )

        # 5. comparison pollution
        def _has_comparison(mid: str) -> bool:
            return any(
                e.type == EdgeType.COMPARISON_ONLY and mid in (e.source_mention_id, e.target_mention_id)
                for e in edges
            ) or roles.get(mid, MentionRole.UNCLEAR) == MentionRole.REJECTED

        if proposal.relation == RelationType.SAME_EXPERIMENT:
            if any(_has_comparison(m) for m in (a, b)):
                reject(ValidationErrorCode.COMPARISON_POLLUTION, f"comparison mention in {a},{b}")

            # 6. measurement pollution: roles must be compatible
            ra, rb = roles.get(a, MentionRole.UNCLEAR), roles.get(b, MentionRole.UNCLEAR)
            if {ra, rb} == {MentionRole.MEASUREMENT, MentionRole.PROCESSING}:
                reject(ValidationErrorCode.MEASUREMENT_POLLUTION, f"mixed roles {ra}/{rb}")
            if (
                ra == MentionRole.MEASUREMENT
                and rb == MentionRole.MEASUREMENT
                and proposal.target_role
                and proposal.target_role.value != "MEASUREMENT"
            ):
                reject(ValidationErrorCode.MEASUREMENT_POLLUTION, "measurement pair into non-measurement role")

        # 7. same-parameter conflict: warn, never resolve
        if len(mentions) >= 2:
            pa = graph.graph.mentions.get(a)
            pb = graph.graph.mentions.get(b)
            if (
                pa is not None
                and pb is not None
                and pa.parameter == pb.parameter
                and pa.normalized_unit == pb.normalized_unit
                and sorted(pa.values) != sorted(pb.values)
            ):
                graph.warnings.append(
                    f"{pid}: same-parameter conflict {pa.raw_text} vs {pb.raw_text} -> CONFLICT_PRESERVED"
                )

    # 8. provenance: every mention in a LINK must carry an anchor
    if proposal.decision == LinkDecision.LINK:
        for m in mentions:
            if m.anchor is None:
                reject(ValidationErrorCode.MISSING_PROVENANCE, m.mention_id)

    # 9. ungrounded value generation: proposals carry no values (checked at
    # parse time); here we assert the invariant on the dataclass
    for field_name in ("value", "values", "normalized_value", "lower", "upper"):
        if getattr(proposal, field_name, None) is not None:
            reject(ValidationErrorCode.UNGROUNDED_VALUE_GENERATION, field_name)

    if proposal.decision == LinkDecision.SEPARATE and proposal.relation not in (
        RelationType.SEPARATE_EXPERIMENT,
        RelationType.MUTUALLY_EXCLUSIVE,
    ):
        reject(ValidationErrorCode.UNKNOWN_RELATION_FOR_DECISION, f"SEPARATE with {proposal.relation}")
    return out
