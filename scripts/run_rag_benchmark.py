"""第一版人工 gold RAG benchmark runner。

确定性计算底层 retrieval 指标（Recall@K 基于 scope 匹配），
回答层指标（Context Precision/Recall、Faithfulness）建议后续接入 Ragas。

用法（需要已建索引）：
    PYTHONPATH=src python -m scripts.run_rag_benchmark
    PYTHONPATH=src python -m scripts.run_rag_benchmark --top-k 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = REPO_ROOT / "benchmarks" / "rag_gold_benchmark.jsonl"


def load_benchmark(path: Path = BENCHMARK_PATH) -> list[dict[str, Any]]:
    items = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def scope_hit_score(hit: dict[str, Any], expected: dict[str, Any]) -> float:
    """基于 canonical scope 的命中计分：材料/工艺/权威等级逐项累加。"""
    from ultrafast_shared.ontology import resolve

    metadata = hit.get("metadata") or {}
    score = 0.0
    material = expected.get("expected_material_id")
    if material:
        actual = resolve("material", metadata.get("material") or hit.get("material"))
        score += 1.0 if actual == material else 0.0
    process = expected.get("expected_process_type")
    if process:
        actual = resolve(
            "process_type", metadata.get("process_type") or hit.get("process_type")
        )
        score += 0.5 if actual == process else 0.0
    return score


def run_benchmark(top_k: int = 8, index_name: str = "literature_default") -> dict[str, Any]:
    from ultrafast_knowledge.rag.query_service import query_rag

    items = load_benchmark()
    results = []
    total_scope_recall = 0.0
    for item in items:
        request = {
            "query": item["query"],
            "filters": item.get("filters") or {},
            "top_k": top_k,
            "purpose": "parameter_recommendation",
            "index_name": index_name,
        }
        pack = query_rag(request)
        hits = pack.get("hits") or []
        if item.get("expect_no_result"):
            matched = 0.0
            scope_recall = 0.0
        else:
            scores = sorted(
                (scope_hit_score(hit, item) for hit in hits), reverse=True
            )[:top_k]
            matched = sum(1 for score in scores if score > 0)
            expected_keys = 1 if item.get("expected_material_id") else 0
            scope_recall = (
                (matched / expected_keys) / 1.0 if expected_keys else 0.0
            )
        total_scope_recall += scope_recall
        results.append(
            {
                "query": item["query"],
                "expected_material_id": item.get("expected_material_id"),
                "retrieved": len(hits),
                "scope_matched_hits": matched,
                "scope_recall": round(scope_recall, 3),
                "evidence_status": pack.get("evidence_status"),
            }
        )
    n = len(items) or 1
    return {
        "benchmark_path": str(BENCHMARK_PATH),
        "n_questions": len(items),
        "top_k": top_k,
        "mean_scope_recall": round(total_scope_recall / n, 3),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAG gold benchmark runner")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--index-name", default="literature_default")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    report = run_benchmark(top_k=args.top_k, index_name=args.index_name)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"questions={report['n_questions']} top_k={report['top_k']} "
              f"mean_scope_recall={report['mean_scope_recall']}")
        for row in report["results"]:
            print(f"  {row['scope_recall']:.2f}  hits={row['retrieved']:2d}  "
                  f"matched={row['scope_matched_hits']:2d}  {row['query'][:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
