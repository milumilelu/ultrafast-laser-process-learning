"""Condition-aware cross-paper reduction over mechanically validated evidence."""

from __future__ import annotations

import json
import math
from typing import Any

from ultrafast_knowledge.evidence_pipeline.schemas import (
    ExtractionStatus,
    PaperEvidence,
    RequirementEvidence,
)
from ultrafast_requirements.schemas import Requirement
from ultrafast_shared.units import convert, normalize_unit


class CrossPaperEvidenceAggregator:
    """Reduce paper-local results without combining incompatible conditions."""

    def aggregate(
        self,
        requirement: Requirement,
        items: list[PaperEvidence],
    ) -> RequirementEvidence:
        valid = [item for item in items if item.evidence.valid]
        found = [item for item in valid if item.evidence.status == ExtractionStatus.FOUND]
        exact: list[PaperEvidence] = []
        incomplete: list[PaperEvidence] = []
        for item in found:
            match = self._condition_match(requirement.conditions, item.evidence.conditions)
            if match == "exact":
                exact.append(item)
            elif match == "incomplete":
                incomplete.append(item)
        if not exact:
            status = ExtractionStatus.INSUFFICIENT if incomplete else ExtractionStatus.NOT_FOUND
            return RequirementEvidence(
                requirement_id=requirement.requirement_id,
                quantity=requirement.quantity,
                status=status,
                conditions=requirement.conditions,
                source_block_refs=self._refs(incomplete),
                confidence=max((item.evidence.confidence for item in incomplete), default=0.0),
                validation_state="validated",
                governance_status=self._governance(incomplete) if incomplete else "unreviewed",
            )

        groups: dict[str, list[PaperEvidence]] = {}
        for item in exact:
            groups.setdefault(self._value_key(item.evidence), []).append(item)
        if len(groups) > 1:
            conflicts = [
                {
                    "paper_id": item.paper_id,
                    "document_version_id": item.document_version_id,
                    "value": item.evidence.value,
                    "lower": item.evidence.lower,
                    "upper": item.evidence.upper,
                    "unit": item.evidence.unit,
                    "conditions": item.evidence.conditions,
                    "source_block_refs": item.evidence.source_block_refs,
                }
                for group in groups.values()
                for item in group
            ]
            return RequirementEvidence(
                requirement_id=requirement.requirement_id,
                quantity=requirement.quantity,
                status=ExtractionStatus.CONFLICT,
                conditions=requirement.conditions,
                source_block_refs=self._refs(exact),
                confidence=max(item.evidence.confidence for item in exact),
                conflict_values=conflicts,
                validation_state="validated",
                governance_status=self._governance(exact),
            )

        agreeing = next(iter(groups.values()))
        best = max(agreeing, key=lambda item: item.evidence.confidence).evidence
        return best.model_copy(
            update={
                "requirement_id": requirement.requirement_id,
                "source_block_refs": self._refs(agreeing),
                "confidence": max(item.evidence.confidence for item in agreeing),
                "validation_state": "validated",
                "validation_errors": [],
                "governance_status": self._governance(agreeing),
            }
        )

    @staticmethod
    def _condition_match(expected: dict[str, Any], actual: dict[str, Any]) -> str:
        missing = False
        for key, expected_value in expected.items():
            if key not in actual:
                missing = True
                continue
            if _normalized(actual[key]) != _normalized(expected_value):
                return "mismatch"
        if any(key not in expected and value is not None for key, value in actual.items()):
            return "incomplete"
        return "incomplete" if missing else "exact"

    @staticmethod
    def _value_key(evidence: RequirementEvidence) -> str:
        normalized_unit, _ = normalize_unit(evidence.unit)

        def normalized_value(value: float | None) -> float | None:
            if value is None:
                return None
            converted = convert(value, evidence.unit)
            return round(converted if converted is not None else value, 12)

        return json.dumps(
            {
                "value": normalized_value(evidence.value),
                "lower": normalized_value(evidence.lower),
                "upper": normalized_value(evidence.upper),
                "unit": normalized_unit or evidence.unit,
            },
            sort_keys=True,
        )

    @staticmethod
    def _refs(items: list[PaperEvidence]) -> list[str]:
        return list(
            dict.fromkeys(
                ref for item in items for ref in item.evidence.source_block_refs
            )
        )

    @staticmethod
    def _governance(items: list[PaperEvidence]) -> str:
        statuses = {item.evidence.governance_status for item in items}
        return next(iter(statuses)) if len(statuses) == 1 else "mixed"


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    if isinstance(value, float):
        return round(value, 12) if math.isfinite(value) else str(value)
    return value
