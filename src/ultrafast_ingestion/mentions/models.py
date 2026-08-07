"""ConditionMention model (Layer 2: extraction without linking).

F1 (v0.2): mention values support SCALAR / RANGE / LIST.
F3: context classification drives acceptance_status.
No condition_id / grouping fields here - linking is out of scope.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from ultrafast_ingestion.models.provenance import ProvenanceAnchor


class AcceptanceStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED_CONTEXT = "REJECTED_CONTEXT"
    AMBIGUOUS_CONTEXT = "AMBIGUOUS_CONTEXT"


class ContextClass(StrEnum):
    PROCESS_CONTEXT = "PROCESS_CONTEXT"
    CAPABILITY_SPEC = "CAPABILITY_SPEC"
    EMISSION_WAVELENGTH = "EMISSION_WAVELENGTH"
    EQUIPMENT_MODEL = "EQUIPMENT_MODEL"
    MEASUREMENT_OPTICS = "MEASUREMENT_OPTICS"
    UNCLEAR = "UNCLEAR"


class MentionValueType(StrEnum):
    SCALAR = "SCALAR"
    RANGE = "RANGE"
    LIST = "LIST"


@dataclass(frozen=True, slots=True)
class ConditionMention:
    mention_id: str
    parameter: str  # canonical parameter id or "length" / "unknown"
    raw_text: str
    values: list[float]
    value_type: MentionValueType
    normalized_unit: str
    context_class: ContextClass
    acceptance_status: AcceptanceStatus
    rejection_reason: str = ""
    anchor: ProvenanceAnchor | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["value_type"] = str(self.value_type)
        data["context_class"] = str(self.context_class)
        data["acceptance_status"] = str(self.acceptance_status)
        data["anchor"] = self.anchor.to_dict() if self.anchor else None
        return data
