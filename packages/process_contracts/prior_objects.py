"""Neutral contracts for auditable evidence-to-prior outputs.

The contracts live outside both E2P and scientific computation so that the
producer and consumers remain independently testable domain modules.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PRIOR_SCHEMA_VERSION = "e2p-prior-object-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriorRef(StrictModel):
    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class PriorUncertainty(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class PriorStatus(StrEnum):
    EXTERNAL_PRIOR = "EXTERNAL_PRIOR"
    PROVISIONAL_PRIOR = "PROVISIONAL_PRIOR"


class ConflictStatus(StrEnum):
    NONE = "NONE"
    CONFLICT = "CONFLICT"


class BasePrior(StrictModel):
    schema_version: str = PRIOR_SCHEMA_VERSION
    prior_id: str = Field(min_length=1)
    prior_type: str = Field(min_length=1)
    input_refs: list[PriorRef] = Field(default_factory=list)
    evidence_refs: list[PriorRef] = Field(min_length=1)
    applicability_refs: list[PriorRef] = Field(default_factory=list)
    provenance: list[PriorRef] = Field(min_length=1)
    uncertainty: PriorUncertainty
    status: PriorStatus
    conflict_status: ConflictStatus = ConflictStatus.NONE
    conflict_group_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)


class ParameterPrior(BasePrior):
    prior_type: Literal["ParameterPrior"] = "ParameterPrior"
    parameter: str = Field(min_length=1)
    lower: float
    upper: float
    unit: str = Field(min_length=1)
    parameter_semantics: Literal["PHYSICAL", "EFFECTIVE", "PROVISIONAL"] = "PROVISIONAL"


class MechanismModelPrior(BasePrior):
    prior_type: Literal["MechanismModelPrior"] = "MechanismModelPrior"
    model_family: str = Field(min_length=1)
    alternatives: list[str] = Field(default_factory=list)
    supporting_evidence: list[PriorRef] = Field(min_length=1)


class PlanningPreferencePrior(BasePrior):
    prior_type: Literal["PlanningPreferencePrior"] = "PlanningPreferencePrior"
    path_families: list[str] = Field(default_factory=list)
    parameter: str | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str | None = None
    preference: str = Field(min_length=1)
    hard_constraint: bool = False


PriorObject = Annotated[
    ParameterPrior | MechanismModelPrior | PlanningPreferencePrior,
    Field(discriminator="prior_type"),
]


class PriorConflict(StrictModel):
    conflict_id: str = Field(min_length=1)
    parameter: str = Field(min_length=1)
    prior_refs: list[PriorRef] = Field(min_length=2)
    reason: str = Field(min_length=1)
    resolution: Literal["PRESERVE_SEPARATELY", "HUMAN_REVIEW_REQUIRED"] = "PRESERVE_SEPARATELY"


class PriorObjectSet(StrictModel):
    schema_version: str = PRIOR_SCHEMA_VERSION
    prior_set_id: str = Field(min_length=1)
    input_refs: list[PriorRef] = Field(default_factory=list)
    priors: list[PriorObject] = Field(default_factory=list)
    conflicts: list[PriorConflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: list[PriorRef] = Field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
