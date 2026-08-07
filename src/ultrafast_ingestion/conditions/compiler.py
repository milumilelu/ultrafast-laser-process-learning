"""Deterministic condition compiler (Layer 4 step 2, no LLM).

Connected components over validated SAME_EXPERIMENT relations
(+ structural STRONG edges + SAME_PARAMETER_GROUP candidates), scope
inheritance via ASSIGN_SCOPE/GLOBAL edges, role partition, conflict
preservation (F4). Values only ever come from input mentions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ultrafast_ingestion.conditions.models import (
    ConditionField,
    ExperimentalConditionSpec,
    FieldStatus,
    ValidatedRelationGraph,
)
from ultrafast_ingestion.graph.models import EdgeType, MentionRole
from ultrafast_ingestion.linking.models import (
    ConditionRole,
    LinkDecision,
    RelationType,
    Scope,
)
from ultrafast_ingestion.models.provenance import stable_hash

PROCESSING_ROLE = ConditionRole.PROCESSING
MEASUREMENT_ROLE = ConditionRole.MEASUREMENT


@dataclass(slots=True)
class CompileResult:
    conditions: list[ExperimentalConditionSpec] = field(default_factory=list)
    unassigned_mentions: list[str] = field(default_factory=list)
    synthetic_condition_count: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)

    def synthetic_condition_rate(self) -> float:
        total = len(self.conditions)
        return self.synthetic_condition_count / total if total else 0.0


def _union_find(items: list[str]):
    parent = {x: x for x in items}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    return find, union


def compile_conditions(graph: ValidatedRelationGraph) -> CompileResult:
    mentions = graph.graph.mentions
    roles = graph.graph.roles

    # global mentions (ASSIGN_SCOPE PAPER_GLOBAL only; structural
    # GLOBAL_SCOPE_CANDIDATE edges are merge edges instead)
    global_ids: list[str] = []
    for p in graph.accepted_decisions():
        if p.decision == LinkDecision.ASSIGN_SCOPE and p.scope == Scope.PAPER_GLOBAL:
            global_ids.extend(p.mention_ids)
    global_ids = [g for g in sorted(set(global_ids)) if g in mentions]

    # ABSTAIN mentions: their parameters stay LINKAGE_AMBIGUOUS wherever
    # they appear (Paper 11: 10 kHz base vs up-to-1 MHz capability)
    abstained_params: set[str] = set()
    for p in graph.accepted:
        if p.decision == LinkDecision.ABSTAIN:
            for mid in p.mention_ids:
                m = mentions.get(mid)
                if m is not None:
                    abstained_params.add(m.parameter)

    # adjacency sources (in authority order)
    merge_pairs: list[tuple[str, str]] = []
    for p in graph.accepted_decisions():
        if p.decision == LinkDecision.LINK and p.relation == RelationType.SAME_EXPERIMENT:
            merge_pairs.append((p.mention_ids[0], p.mention_ids[1]))
    # structural STRONG same-experiment edges (tables)
    for e in graph.graph.edges:
        if e.type == EdgeType.SAME_EXPERIMENT_CANDIDATE and e.edge_strength.value == "STRONG":
            merge_pairs.append((e.source_mention_id, e.target_mention_id))
    # prose parameter-group candidates (weak) - components, not facts
    for e in graph.graph.edges:
        if e.type == EdgeType.SAME_PARAMETER_GROUP:
            merge_pairs.append((e.source_mention_id, e.target_mention_id))
    # explicit global-statement links
    for e in graph.graph.edges:
        if e.type == EdgeType.GLOBAL_SCOPE_CANDIDATE:
            merge_pairs.append((e.source_mention_id, e.target_mention_id))

    valid_ids = [
        m
        for m in mentions
        if m not in global_ids
        and roles.get(m, MentionRole.REJECTED) != MentionRole.REJECTED
    ]
    valid_set = set(valid_ids)
    find, union = _union_find(valid_ids)

    def _role_compatible(x: str, y: str) -> bool:
        rx, ry = roles.get(x, MentionRole.UNCLEAR), roles.get(y, MentionRole.UNCLEAR)
        return {rx, ry} != {MentionRole.PROCESSING, MentionRole.MEASUREMENT}

    for a, b in merge_pairs:
        if a in valid_set and b in valid_set and _role_compatible(a, b):
            union(a, b)

    components: dict[str, list[str]] = {}
    for mid in valid_ids:
        components.setdefault(find(mid), []).append(mid)

    # role per component
    def _component_role(ids: list[str]) -> ConditionRole:
        role_values = {roles.get(i, MentionRole.UNCLEAR) for i in ids}
        if MentionRole.PROCESSING in role_values:
            return PROCESSING_ROLE
        if role_values == {MentionRole.MEASUREMENT}:
            return MEASUREMENT_ROLE
        return ConditionRole.UNKNOWN

    conditions: list[ExperimentalConditionSpec] = []
    synthetic = 0
    for idx, ids in enumerate(components.values()):
        if len(ids) < 2 and not (set(ids) & set(global_ids)):
            continue  # singleton mentions stay unassigned
        role = _component_role(ids)
        first = mentions[ids[0]]
        paper_id = first.anchor.paper_id if first.anchor else ""
        cid = stable_hash(paper_id, "cond", str(idx))
        spec = ExperimentalConditionSpec(
            condition_id=cid,
            paper_id=paper_id,
            role=role,
            scope=Scope.EXPERIMENT_GROUP,
            mention_ids=sorted(ids),
        )
        member_ids = sorted(set(ids) | set(global_ids))
        spec.mention_ids = member_ids
        # synthetic condition: component contains a MUTUALLY_EXCLUSIVE pair
        # or mixes PROCESSING and MEASUREMENT roles (must be impossible
        # after validation; counted here as an honest safety net)
        forbidden_edges = {
            (e.source_mention_id, e.target_mention_id)
            for e in graph.graph.edges
            if e.type == EdgeType.MUTUALLY_EXCLUSIVE
        }
        member_set = set(member_ids)
        if any({a, b} <= member_set for a, b in forbidden_edges):
            synthetic += 1
        role_values = {roles.get(i, MentionRole.UNCLEAR) for i in ids}
        if MentionRole.PROCESSING in role_values and MentionRole.MEASUREMENT in role_values:
            synthetic += 1
        # fields grouped by parameter
        by_param: dict[str, list] = {}
        for mid in member_ids:
            m = mentions[mid]
            by_param.setdefault(m.parameter, []).append(m)
        for param, ms in by_param.items():
            values: list[float] = []
            anchors: list[str] = []
            strength = ""
            for m in ms:
                for v in m.values:
                    if v not in values:
                        values.append(v)
                if m.anchor:
                    anchors.append(m.anchor.quote_fingerprint)
                strength = strength or str(m.context_class)
            unit = ms[0].normalized_unit
            # conflict = multiple DISTINCT mentions with differing value
            # sets; a single RANGE/LIST mention is one reported value shape
            value_sets = {tuple(m.values) for m in ms}
            status = FieldStatus.REPORTED_CLEAR
            if len(value_sets) > 1:
                status = FieldStatus.CONFLICT_PRESERVED
            if param in abstained_params:
                status = FieldStatus.LINKAGE_AMBIGUOUS
            spec.fields[param] = ConditionField(
                parameter=param,
                status=status,
                values=values,
                unit=unit,
                provenance_anchor_ids=sorted(set(anchors)),
                evidence_strength=strength,
            )
        conditions.append(spec)

    assigned = {m for c in conditions for m in c.mention_ids}
    unassigned = [
        m
        for m in valid_ids
        if m not in assigned
        and roles.get(m) != MentionRole.REJECTED
    ]

    return CompileResult(
        conditions=conditions,
        unassigned_mentions=unassigned,
        synthetic_condition_count=synthetic,
        metrics={
            "conditions": len(conditions),
            "unassigned_mentions": len(unassigned),
            "synthetic_condition_count": synthetic,
        },
    )
