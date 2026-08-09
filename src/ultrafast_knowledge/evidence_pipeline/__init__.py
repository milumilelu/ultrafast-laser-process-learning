"""Requirement-specific scientific evidence API."""

from ultrafast_knowledge.evidence_pipeline.aggregation import CrossPaperEvidenceAggregator
from ultrafast_knowledge.evidence_pipeline.benchmark import (
    EvidenceBenchmarkMetrics,
    RetrievalGold,
    evaluate_evidence_run,
)
from ultrafast_knowledge.evidence_pipeline.blocks import SemanticBlockBuilder
from ultrafast_knowledge.evidence_pipeline.extraction import (
    RequirementEvidenceExtractor,
    RequirementEvidenceValidator,
)
from ultrafast_knowledge.evidence_pipeline.hybrid_index import (
    HybridScientificIndex,
    ScientificIndexNotReady,
)
from ultrafast_knowledge.evidence_pipeline.indexing import ScientificIndexIngestionService
from ultrafast_knowledge.evidence_pipeline.repository import (
    PersistentScientificPaperRepository,
)
from ultrafast_knowledge.evidence_pipeline.retrieval import TwoLevelEvidenceRetriever
from ultrafast_knowledge.evidence_pipeline.schemas import (
    EvidenceIR,
    EvidenceWindow,
    ExtractionStatus,
    PaperEvidence,
    RequirementEvidence,
    RequirementEvidenceRun,
    SemanticBlock,
    SemanticBlockType,
    StructuredScientificPaper,
)
from ultrafast_knowledge.evidence_pipeline.service import RequirementEvidencePipeline
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore

__all__ = [
    "CrossPaperEvidenceAggregator",
    "EvidenceBenchmarkMetrics",
    "EvidenceIR",
    "EvidenceWindow",
    "ExtractionStatus",
    "HybridScientificIndex",
    "PaperEvidence",
    "PersistentScientificPaperRepository",
    "RequirementEvidence",
    "RequirementEvidenceExtractor",
    "RequirementEvidencePipeline",
    "RequirementEvidenceRun",
    "RequirementEvidenceValidator",
    "RetrievalGold",
    "ScientificIndexIngestionService",
    "ScientificIndexNotReady",
    "ScientificIndexStore",
    "SemanticBlock",
    "SemanticBlockBuilder",
    "SemanticBlockType",
    "StructuredScientificPaper",
    "TwoLevelEvidenceRetriever",
    "evaluate_evidence_run",
]
