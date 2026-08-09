"""Requirement-specific scientific evidence API."""

from ultrafast_knowledge.evidence_pipeline.blocks import SemanticBlockBuilder
from ultrafast_knowledge.evidence_pipeline.extraction import (
    RequirementEvidenceExtractor,
    RequirementEvidenceValidator,
)
from ultrafast_knowledge.evidence_pipeline.repository import DatabaseScientificPaperRepository
from ultrafast_knowledge.evidence_pipeline.retrieval import TwoLevelEvidenceRetriever
from ultrafast_knowledge.evidence_pipeline.schemas import (
    EvidenceIR,
    EvidenceWindow,
    ExtractionStatus,
    RequirementEvidence,
    RequirementEvidenceRun,
    SemanticBlock,
    SemanticBlockType,
    StructuredScientificPaper,
)
from ultrafast_knowledge.evidence_pipeline.service import RequirementEvidencePipeline

__all__ = [
    "DatabaseScientificPaperRepository",
    "EvidenceIR",
    "EvidenceWindow",
    "ExtractionStatus",
    "RequirementEvidence",
    "RequirementEvidenceExtractor",
    "RequirementEvidencePipeline",
    "RequirementEvidenceRun",
    "RequirementEvidenceValidator",
    "SemanticBlock",
    "SemanticBlockBuilder",
    "SemanticBlockType",
    "StructuredScientificPaper",
    "TwoLevelEvidenceRetriever",
]
