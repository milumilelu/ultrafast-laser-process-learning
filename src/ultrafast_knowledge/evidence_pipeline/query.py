"""Generate retrieval queries directly from a compiled Requirement."""

from __future__ import annotations

import re
import unicodedata

from ultrafast_knowledge.evidence_pipeline.schemas import RequirementQuery
from ultrafast_requirements.schemas import Requirement

_UNIT_SUFFIXES = {"2", "j", "m2", "m", "s", "hz", "w", "um", "fs", "khz"}


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(text))
    normalized = re.sub(r"([a-z])([A-Z])", r"\1 \2", normalized).lower()
    return re.findall(r"[a-zα-ω]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]+", normalized)


class RequirementQueryCompiler:
    """No requirement-type-to-intent table: fields on the requirement are the query."""

    def compile(self, requirement: Requirement) -> RequirementQuery:
        quantity_terms = tokenize(requirement.quantity.replace("_", " "))
        core = [item for item in quantity_terms if item not in _UNIT_SUFFIXES]
        core.extend(tokenize(requirement.role.replace("_", " ")))
        for hint in requirement.query_terms:
            core.extend(tokenize(hint))
        conditions: list[str] = []
        for value in requirement.conditions.values():
            if value is None:
                continue
            conditions.extend(tokenize(str(value)))
        units = [
            item
            for item in tokenize(requirement.expected_unit or "")
            if not item.isdigit() and item not in {"m", "s"}
        ]
        core = list(dict.fromkeys(core))
        conditions = list(dict.fromkeys(conditions))
        units = list(dict.fromkeys(units))
        phrases = [hint.strip() for hint in requirement.query_terms if hint.strip()]
        query_text = " ".join([*phrases, *core, *conditions, *units])
        return RequirementQuery(
            requirement_id=requirement.requirement_id,
            query_text=query_text,
            core_terms=core,
            condition_terms=conditions,
            unit_terms=units,
        )
