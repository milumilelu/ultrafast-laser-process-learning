"""LLM Metadata Extraction Benchmark Runner（不写生产数据库）。

流程：
  1. 读取 gold（paper_id + title）
  2. **全部 gold 进入运行**；从 work/texts/ 读取文本，缺失论文生成明确失败记录
     （parse_missing 计入端到端指标，不静默排除）
  3. 对每篇运行 Extractor V2（真实 LLM；--dry-run 时 rule-only abstain）
  4. 输出 runs/<timestamp>/predictions.jsonl + manifest.json

Manifest 可复现性约定：
  - git commit + worktree dirty 状态 + diff hash
  - 抽取相关源码文件字节 SHA
  - 完整请求 SHA（system prompt + 正文构造模板源码）
  - 实际生效参数（temperature 沿调用链传入 client.chat）
  - 每篇输入文本 SHA + selected paper IDs（固定 seed 互斥分层）
  - token usage（含重试累计）

用法：
  python scripts/run_llm_benchmark.py --gold gold/annotations.jsonl --strata 5 --seed 42
  python scripts/run_llm_benchmark.py --gold gold/annotations.jsonl            # 全量 203
  python scripts/run_llm_benchmark.py --gold gold/annotations.jsonl --dry-run --limit 3

评测：python scripts/evaluate_extraction.py --gold <gold> --pred <runs/xxx/predictions.jsonl>
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import io
import json
import random
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BENCH_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = BENCH_ROOT.parents[1]
DEFAULT_GOLD = BENCH_ROOT / "gold" / "annotations.jsonl"
DEFAULT_TEXTS = BENCH_ROOT / "work" / "texts"
RUNS_DIR = BENCH_ROOT / "runs"
DEFAULT_SEED = 42

# 互斥分层：按优先级首个命中（review > non_laser > 材料类互斥集）
STRATA_SPEC: tuple[tuple[str, Callable[[dict[str, Any]], bool]], ...] = (
    ("review", lambda r: bool(r.get("is_review"))),
    ("non_laser", lambda r: not r.get("primary_material")),
    ("glass", lambda r: "Glass" in (r.get("primary_material") or [])),
    ("ni_tbc", lambda r: bool(set(r.get("primary_material") or []) & {"NickelSuperalloy", "TBC", "ZrO2"})),
    ("diamond", lambda r: "Diamond" in (r.get("primary_material") or [])),
    ("cfrp_metal", lambda r: bool(set(r.get("primary_material") or []) & {"CFRP", "Epoxy", "Aluminum", "Steel", "Ti6Al4V"})),
    ("other_laser", lambda r: bool(r.get("primary_material"))),
)


def assign_stratum(record: dict[str, Any]) -> str:
    for name, predicate in STRATA_SPEC:
        if predicate(record):
            return name
    return "unassigned"


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
        return result.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — 无 git 环境时降级
        return "unknown"


def git_worktree_state() -> tuple[bool, str]:
    """返回 (dirty, diff_sha256)；非 git 环境 (True, 'unknown')。"""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10, check=False
        ).stdout
        dirty = bool(status.strip())
        diff = subprocess.run(
            ["git", "diff"], capture_output=True, text=True, timeout=10, check=False
        ).stdout
        return dirty, hashlib.sha256(diff.encode("utf-8")).hexdigest()
    except Exception:  # noqa: BLE001
        return True, "unknown"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """字节级 SHA256（与 git/Get-FileHash 一致，不受换行规范化影响）。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files_sha() -> dict[str, str]:
    extraction_dir = AGENT_ROOT / "src" / "ultrafast_knowledge" / "literature" / "extraction"
    files = [
        "extractor.py", "semantic_roles.py", "schemas.py", "registry.py",
        "candidates.py", "validator.py", "__init__.py",
    ]
    hashes: dict[str, str] = {}
    for name in files:
        path = extraction_dir / name
        if path.exists():
            hashes[name] = sha256_file(path)
    return hashes


def find_text_file(paper_id: str, texts_dir: Path) -> Path | None:
    stem = paper_id[:-4] if paper_id.lower().endswith(".pdf") else paper_id
    exact = texts_dir / f"{stem}.txt"
    if exact.exists():
        return exact
    for candidate in texts_dir.iterdir():
        if candidate.name.startswith(stem[:30]):
            return candidate
    return None


def parse_pages(text: str) -> list[str]:
    parts = text.split("[PAGE ")
    pages: list[str] = []
    for part in parts[1:]:
        marker, _, body = part.partition("] ")
        if body:
            pages.append(f"[PAGE {marker}] {body}")
    return pages or ([text] if text.strip() else [])


def build_sections_from_pages(pages: list[str], paper_id: str) -> list[Any]:
    from ultrafast_knowledge.literature.schemas import LiteratureSectionData

    sections = []
    for index, page in enumerate(pages, start=1):
        text = page.split("] ", 1)[1] if "] " in page else page
        sections.append(
            LiteratureSectionData(
                section_id=f"{paper_id}-page-{index}",
                paper_id=paper_id,
                artifact_id=None,
                section_type="page",
                section_title="",
                page_start=index,
                page_end=index,
                text=text,
                text_hash=f"h-{paper_id}-{index}",
                parser_version="benchmark-runner",
            )
        )
    return sections


def failure_row(paper_id: str, title: str, error: str) -> dict[str, Any]:
    """统一 PredictionEnvelope：失败行保持 evaluator schema 兼容（全 abstain + failed 元数据）。"""
    return {
        "paper_id": paper_id,
        "title": title,
        "is_review": None,
        "primary_material": [],
        "material_grade": {},
        "primary_process": "",
        "laser_type": "",
        "wavelength_nm": None,
        "pulse_width": None,
        "geometry": "",
        "material_mentions": [],
        "process_mentions": [],
        "evidence_page_primary_material": None,
        "notes": f"prediction failed: {error}",
        "failed": True,
        "error": error,
        "extraction_status": "failed",
    }


def to_prediction_row(paper_id: str, title: str, metadata: Any) -> dict[str, Any]:
    data = metadata.as_dict()
    return {
        "paper_id": paper_id,
        "title": title,
        "is_review": None,
        "primary_material": data["primary_material"],
        "material_grade": data["primary_material_grade"],
        "primary_process": data["primary_process"],
        "laser_type": data["laser_type"],
        "wavelength_nm": (data["wavelength_nm"] or {}).get("value"),
        "pulse_width": data["pulse_width"],
        "geometry": data["geometry"],
        "material_mentions": data["material_mentions"],
        "process_mentions": data["process_mentions"],
        "evidence_page_primary_material": None,
        "notes": "; ".join(data["warnings"]) if data["warnings"] else "",
        "extraction_status": data["extraction_status"],
        "extractor_version": data["extractor_version"],
        "llm_usage": data.get("llm_usage") or {},
    }


def sample_strata(gold: list[dict[str, Any]], per_stratum: int, seed: int) -> list[dict[str, Any]]:
    """互斥分层 + 固定 seed 确定性抽样。"""
    rng = random.Random(seed)
    strata: dict[str, list[dict[str, Any]]] = {}
    for record in gold:
        strata.setdefault(assign_stratum(record), []).append(record)
    picked: list[dict[str, Any]] = []
    for members in strata.values():
        chosen = rng.sample(members, min(per_stratum, len(members)))
        picked.extend(chosen)
    return picked


def run(
    gold_path: Path,
    texts_dir: Path,
    *,
    limit: int,
    strata: int,
    papers: list[str],
    dry_run: bool,
    temperature: float,
    seed: int,
    out_dir: Path,
) -> dict[str, Any]:
    gold = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    gold_sha = sha256_file(gold_path)

    if papers:
        selected = [r for r in gold if r["paper_id"] in papers]
    elif strata:
        selected = sample_strata(gold, strata, seed)
    else:
        selected = list(gold)  # P0 修复：全部 gold 进入选择，缺文本在运行期记录
    if limit:
        selected = selected[:limit]
    selected_ids = [r["paper_id"] for r in selected]

    from ultrafast_knowledge.literature.extraction.extractor import (
        build_extraction_llm_client,
        extract_paper_metadata,
    )

    client = None if dry_run else build_extraction_llm_client()
    if client is None and not dry_run:
        raise SystemExit(
            "LLM 未配置或 Key 不可用：真实基准需要 LLM（Agent 侧边栏 → 配置 → 保存 API Key 并测试连接）。\n"
            "先用 --dry-run 验证链路（rule-only abstain），配置 Key 后再跑真实基准。"
        )

    from ultrafast_knowledge.literature.extraction.semantic_roles import ROLE_PROMPT, _build_input

    # 完整请求 SHA：system prompt + 正文构造模板源码（覆盖候选生成与请求组装）
    request_spec_sha = sha256_text(ROLE_PROMPT + "\n" + inspect.getsource(_build_input))
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = out_dir / "predictions.jsonl"
    manifest_path = out_dir / "manifest.json"

    predictions: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    parse_missing: list[str] = []
    input_hashes: dict[str, str] = {}

    for index, record in enumerate(selected, start=1):
        paper_id = record["paper_id"]
        title = record.get("title") or ""
        text_file = find_text_file(paper_id, texts_dir)
        print(f"[{index}/{len(selected)}] {paper_id[:70]}")
        if text_file is None:
            parse_missing.append(paper_id)
            row = failure_row(paper_id, title, "text file missing (parse failure counted in e2e metrics)")
            predictions.append(row)
            failed.append({"paper_id": paper_id, "error": "text file missing"})
            print("    -> PARSE MISSING (counted in end-to-end metrics)")
            continue
        text = text_file.read_text(encoding="utf-8")
        input_hashes[paper_id] = sha256_text(text)
        pages = parse_pages(text)
        try:
            metadata = extract_paper_metadata(
                paper_id,
                build_sections_from_pages(pages, paper_id),
                page_count=len(pages),
                llm_client=client,
                paper_title=title,
                temperature=temperature,
            )
            predictions.append(to_prediction_row(paper_id, title, metadata))
            status = metadata.extraction_status
            print(f"    -> {status} | materials={metadata.primary_material} laser={metadata.laser_type}")
        except Exception as exc:  # noqa: BLE001 — 单篇失败记录进 manifest，不中断
            error_text = f"{type(exc).__name__}: {exc}"
            failed.append({"paper_id": paper_id, "error": error_text})
            predictions.append(failure_row(paper_id, title, error_text))
            print(f"    -> FAILED {error_text}")

    with predictions_path.open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    usage_agg = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for row in predictions:
        usage = row.get("llm_usage") or {}
        for key in usage_agg:
            usage_agg[key] += int(usage.get(key) or 0)

    dirty, diff_sha = git_worktree_state()
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold_path": str(gold_path),
        "gold_sha256": gold_sha,
        "gold_papers": len(gold),
        "git_commit": git_commit(),
        "worktree_dirty": dirty,
        "worktree_diff_sha256": diff_sha,
        "dry_run": dry_run,
        "mode": {"limit": limit, "strata": strata, "papers": papers, "seed": seed},
        "extractor_version": None,
        "prompt_sha256": sha256_text(ROLE_PROMPT),
        "request_spec_sha256": request_spec_sha,
        "source_files_sha256": source_files_sha(),
        "temperature": temperature,
        "provider": None,
        "model": None,
        "n_selected": len(selected),
        "n_predicted": sum(1 for p in predictions if not p.get("failed")),
        "n_failed": len(failed),
        "parse_missing": parse_missing,
        "n_parse_missing": len(parse_missing),
        "selected_paper_ids": selected_ids,
        "input_text_sha256": input_hashes,
        "token_usage": usage_agg,
        "predictions_path": str(predictions_path),
    }
    if client is not None:
        manifest["provider"] = getattr(client, "provider", None)
        manifest["model"] = getattr(client, "model", None)
    from ultrafast_knowledge.literature.extraction import EXTRACTION_VERSION

    manifest["extractor_version"] = EXTRACTION_VERSION
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM metadata extraction benchmark runner (no production DB)")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--texts-dir", type=Path, default=DEFAULT_TEXTS)
    parser.add_argument("--limit", type=int, default=0, help="仅前 N 篇")
    parser.add_argument("--strata", type=int, default=0, help="互斥分层：每层 N 篇（review/非激光/玻璃/镍基TBC/金刚石/CFRP金属/其他）")
    parser.add_argument("--papers", nargs="*", default=[], help="显式 paper_id 列表")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="分层抽样随机种子")
    parser.add_argument("--dry-run", action="store_true", help="不调 LLM（rule-only abstain），验证链路")
    parser.add_argument("--temperature", type=float, default=0.2, help="实际传入 client.chat 的 temperature")
    parser.add_argument("--out-dir", type=Path, default=None, help="默认 runs/<utc>")
    args = parser.parse_args()

    out_dir = args.out_dir or (RUNS_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    manifest = run(
        args.gold,
        args.texts_dir,
        limit=args.limit,
        strata=args.strata,
        papers=args.papers,
        dry_run=args.dry_run,
        temperature=args.temperature,
        seed=args.seed,
        out_dir=out_dir,
    )
    print("\n" + json.dumps(
        {k: v for k, v in manifest.items() if k not in ("input_text_sha256", "parse_missing", "selected_paper_ids")},
        ensure_ascii=False, indent=2,
    ))
    print(f"\n评测：python scripts/evaluate_extraction.py --gold <gold> --pred {manifest['predictions_path']}")


if __name__ == "__main__":
    main()
