"""摄取失败制品必须可重试，不能被当作成功重复项跳过（P1-6）。"""

from __future__ import annotations

import json
from pathlib import Path

from ultrafast_memory.db.session import get_connection
from ultrafast_memory.ingestion.pipeline import ingest_file


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _parse_status(sha256: str) -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT parse_status FROM raw_artifact WHERE sha256=?", (sha256,)
        ).fetchone()
        return row["parse_status"] if row else "missing"


def test_failed_parse_is_retried_not_skipped(memory_root, tmp_path) -> None:
    target = tmp_path / "broken_recipe.json"
    _write(target, "{ not valid json")

    first = ingest_file(target, raw_dir=tmp_path / "raw")
    assert first["imported"] == 0
    assert first["skipped"] == 0
    assert first["errors"]

    second = ingest_file(target, raw_dir=tmp_path / "raw")
    # 失败状态必须持久化并允许重试：第二次不是 skipped=1 的假成功
    assert second["skipped"] == 0
    assert second["errors"]


def test_parse_status_becomes_failed_after_error(memory_root, tmp_path) -> None:
    target = tmp_path / "bad.json"
    _write(target, "{ not valid json")
    ingest_file(target, raw_dir=tmp_path / "raw")
    assert _parse_status(_sha256_of(target)) == "failed"


def test_successful_parse_is_skipped_on_second_run(memory_root, tmp_path) -> None:
    target = _write(
        tmp_path / "recipe.json",
        json.dumps({"task_id": "task-retry-1", "material": "SiC"}),
    )
    first = ingest_file(target, raw_dir=tmp_path / "raw")
    assert first["imported"] == 1
    second = ingest_file(target, raw_dir=tmp_path / "raw")
    assert second["skipped"] == 1
    assert second["errors"] == []
    assert _parse_status(_sha256_of(target)) in ("parsed", "parsed_with_warnings")


def _sha256_of(path: Path) -> str:
    from ultrafast_memory.core.hashing import sha256_file

    return sha256_file(path)
