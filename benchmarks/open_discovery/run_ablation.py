"""O9 blind benchmark runner (contract §14).

Ablations:
  A Deterministic only          (extract_mentions + tables -> ledger)
  B LLM discovery only          (recorded/live backend discovery -> ledger)
  C Deterministic + Discovery   (hybrid merge)
  D Hybrid + Glean + Verify     (full pipeline)

Usage (requires gold JSONL + paper archive):
  python benchmarks/open_discovery/run_ablation.py --gold gold.jsonl --papers list.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from benchmarks.open_discovery.metrics import GoldCandidate, compute_metrics


def load_gold(path: Path) -> list[GoldCandidate]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows.append(
            GoldCandidate(
                paper_id=row["paper_id"],
                candidate_kind=row["candidate_kind"],
                concept_label=row["concept_label"],
                verbatim_quote=row["verbatim_quote"],
                block_id=row.get("block_id", ""),
                char_start=row.get("char_start"),
                char_end=row.get("char_end"),
            )
        )
    return rows


def load_candidates(path: Path) -> list:
    """Load a ledger artifact JSON (candidate-ledger-v0.1) as candidate list."""
    from ultrafast_ingestion.candidates.models import ScientificCandidate

    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ScientificCandidate.model_validate(c) for c in payload["candidates"]]


def run(paper_ids: list[str], gold: list[GoldCandidate], artifact_dir: Path) -> dict:
    """Compute A/C/D metrics from pre-built ledger artifacts.

    Artifact layout: artifact_dir/<paper_id>/<ledger_version_id>.json
      - *_det.json        deterministic-only ledger
      - *_hybrid.json     hybrid ledger (deterministic + discovered)
      - unsupported.json  hybrid candidates with grounding FAIL / CONTRADICTED
    """
    reports = []
    for paper_id in paper_ids:
        det_ledgers = sorted(artifact_dir.glob(f"{paper_id}/*det*.json"))
        hyb_ledgers = sorted(artifact_dir.glob(f"{paper_id}/*hybrid*.json"))
        if not det_ledgers or not hyb_ledgers:
            continue
        det_candidates = load_candidates(det_ledgers[-1])
        hybrid_candidates = load_candidates(hyb_ledgers[-1])
        unsupported_path = artifact_dir / paper_id / "unsupported.json"
        unsupported = (
            load_candidates(unsupported_path)
            if unsupported_path.exists()
            else []
        )
        paper_gold = [g for g in gold if g.paper_id == paper_id]
        reports.append(
            compute_metrics(paper_gold, det_candidates, hybrid_candidates, unsupported)
        )
    return _aggregate(reports)


def _aggregate(reports: list[dict]) -> dict:
    total_gold = sum(r["gold_candidates"] for r in reports)
    total_det = sum(r["deterministic_candidate_count"] for r in reports)
    total_hyb = sum(r["hybrid_candidate_count"] for r in reports)
    total_unsupported = sum(r["unsupported_count"] for r in reports)
    total_proposed = sum(r["proposed_count"] for r in reports)
    det_found = sum(round(r["deterministic_recall"] * r["gold_candidates"]) for r in reports)
    hyb_found = sum(round(r["hybrid_recall"] * r["gold_candidates"]) for r in reports)
    inc_found = sum(round(r["incremental_open_recall"] * r["gold_candidates"]) for r in reports)
    return {
        "papers": len(reports),
        "gold_candidates": total_gold,
        "deterministic_recall": det_found / total_gold if total_gold else 0.0,
        "hybrid_recall": hyb_found / total_gold if total_gold else 0.0,
        "incremental_open_recall": inc_found / total_gold if total_gold else 0.0,
        "unsupported_candidate_rate": total_unsupported / total_proposed if total_proposed else 0.0,
        "unsupported_count": total_unsupported,
        "proposed_count": total_proposed,
        "deterministic_candidate_count": total_det,
        "hybrid_candidate_count": total_hyb,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True, type=Path, help="gold JSONL")
    parser.add_argument("--papers", required=True, type=Path, help="paper id list (one per line)")
    parser.add_argument("--artifacts", required=True, type=Path, help="ledger artifact dir")
    args = parser.parse_args()
    gold = load_gold(args.gold)
    papers = [p.strip() for p in args.papers.read_text(encoding="utf-8").splitlines() if p.strip()]
    report = run(papers, gold, args.artifacts)
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
