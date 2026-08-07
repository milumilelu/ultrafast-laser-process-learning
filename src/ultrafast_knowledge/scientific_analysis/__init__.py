"""Scientific Analysis（Map → Reduce → Selective Critic）。

RAG 负责发现语料；本包负责科学精读与提炼（不依赖聊天 Agent，可离线批处理）。
"""

from ultrafast_knowledge.scientific_analysis.schemas import SourceScientificAnalysis
from ultrafast_knowledge.scientific_analysis.service import ScientificKnowledgeService

__all__ = ["ScientificKnowledgeService", "SourceScientificAnalysis"]

