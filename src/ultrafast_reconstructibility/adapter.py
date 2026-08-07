"""M6-1: ExperimentalConditionSpec → SourceConditionSpec projection.

Deterministic projection only - no new extraction, no new semantic judgment.
coverage_status comes from the parser audit (pilot 5 = TEXT_COVERAGE_OK);
it is an input to this adapter, never inferred from missing fields.
"""

from __future__ import annotations

from typing import Any

from ultrafast_ingestion.conditions.models import ExperimentalConditionSpec
from ultrafast_ingestion.mentions.models import (
    AcceptanceStatus,
    ConditionMention,
    ContextClass,
    MentionValueType,
)
from ultrafast_ingestion.models.document import ScientificDocument
from ultrafast_reconstructibility.models import (
    CoverageStatus,
    FieldStatus,
    SourceConditionSpec,
    SourceField,
    ValueShape,
)

_FIELD_STATUS_MAP = {
    "REPORTED_CLEAR": FieldStatus.REPORTED_CLEAR,
    "CONFLICT_PRESERVED": FieldStatus.CONFLICT_PRESERVED,
    "LINKAGE_AMBIGUOUS": FieldStatus.LINKAGE_AMBIGUOUS,
}


def to_source_condition_spec(
    condition: ExperimentalConditionSpec,
    *,
    document_version_id: str = "",
    coverage_status: CoverageStatus = CoverageStatus.TEXT_COVERAGE_OK,
) -> SourceConditionSpec:
    """Project one ExperimentalConditionSpec into physics-consumable form."""
    fields: list[SourceField] = []
    for parameter, field in condition.fields.items():
        fields.append(
            SourceField(
                parameter=parameter,
                values=tuple(field.values),
                unit=field.unit,
                field_status=_FIELD_STATUS_MAP.get(
                    field.status.value, FieldStatus.REPORTED_CLEAR
                ),
                provenance_anchor_ids=tuple(field.provenance_anchor_ids),
                value_shape=ValueShape(field.value_shape),
            )
        )
    fields.sort(key=lambda f: f.parameter)
    return SourceConditionSpec(
        condition_id=condition.condition_id,
        paper_id=condition.paper_id,
        document_version_id=document_version_id,
        role=condition.role.value if hasattr(condition.role, "value") else str(condition.role),
        scope=condition.scope.value if hasattr(condition.scope, "value") else str(condition.scope),
        coverage_status=coverage_status,
        fields=tuple(fields),
    )


def paper_level_spec(
    document: ScientificDocument,
    mentions: list[ConditionMention],
    *,
    cells: list[Any] | None = None,
    coverage_status: CoverageStatus = CoverageStatus.TEXT_COVERAGE_OK,
) -> SourceConditionSpec:
    """Paper-level source fields, aggregated across processing mentions
    AND table cells.

    A1 root-cause fix (COMPILER_SINGLETON): condition compilation drops
    singleton mentions (e.g. a paper whose frequency/scan_speed never join a
    >=2-mention component), so per-condition projection loses fields the
    paper explicitly reports. The human Level-2 judgement is paper-level
    ("main processing condition"), so evaluation needs a paper-level view.
    Table cells (TableCell with a known parameter) join the aggregation so
    parameters reported only in tables still reach the paper level.

    Aggregation rule: PROCESS_CONTEXT mentions are authoritative per
    parameter; UNCLEAR mentions are used only when a parameter has no
    PROCESS_CONTEXT value (avoids noise values like a stray "100 Hz" next to
    the processing "100 kHz"). Measurement-context mentions are excluded.
    Multiple PROCESS_CONTEXT values -> CONFLICT_PRESERVED.
    """
    by_param: dict[str, list[ConditionMention]] = {}
    for mention in mentions:
        if mention.acceptance_status != AcceptanceStatus.ACCEPTED:
            continue
        if mention.context_class not in (
            ContextClass.PROCESS_CONTEXT,
            ContextClass.UNCLEAR,
        ):
            continue
        by_param.setdefault(mention.parameter, []).append(mention)

    for cell in cells or []:
        if cell.parameter in ("unknown", ""):
            continue
        by_param.setdefault(cell.parameter, []).append(cell)

    fields: list[SourceField] = []
    for parameter, group in sorted(by_param.items()):
        mentions_only = [
            m for m in group if isinstance(m, ConditionMention)
        ]
        process_group = [
            m for m in mentions_only if m.context_class == ContextClass.PROCESS_CONTEXT
        ]
        selected = process_group if process_group else mentions_only or group
        units = {_unit_of(m) for m in selected}
        value_sets = {tuple(_values_of(m)) for m in selected}
        status = (
            FieldStatus.CONFLICT_PRESERVED
            if len(value_sets) > 1 or len(units) > 1
            else FieldStatus.REPORTED_CLEAR
        )
        first = selected[0]
        fields.append(
            SourceField(
                parameter=parameter,
                values=tuple(_values_of(first)),
                unit=_unit_of(first),
                field_status=status,
                provenance_anchor_ids=tuple(
                    m.anchor.quote_fingerprint
                    for m in selected
                    if isinstance(m, ConditionMention) and m.anchor
                ),
                value_shape=_shape_of(selected),
            )
        )
    return SourceConditionSpec(
        condition_id="paper-level",
        paper_id=document.paper_id,
        document_version_id=document.document_version_id,
        role="PROCESSING",
        scope="PAPER_LEVEL",
        coverage_status=coverage_status,
        fields=tuple(fields),
    )


def _unit_of(item: Any) -> str:
    if isinstance(item, ConditionMention):
        return item.normalized_unit
    return item.unit


def _values_of(item: Any) -> list[float]:
    if isinstance(item, ConditionMention):
        return list(item.values)
    return [item.value] if item.value2 is None else [item.value, item.value2]


def _shape_of(selected: list[Any]) -> ValueShape:
    """V2-2: aggregate value shape across selected mentions/cells.

    A single RANGE/LIST mention (or a table cell with value2) is a range/list
    report, not a point observation.
    """
    for item in selected:
        if isinstance(item, ConditionMention):
            if item.value_type == MentionValueType.RANGE:
                return ValueShape.RANGE
            if item.value_type == MentionValueType.LIST:
                return ValueShape.LIST
        elif item.value2 is not None:
            return ValueShape.RANGE
    return ValueShape.POINT
