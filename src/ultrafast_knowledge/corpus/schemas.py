"""EvidenceCorpusPack：RAG 与 LLM Scientific Analyst 之间的唯一正式接口。

RAG 的正式职责是"找对语料并组织为任务导向的语料包"，不直接产出科学
结论（文档 §3.1 / §6）。禁止把散乱 chunk[] 直接传给 E2P。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RetrievalIntent(StrEnum):
    """检索意图（文档 §5.2）：不同 intent 采用不同 query expansion 与 rerank 规则。"""

    PARAMETER_EFFECT = "parameter_effect"
    PARAMETER_CONDITION = "parameter_condition"
    MATERIAL_PROPERTY = "material_property"
    OPTICAL_PROPERTY = "optical_property"
    THRESHOLD = "threshold"
    FORMULA = "formula"
    MECHANISM = "mechanism"
    INTERACTION = "interaction"
    REPORTED_OPTIMUM = "reported_optimum"
    HISTORICAL_ANALOG = "historical_analog"


SECTION_TYPES = Literal[
    "abstract",
    "introduction",
    "methods",
    "experimental_setup",
    "results",
    "discussion",
    "conclusion",
    "table",
    "figure_caption",
    "equation",
    "other",
]

SOURCE_TYPES = Literal[
    "literature",
    "historical_experiment",
    "validated_rule",
    "structured_knowledge",
]


class CorpusSection(BaseModel):
    """语料中的一段（与论文 section 对齐，可追溯 chunk_ids）。"""

    section_type: SECTION_TYPES = "other"
    page: int | None = None
    chunk_ids: list[str] = Field(default_factory=list)
    text: str = ""
    retrieval_score: float | None = None


class CorpusSource(BaseModel):
    """一个来源（论文 / 历史实验 / 规则 / 结构化知识）。"""

    source_id: str
    source_type: SOURCE_TYPES = "literature"
    title: str | None = None
    paper_id: str | None = None
    experiment_id: str | None = None
    knowledge_id: str | None = None
    material_id: str | None = None
    process_type: str | None = None
    sections: list[CorpusSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalTrace(BaseModel):
    """检索过程追溯。"""

    retrieval_run_id: str
    intents: list[RetrievalIntent] = Field(default_factory=list)
    query_by_intent: dict[str, str] = Field(default_factory=dict)
    raw_hit_count: int = 0
    filtered_hit_count: int = 0
    source_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class EvidenceCorpusPack(BaseModel):
    """RAG 输出（文档 §6.2）。"""

    corpus_pack_id: str
    task_context_id: str
    task_context_version: int = 1
    task_scope: dict[str, Any]
    retrieval_intents: list[RetrievalIntent] = Field(default_factory=list)
    sources: list[CorpusSource] = Field(default_factory=list)
    retrieval_trace: RetrievalTrace
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "evidence-corpus-pack-v1"

    def source_count(self) -> int:
        return len(self.sources)

    def section_count(self) -> int:
        return sum(len(source.sections) for source in self.sources)

    def chunk_count(self) -> int:
        return sum(
            len(section.chunk_ids) for source in self.sources for section in source.sections
        )
