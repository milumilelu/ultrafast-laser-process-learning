from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ultrafast_app.api.routers import ROUTERS


def _allowed_origins() -> list[str]:
    """默认只允许本机来源（前端 dev server 与 Topic2 托管端口）。

    恶意网页（任意 Origin）无法通过 CORS 读取本机服务数据；
    可用 ULTRAFAST_ALLOWED_ORIGINS 环境变量覆盖（逗号分隔）。
    """
    configured = os.getenv("ULTRAFAST_ALLOWED_ORIGINS", "").strip()
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8010",
        "http://localhost:8010",
    ]


def build_background_worker():
    """Composition Root：注册已知 job handler 并返回可运行的 worker。"""
    from ultrafast_agent.documents import build_paddleocr_job_handler
    from ultrafast_agent.jobs import JobWorker
    from ultrafast_integrations.ocr import PaddleOcrProvider
    from ultrafast_integrations.storage.job_repository import SQLiteJobRepository

    worker = JobWorker(SQLiteJobRepository())
    worker.register(
        "paddleocr_document",
        build_paddleocr_job_handler(PaddleOcrProvider()),
    )
    return worker


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from ultrafast_agent.jobs import BackgroundWorkerRunner
    from ultrafast_memory.core.llm_config import restore_api_key_from_store

    # 启动时恢复 DPAPI 加密保存的 API Key 到进程环境变量（无需重启后重新配置）
    restore_api_key_from_store()
    runner = BackgroundWorkerRunner(build_background_worker())
    runner.start()
    try:
        yield
    finally:
        runner.stop()


def create_app() -> FastAPI:
    application = FastAPI(
        title="Ultrafast Laser Agent",
        version="0.2.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in ROUTERS:
        application.include_router(router)
    return application


app = create_app()
