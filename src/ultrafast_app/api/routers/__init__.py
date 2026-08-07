from ultrafast_app.api.routers.bo import router as bo_router
from ultrafast_app.api.routers.chat import router as chat_router
from ultrafast_app.api.routers.e2p import router as e2p_router
from ultrafast_app.api.routers.equipment import router as equipment_router
from ultrafast_app.api.routers.health import router as health_router
from ultrafast_app.api.routers.ingestion import router as ingestion_router
from ultrafast_app.api.routers.jobs import router as jobs_router
from ultrafast_app.api.routers.knowledge import router as knowledge_router
from ultrafast_app.api.routers.literature import router as literature_router
from ultrafast_app.api.routers.process_recommendations import (
    router as process_recommendations_router,
)
from ultrafast_app.api.routers.rag import router as rag_router
from ultrafast_app.api.routers.reports import router as reports_router
from ultrafast_app.api.routers.scientific_pipeline import router as scientific_pipeline_router
from ultrafast_app.api.routers.trial import router as trial_router

ROUTERS = (
    health_router,
    ingestion_router,
    equipment_router,
    chat_router,
    literature_router,
    rag_router,
    knowledge_router,
    trial_router,
    bo_router,
    e2p_router,
    reports_router,
    jobs_router,
    process_recommendations_router,
    scientific_pipeline_router,
)

__all__ = ["ROUTERS"]

