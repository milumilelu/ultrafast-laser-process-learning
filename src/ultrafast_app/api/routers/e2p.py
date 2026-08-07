"""RAG → Topic2 Evidence[] 转换接口：Web "检索证据" 按钮的后端支撑。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/e2p", tags=["e2p"])


class EvidenceCandidatesRequest(BaseModel):
    task_scope: dict[str, Any]
    query: str | None = None
    top_k: int = Field(default=8, ge=1, le=20)
    include_unreviewed_candidates: bool = False
    # 流程验证期约定：True 时 RAG 候选全部标记 approved（审核放行）。
    # 生产/真实治理流程必须保持 False（candidate 需人工/流程审核后进入 E2P）。
    auto_approve: bool = False


@router.post("/evidence-candidates")
def evidence_candidates(request: EvidenceCandidatesRequest) -> dict:
    """按任务 scope 检索 RAG 并把已审核文献数值观测编译为 Topic2 Evidence[]。"""
    from ultrafast_knowledge.rag.evidence_converter import rag_evidence_to_topic2

    try:
        return rag_evidence_to_topic2(
            request.task_scope,
            query=request.query,
            top_k=request.top_k,
            include_unreviewed_candidates=request.include_unreviewed_candidates,
            auto_approve=request.auto_approve,
        )
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "invalid_request", "message": str(exc)}) from exc
