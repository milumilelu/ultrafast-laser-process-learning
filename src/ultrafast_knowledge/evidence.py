"""Knowledge 边界出口：EvidencePack。

边界约定：
    Knowledge → EvidencePack（找到了什么经过治理的证据）
    ── boundary ──
    E2P → EvidenceClaim / PriorSpec（证据如何影响概率模型）

RAG 与 E2P 通过此 DTO 交互；E2P 不得 import ultrafast_knowledge.rag。
"""

from ultrafast_knowledge.rag.evidence_pack import build_evidence_pack
from ultrafast_knowledge.rag.schemas import EvidenceHit, EvidencePack

__all__ = ["EvidenceHit", "EvidencePack", "build_evidence_pack"]
