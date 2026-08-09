"""Public API for dependency-graph requirement compilation."""

from ultrafast_requirements.compiler import RequirementCompiler
from ultrafast_requirements.graph import ScientificDependencyGraph, default_dependency_graph
from ultrafast_requirements.schemas import (
    CalibrationRequirement,
    DataRequirement,
    DependencySpec,
    KnowledgeRequirement,
    ModelCapability,
    Requirement,
    RequirementCategory,
    RequirementSet,
    RequirementSource,
    RequirementStatus,
    ResourceRequirement,
)

__all__ = [
    "CalibrationRequirement",
    "DataRequirement",
    "DependencySpec",
    "KnowledgeRequirement",
    "ModelCapability",
    "Requirement",
    "RequirementCategory",
    "RequirementCompiler",
    "RequirementSet",
    "RequirementSource",
    "RequirementStatus",
    "ResourceRequirement",
    "ScientificDependencyGraph",
    "default_dependency_graph",
]
