"""Scientific dependency and requirement contracts.

Requirements are compiled from declared model dependencies.  They are not
inferred from exceptions raised while attempting to execute a downstream
model.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RequirementSource(StrEnum):
    TASK = "task"
    EQUIPMENT = "equipment"
    LITERATURE = "literature"
    CALIBRATION = "calibration"
    EXPERIMENT = "experiment"
    DATASET = "dataset"
    PRIOR = "prior"
    DERIVED = "derived"


class RequirementStatus(StrEnum):
    SATISFIED = "satisfied"
    DERIVABLE = "derivable"
    MISSING = "missing"


class RequirementCategory(StrEnum):
    RESOURCE_REQUIREMENT = "RESOURCE_REQUIREMENT"
    KNOWLEDGE_REQUIREMENT = "KNOWLEDGE_REQUIREMENT"
    CALIBRATION_REQUIREMENT = "CALIBRATION_REQUIREMENT"
    DATA_REQUIREMENT = "DATA_REQUIREMENT"
    DERIVABLE = "DERIVABLE"
    SATISFIED = "SATISFIED"


class DependencySpec(BaseModel):
    """One declared input of a scientific capability."""

    quantity: str
    role: str
    acceptable_sources: list[RequirementSource] = Field(default_factory=list)
    expected_unit: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    resolution_policy: str = "require_observed_or_governed_value"
    query_terms: list[str] = Field(default_factory=list)


class ModelCapability(BaseModel):
    """A non-executable declaration of what a model predicts and consumes."""

    capability_id: str
    predicts: list[str]
    inputs: list[DependencySpec] = Field(default_factory=list)
    model_family: str = "scientific_model"
    description: str = ""
    assumptions: list[str] = Field(default_factory=list)
    version: str = "v1"


class Requirement(BaseModel):
    requirement_id: str
    quantity: str
    role: str
    required_by: list[str] = Field(default_factory=list)
    acceptable_sources: list[RequirementSource] = Field(default_factory=list)
    expected_unit: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    resolution_policy: str
    status: RequirementStatus
    category: RequirementCategory
    derivation_capability_id: str | None = None
    query_terms: list[str] = Field(default_factory=list)
    supplied_value: Any | None = None


class ResourceRequirement(Requirement):
    category: Literal[RequirementCategory.RESOURCE_REQUIREMENT] = (
        RequirementCategory.RESOURCE_REQUIREMENT
    )


class KnowledgeRequirement(Requirement):
    category: Literal[RequirementCategory.KNOWLEDGE_REQUIREMENT] = (
        RequirementCategory.KNOWLEDGE_REQUIREMENT
    )


class CalibrationRequirement(Requirement):
    category: Literal[RequirementCategory.CALIBRATION_REQUIREMENT] = (
        RequirementCategory.CALIBRATION_REQUIREMENT
    )


class DataRequirement(Requirement):
    category: Literal[RequirementCategory.DATA_REQUIREMENT] = (
        RequirementCategory.DATA_REQUIREMENT
    )


class RequirementSet(BaseModel):
    requirement_set_id: str
    task_spec: dict[str, Any]
    root_quantities: list[str]
    selected_capabilities: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    graph_version: str = "scientific-dependency-graph-v1"
    compiler_version: str = "requirement-compiler-v1"

    def by_category(self, category: RequirementCategory) -> list[Requirement]:
        return [item for item in self.requirements if item.category == category]

    @property
    def resource_requirements(self) -> list[Requirement]:
        return self.by_category(RequirementCategory.RESOURCE_REQUIREMENT)

    @property
    def knowledge_requirements(self) -> list[Requirement]:
        return self.by_category(RequirementCategory.KNOWLEDGE_REQUIREMENT)

    @property
    def calibration_requirements(self) -> list[Requirement]:
        return self.by_category(RequirementCategory.CALIBRATION_REQUIREMENT)

    @property
    def data_requirements(self) -> list[Requirement]:
        return self.by_category(RequirementCategory.DATA_REQUIREMENT)

    @property
    def derivable(self) -> list[Requirement]:
        return self.by_category(RequirementCategory.DERIVABLE)

    @property
    def satisfied(self) -> list[Requirement]:
        return self.by_category(RequirementCategory.SATISFIED)

    @property
    def unresolved(self) -> list[Requirement]:
        return [item for item in self.requirements if item.status == RequirementStatus.MISSING]
