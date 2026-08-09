"""V1 task-driven literature evidence and E2P prior API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ultrafast_evidence_prior.schemas import TaskRequestV1

router = APIRouter(prefix="/api/v1/evidence-prior", tags=["evidence-prior"])


@router.post("/analyze")
def analyze_evidence_prior(request: TaskRequestV1) -> dict:
    from ultrafast_app.services.scientific_pipeline import LLMNotConfiguredError
    from ultrafast_evidence_prior.service import EvidencePriorAnalysisService
    from ultrafast_knowledge.evidence_pipeline import ScientificIndexNotReady
    from ultrafast_memory.llm.openai_compatible import LLMProviderError

    try:
        result = EvidencePriorAnalysisService().analyze(request)
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "llm_not_configured", "message": str(exc)},
        ) from exc
    except ScientificIndexNotReady as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scientific_index_not_ready",
                "message": str(exc),
                "hint": "先导入真实 PDF 并构建 paper/block 索引。",
            },
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_provider_failed", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "evidence_prior_failed", "message": str(exc)},
        ) from exc
    return result.model_dump(mode="json")
