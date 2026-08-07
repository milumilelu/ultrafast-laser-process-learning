"""Gold RAG benchmark 数据文件 schema 校验。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

def _repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while not (current / "pyproject.toml").exists() and current.parent != current:
        current = current.parent
    return current


REPO_ROOT = _repo_root()
BENCHMARK_PATH = REPO_ROOT / "benchmarks" / "rag_gold_benchmark.jsonl"
RUNNER_PATH = REPO_ROOT / "scripts" / "run_rag_benchmark.py"

REQUIRED_FIELDS = {
    "query",
    "filters",
    "gold_paper_id",
    "gold_chunk_ids",
    "expected_material_id",
    "expected_process_type",
    "expected_authority",
}


def _load_runner_module():
    """按文件路径加载 runner，避免根目录 scripts/ 命名空间冲突。"""
    spec = importlib.util.spec_from_file_location("rag_gold_benchmark_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_benchmark() -> list[dict]:
    items = []
    with BENCHMARK_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def test_benchmark_file_exists_and_is_valid_jsonl() -> None:
    assert BENCHMARK_PATH.exists()
    items = _load_benchmark()
    assert len(items) >= 10, "至少 10 条代表性问题"
    for item in items:
        assert set(REQUIRED_FIELDS).issubset(item), sorted(REQUIRED_FIELDS - set(item))
        assert isinstance(item["filters"], dict)
        assert isinstance(item["gold_chunk_ids"], list)
        assert item["query"].strip()


def test_benchmark_covers_cfrp_synonyms() -> None:
    items = _load_benchmark()
    queries = " | ".join(item["query"] for item in items)
    assert "CFRP" in queries or "carbon fiber" in queries or "碳纤维" in queries
    assert any(
        item["expected_material_id"] == "CFRP" for item in items
    ), "benchmark 必须覆盖 CFRP 语义归一"


def test_benchmark_contains_no_answer_case() -> None:
    items = _load_benchmark()
    assert any(item.get("expect_no_result") for item in items)


def test_runner_module_loads_without_namespace_conflict() -> None:
    runner = _load_runner_module()
    assert runner.BENCHMARK_PATH == BENCHMARK_PATH
    items = runner.load_benchmark()
    assert len(items) >= 10


def test_gold_benchmark_recall_when_corpus_present() -> None:
    """语料存在时，Gold Benchmark 必须真实执行并达到召回门槛。

    本地（含已审核语料）强制断言 mean_scope_recall > 0；
    无语料的 CI 环境自动跳过（不伪造通过）。
    """
    import sqlite3

    from ultrafast_memory.core.config import get_project_root

    db = sqlite3.connect(get_project_root() / "data" / "ultrafast_memory.db")
    try:
        indexed = db.execute(
            "SELECT COUNT(*) FROM rag_index_entry WHERE status='indexed'"
        ).fetchone()[0]
    finally:
        db.close()
    if indexed < 100:
        pytest.skip("本地语料未索引，无法执行召回基准")

    runner = _load_runner_module()
    report = runner.run_benchmark(top_k=8)
    assert report["n_questions"] >= 10
    # 已审核语料存在时，参数用途检索必须能召回 scope 命中
    assert report["mean_scope_recall"] > 0.0, (
        f"Gold benchmark 召回为 0：{report['results']}"
    )

