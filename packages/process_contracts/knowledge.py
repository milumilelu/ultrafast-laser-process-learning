"""Task-driven knowledge workflow contracts (V0 main chain).

Objects:
- KnowledgeRequirement: what knowledge the current task needs and why.
- RequirementSatisfaction: whether existing/acquired knowledge satisfies it.
- KnowledgeState: the assembled knowledge picture feeding learning/planning.

Phase 0 semantics:
- Gap analysis is deterministic diagnostics (+ optional LLM provisional).
- Satisfaction is provisional (LLM or deterministic) - a typed deterministic
  evaluator can replace it later without changing the workflow.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

KnowledgeRequirementType = Literal[
    "experimental_condition",
    "formula",
    "material_property",
    "threshold",
    "parameter_effect",
    "parameter_range",
    "reported_optimum",
    "physics_dependency",
    "process_mechanism",
    "data_quality",
    "MATERIAL_PROPERTY",
    "PARAMETER_PRIOR",
    "MECHANISM_MODEL",
    "PHYSICS_DEPENDENCY",
    "INTERACTION_MECHANISM",
    "PARAMETER_EFFECT",
    "MODEL_VALIDATION",
    "EXTERNAL_VALIDATION_CASE",
    "PATH_STRATEGY",
    "OTHER",
]

RequirementTarget = str


class KnowledgeRequirement(BaseModel):
    """一条知识需求：当前任务值得知道什么、为什么（P0-5）。

    required_evidence_roles 声明该需求能被哪种 evidence claim_type 满足
    （requirement-specific coverage：一条 parameter_effect 证据不能
    满足 threshold 需求）。
    """

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(min_length=1)
    type: KnowledgeRequirementType
    question: str | None = Field(default=None, min_length=1)
    scientific_question: str | None = Field(default=None, min_length=1)
    required_for: RequirementTarget = "both"
    priority: Literal["high", "medium", "low"] = "medium"
    trigger_reasons: list[str] = Field(default_factory=list)
    required_evidence_roles: list[str] = Field(default_factory=list)
    satisfaction_criteria: list[str] = Field(default_factory=list)
    status: Literal["KNOWN", "PARTIAL", "UNKNOWN", "MISMATCH"] = "UNKNOWN"
    provenance: list[dict[str, Any]] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.question and not self.scientific_question:
            raise ValueError("question or scientific_question is required")
        if not self.question:
            object.__setattr__(self, "question", self.scientific_question)
        if not self.scientific_question:
            object.__setattr__(self, "scientific_question", self.question)


SatisfactionStatus = Literal[
    "SATISFIED",
    "PARTIALLY_SATISFIED",
    "SATISFIED_WITH_CONFLICT",
    "UNSATISFIED",
]


class RequirementSatisfaction(BaseModel):
    """需求满足度评估（V0 provisional，允许 LLM 判断）。"""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(min_length=1)
    status: SatisfactionStatus
    assessment_method: Literal["LLM_PROVISIONAL", "DETERMINISTIC_PROVISIONAL"]
    assessment_version: str = Field(min_length=1)
    basis_refs: list[str] = Field(default_factory=list)
    unresolved_reasons: list[str] = Field(default_factory=list)


class ExistingKnowledgeSummary(BaseModel):
    """已有知识摘要（来自已审核证据 / 应用运行历史）。"""

    model_config = ConfigDict(extra="allow")

    evidence_count: int = 0
    governed_evidence_count: int = 0
    candidate_count: int = 0
    paper_count: int = 0
    topics: list[str] = Field(default_factory=list)


class KnowledgeState(BaseModel):
    """知识状态：需求 + 满足度 + 已有知识摘要，供 Learning/Planning 使用。"""

    model_config = ConfigDict(extra="allow")

    requirements: list[KnowledgeRequirement] = Field(default_factory=list)
    satisfactions: list[RequirementSatisfaction] = Field(default_factory=list)
    existing_knowledge: ExistingKnowledgeSummary = Field(
        default_factory=ExistingKnowledgeSummary
    )
    missing_topics: list[str] = Field(default_factory=list)
    assessment_version: str = "knowledge-state-v0.1"
