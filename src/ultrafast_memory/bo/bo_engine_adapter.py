from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from ultrafast_bo.application.compatibility import LegacyBOCompatibilityAdapter
from ultrafast_memory.equipment.bounds import build_machine_bounds


def build_approval_verifier() -> object:
    """approval repository 验证器（P0 治理链）：approval_id 必须存在且未撤销。

    注入 BO 入口后，compile_from_approved_priors 会逐条验证 approval_id，
    不存在的审批不再被编译为先验（ignored_unverified）。
    """

    def verify(approval_id: str) -> bool:
        try:
            from ultrafast_memory.db.session import get_connection

            with get_connection() as conn:
                row = conn.execute(
                    "SELECT 1 FROM knowledge_usage_approval "
                    "WHERE approval_id=? AND (revoked_at IS NULL OR revoked_at='')",
                    (approval_id,),
                ).fetchone()
        except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError):
            # 验证失败按"未验证"降级：绝不把未知审批当成有效先验。
            return False
        return row is not None

    return verify


def call_bo_recommendation(task_spec: dict, training_csv_path: str) -> dict:
    spec = dict(task_spec)
    machine_context = spec.pop("machine_context", None)
    explicit_bounds = spec.pop("machine_bounds", None)
    if machine_context is None and explicit_bounds:
        machine_context = {
            "active": True,
            "machine_bounds": explicit_bounds,
            "revision_id": spec.pop("equipment_revision", "task-override"),
        }
    if machine_context is None:
        machine_context = build_machine_bounds()
    approved_priors = spec.pop("approved_priors", [])
    path = Path(training_csv_path)
    samples = []
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            samples = [dict(row) for row in csv.DictReader(handle)]
    result = LegacyBOCompatibilityAdapter().recommend(
        task_spec=spec,
        samples=samples,
        machine_context=machine_context,
        approved_priors=approved_priors,
        approval_verifier=build_approval_verifier(),
    )
    result["training_csv_path"] = str(path)
    return result
