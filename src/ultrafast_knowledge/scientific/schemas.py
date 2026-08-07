"""ScientificKnowledgePack / ScientificKnowledgeCandidate（文档 §11-16）。

LLM Scientific Analyst 的唯一输出接口；所有 candidate 均为
knowledge_candidate 状态（无权升级为 validated knowledge），
必须经过 DeterministicValidator + 审核后才能进入 E2P。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class CandidateType(StrEnum):
    PARAMETER_VALUE = "parameter_value"
    PARAMETER_RANGE = "parameter_range"
    PARAMETER_EFFECT = "parameter_effect"
    RELATIVE_IMPORTANCE = "relative_importance"
    INTERACTION = "interaction"
    FUNCTIONAL_SHAPE = "functional_shape"
    MATERIAL_PROPERTY = "material_property"
    OPTICAL_PROPERTY = "optical_property"
    THRESHOLD = "threshold"
    FORMULA = "formula"
    MECHANISM = "mechanism"
    REPORTED_OPTIMUM = "reported_optimum"
    EXPERIMENTAL_CONDITION = "experimental_condition"
    HISTORICAL_PATTERN = "historical_pattern"
    HISTORICAL_MODEL = "historical_model"


class SemanticRole(StrEnum):
    """数字语义（文档问题 2：数值必须脱离"实验条件/范围/最优值/对照值"歧义）。"""

    EXPERIMENTAL_CONDITION = "experimental_condition"
    SCANNED_RANGE = "scanned_range"
    REPORTED_OPTIMUM = "reported_optimum"
    OBSERVED_RELATION = "observed_relation"
    REPORTED_RESULT = "reported_result"
    CONTROL_VALUE = "control_value"
    PROPERTY_CONSTANT = "property_constant"
    ASSUMPTION = "assumption"


class SourceRef(BaseModel):
    paper_id: str | None = None
    page: int | None = None
    chunk_ids: list[str] = Field(default_factory=list)
    knowledge_id: str | None = None


class ScientificKnowledgeCandidate(BaseModel):
    """一条结构化科学知识候选（宽松：各类型共用一个 schema，按 type 解释字段）。"""

    candidate_id: str
    type: CandidateType
    name: str | None = None
    parameter: str | None = None
    target: str | None = None
    relation: str | None = None
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str | None = None
    expression: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    property: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    semantic_role: SemanticRole = SemanticRole.OBSERVED_RELATION
    supporting_sources: list[SourceRef] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)
    llm_extraction: bool = True
    confidence: float | None = None

    def source_ids(self) -> list[str]:
        return [
            ref.paper_id for ref in self.supporting_sources if ref.paper_id is not None
        ]


class KnowledgeSummary(BaseModel):
    """已知事实摘要（前端可展示）。"""

    claim: str
    sources: list[SourceRef] = Field(default_factory=list)


class KnowledgeGap(BaseModel):
    """知识缺口（Unknown）。"""

    topic: str
    description: str
    related_conditions: dict[str, Any] = Field(default_factory=dict)


class KnowledgeConflict(BaseModel):
    """文献冲突（Conflicting）。"""

    topic: str
    positions: list[dict[str, Any]] = Field(default_factory=list)
    description: str = ""


class ScientificKnowledgePack(BaseModel):
    """LLM Scientific Analyst 输出（文档 §11.1）。"""

    knowledge_pack_id: str
    source_corpus_pack_id: str
    task_scope: dict[str, Any]
    candidates: list[ScientificKnowledgeCandidate] = Field(default_factory=list)
    known: list[KnowledgeSummary] = Field(default_factory=list)
    unknown: list[KnowledgeGap] = Field(default_factory=list)
    conflicts: list[KnowledgeConflict] = Field(default_factory=list)
    llm_model: str = "unknown"
    prompt_version: str = "scientific-analyst-p1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ValidationIssue(BaseModel):
    candidate_id: str
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"


class ValidationResult(BaseModel):
    """Deterministic Validator 输出（文档 §18）。"""

    validated_candidates: list[str] = Field(default_factory=list)
    rejected_candidates: list[str] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)

    def ok(self) -> bool:
        return not self.rejected_candidates
