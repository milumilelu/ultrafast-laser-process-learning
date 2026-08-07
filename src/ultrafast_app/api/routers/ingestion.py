from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ultrafast_memory.core.config import get_project_root, resolve_path

router = APIRouter(tags=["ingestion"])


class ScanRequest(BaseModel):
    directory: str = "data/watch_dirs"


def _validate_scan_directory(directory: str) -> str:
    """只允许扫描项目根内的目录，避免任意路径递归扫描（本地服务安全面）。"""
    root = get_project_root()
    candidate = Path(directory).expanduser().resolve()
    if candidate.is_relative_to(root):
        return str(candidate)
    resolved_default = Path(resolve_path("data/watch_dirs", root)).resolve()
    if candidate == resolved_default:
        return str(candidate)
    raise HTTPException(
        400,
        detail={
            "code": "directory_outside_project_root",
            "message": f"scan directory must be inside project root: {root}",
        },
    )


@router.post("/ingest/scan")
def ingest_scan(request: ScanRequest) -> dict:
    from ultrafast_memory.db.init_db import init_database
    from ultrafast_memory.ingestion.pipeline import scan_directory

    init_database()
    return scan_directory(_validate_scan_directory(request.directory))


@router.get("/artifacts")
def artifacts() -> list[dict]:
    from ultrafast_integrations.storage.read_models import list_artifacts

    return list_artifacts()


@router.get("/runs")
def runs() -> list[dict]:
    from ultrafast_integrations.storage.read_models import list_runs

    return list_runs()
