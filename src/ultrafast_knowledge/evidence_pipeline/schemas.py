"""Contracts for requirement-specific scientific evidence processing."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SemanticBlockType(StrEnum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    TABLE_CAPTION = "table_caption"
    FIGURE_CAPTION = "figure_caption"
    EQUATION = "equation"
    EQUATION_CONTEXT = "equation_context"
    EXPERIMENTAL_SETUP = "experimental_setup"
    RESULT_STATEMENT = "result_statement"


class SemanticBlock(BaseModel):
    paper_id: str
    document_version_id: str
    block_id: str
    block_type: SemanticBlockType
    page: int
    pdf_page_index: int
    section_id: str | None = None
    section_path: str | None = None
    section_type: str | None = None
    section_title: str | None = None
    table_id: str | None = None
    text: str
    retrieval_text: str = ""
    bbox: tuple[float, float, float, float] | None = None
    previous_block_id: str | None = None
    next_block_id: str | None = None
    related_block_ids: list[str] = Field(default_factory=list)
    source_text_type: str = "native"


class StructuredScientificPaper(BaseModel):
    paper_id: str
    document_version_id: str
    title: str = ""
    abstract: str = ""
    retrieval_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    blocks: list[SemanticBlock] = Field(default_factory=list)
    pdf_path: str | None = None

    def block_by_id(self, block_id: str) -> SemanticBlock | None:
        return next((item for item in self.blocks if item.block_id == block_id), None)


class RequirementQuery(BaseModel):
    requirement_id: str
    query_text: str
    core_terms: list[str]
    condition_terms: list[str]
    unit_terms: list[str]


class PaperCandidate(BaseModel):
    paper_id: str
    document_version_id: str
    score: float
    matched_terms: list[str] = Field(default_factory=list)
    paper_index_score: float = 0.0
    global_block_score: float = 0.0
    retrieval_routes: list[str] = Field(default_factory=list)


class HybridIndexHit(BaseModel):
    item_id: str
    paper_id: str
    document_version_id: str
    score: float
    bm25_score: float = 0.0
    dense_score: float = 0.0
    rerank_score: float = 0.0
    rank_routes: list[str] = Field(default_factory=list)
    block_id: str | None = None


class EvidenceWindow(BaseModel):
    window_id: str
    requirement_id: str
    paper_id: str
    center_block_id: str
    blocks: list[SemanticBlock]
    score: float
    paper_title: str = ""
    paper_metadata: dict[str, Any] = Field(default_factory=dict)
    matched_terms: list[str] = Field(default_factory=list)

    @property
    def source_block_refs(self) -> list[str]:
        return [item.block_id for item in self.blocks]

    def render(self) -> str:
        metadata = ", ".join(
            f"{key}={value}" for key, value in sorted(self.paper_metadata.items())
        )
        context = (
            f"PAPER_CONTEXT title={self.paper_title}; metadata={metadata or 'unknown'}"
        )
        blocks = "\n".join(
            f"[{item.block_id} | page {item.page} | {item.block_type.value} | "
            f"section={item.section_type or 'unknown'}] {item.text}"
            for item in self.blocks
        )
        return f"{context}\n{blocks}"


class ExtractionStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INSUFFICIENT = "INSUFFICIENT"


class RequirementEvidence(BaseModel):
    requirement_id: str
    quantity: str
    status: ExtractionStatus
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    semantic_role: str | None = None
    source_block_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    conflict_values: list[dict[str, Any]] = Field(default_factory=list)
    evidence_quote: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    validation_state: str = "pending"
    governance_status: str = "unreviewed"
    prompt_version: str = "requirement-extraction-v2"

    @property
    def valid(self) -> bool:
        return self.validation_state == "validated" and not self.validation_errors


# The extraction IR is requirement-scoped.  It is not an approved E2P prior;
# governance and applicability checks remain downstream responsibilities.
EvidenceIR = RequirementEvidence


class PaperEvidence(BaseModel):
    """One requirement evaluated against exactly one paper version."""

    paper_id: str
    document_version_id: str
    evidence: RequirementEvidence
    route: str = "literature_extraction"
    knowledge_id: str | None = None


class RequirementEvidenceRun(BaseModel):
    run_id: str
    requirement_set_id: str
    results: list[RequirementEvidence] = Field(default_factory=list)
    paper_evidence: dict[str, list[PaperEvidence]] = Field(default_factory=dict)
    paper_candidates: dict[str, list[PaperCandidate]] = Field(default_factory=dict)
    evidence_windows: dict[str, list[EvidenceWindow]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    governance_warnings: list[str] = Field(default_factory=list)
    fallback_requirements: list[dict[str, Any]] = Field(default_factory=list)
    version: str = "requirement-evidence-run-v2"
