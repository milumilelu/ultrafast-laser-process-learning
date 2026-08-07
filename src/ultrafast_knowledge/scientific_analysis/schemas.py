"""Source-level 科学分析 schema（文档：Source-level Map → Structured Reduce → Selective Critic）。

Pass 1 的输出是固定结构的 SourceScientificAnalysis（Extraction + Local
Interpretation 合并）；Pass 2 只读这些结构化结果，不再读原文。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from ultrafast_knowledge.scientific.schemas import CandidateType, SemanticRole, SourceRef


class SourceAnalysisStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    FROM_CACHE = "from_cache"


class LocalKnowledgeItem(BaseModel):
    """单 Source 内的一个知识项（与候选 schema 对齐，便于确定性验证）。"""

    item_id: str
    type: CandidateType
    parameter: str | None = None
    target: str | None = None
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str | None = None
    relation: str | None = None
    property: str | None = None
    name: str | None = None
    expression: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)
    semantic_role: SemanticRole = SemanticRole.OBSERVED_RELATION
    # 作者给出的解释（mechanism 语义，供全局综合）
    explanation: str | None = None
    # 源内定位
    page: int | None = None
    chunk_ids: list[str] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)


class SourceKnowledgeGap(BaseModel):
    type: str = "missing_information"
    field: str | None = None
    description: str = ""
    search_hints: list[str] = Field(default_factory=list)


class SourceInternalConflict(BaseModel):
    topic: str
    positions: list[str] = Field(default_factory=list)
    description: str = ""


class SourceScientificAnalysis(BaseModel):
    """Pass 1 输出：一篇 Source 的局部科学分析（Extraction + Local Interpretation）。"""

    source_id: str
    paper_id: str | None = None
    title: str | None = None
    status: SourceAnalysisStatus = SourceAnalysisStatus.COMPLETED
    error: str | None = None

    experimental_conditions: list[LocalKnowledgeItem] = Field(default_factory=list)
    parameter_values: list[LocalKnowledgeItem] = Field(default_factory=list)
    parameter_ranges: list[LocalKnowledgeItem] = Field(default_factory=list)
    parameter_effects: list[LocalKnowledgeItem] = Field(default_factory=list)
    material_properties: list[LocalKnowledgeItem] = Field(default_factory=list)
    thresholds: list[LocalKnowledgeItem] = Field(default_factory=list)
    formulas: list[LocalKnowledgeItem] = Field(default_factory=list)
    mechanisms: list[LocalKnowledgeItem] = Field(default_factory=list)
    interactions: list[LocalKnowledgeItem] = Field(default_factory=list)
    reported_optima: list[LocalKnowledgeItem] = Field(default_factory=list)

    knowledge_gaps: list[SourceKnowledgeGap] = Field(default_factory=list)
    internal_conflicts: list[SourceInternalConflict] = Field(default_factory=list)

    source_refs: list[SourceRef] = Field(default_factory=list)
    llm_model: str = "unknown"
    prompt_version: str = "source-map-v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def all_items(self) -> list[LocalKnowledgeItem]:
        fields = (
            self.experimental_conditions,
            self.parameter_values,
            self.parameter_ranges,
            self.parameter_effects,
            self.material_properties,
            self.thresholds,
            self.formulas,
            self.mechanisms,
            self.interactions,
            self.reported_optima,
        )
        return [item for group in fields for item in group]

    def item_count(self) -> int:
        return len(self.all_items())


# Critic 分级（文档第七节）：哪些类型必须被 Selective Critic 审核
CRITIC_REQUIRED_TYPES: frozenset[CandidateType] = frozenset(
    {
        CandidateType.MATERIAL_PROPERTY,
        CandidateType.THRESHOLD,
        CandidateType.FORMULA,
        CandidateType.REPORTED_OPTIMUM,
    }
)
CRITIC_RECOMMENDED_TYPES: frozenset[CandidateType] = frozenset(
    {CandidateType.PARAMETER_EFFECT, CandidateType.PARAMETER_VALUE}
)
CRITIC_SKIPPED_TYPES: frozenset[CandidateType] = frozenset(
    {CandidateType.MECHANISM, CandidateType.EXPERIMENTAL_CONDITION}
)


def critic_priority(item_type: CandidateType) -> Literal["required", "recommended", "skipped"]:
    if item_type in CRITIC_REQUIRED_TYPES:
        return "required"
    if item_type in CRITIC_RECOMMENDED_TYPES:
        return "recommended"
    return "skipped"
