"""Evaluate table-extraction results against gold annotations.

Metrics (per benchmark spec):
  - Table Recall             detected / total expected
  - Shape Accuracy           exact row/col counts on cell-evaluable cases
  - Cell Accuracy            normalized cell exact match (aligned)
  - Numeric Accuracy         numeric-token match on gold numeric cells
  - Header-Value Accuracy    value still under the same column/row header
  - Runtime                  cold start + mean warm page time
  - Failure Count            cases with error or missing result

Outputs: results/summary.json, results/summary.csv, results/diagnostics.json,
         results/review/<case_id>/* (page png + gold + per-tool json)
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import (
    BENCH_DIR,
    RESULTS_DIR,
    REVIEW_DIR,
    load_gold_cases,
    normalize_text,
    read_result,
    rows_to_normalized,
    TOOL_DIRS,
)

TOOLS = ["pymupdf", "docling", "paddleocr", "camelot"]


def find_number_tokens(cell: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", normalize_text(cell))


def align_rows(gold_rows: list[list[str]], pred_rows: list[list[str]]) -> list[tuple[int, int]]:
    """Return (gold_row_idx, pred_row_idx) pairs via sequence matching.

    Equal/replace blocks are paired 1:1 in order; unmatched gold rows are omitted.
    """
    g = [tuple(r) for r in gold_rows]
    p = [tuple(r) for r in pred_rows]
    sm = difflib.SequenceMatcher(None, g, p, autojunk=False)
    pairs: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            pairs.extend((i1 + k, j1 + k) for k in range(i2 - i1))
        elif tag == "replace":
            n = min(i2 - i1, j2 - j1)
            pairs.extend((i1 + k, j1 + k) for k in range(n))
    return pairs


def score_table(g_norm: list[list[str]], p_norm: list[list[str]]) -> dict:
    """Score one predicted table against gold rows."""
    out = {
        "matched_cells": 0,
        "shape_accuracy": 0.0,
        "cell_accuracy": None,
        "numeric_accuracy": None,
        "header_value_accuracy": None,
        "n_gold_cells": 0,
        "n_numeric_cells": 0,
        "n_value_cells": 0,
    }
    if not g_norm:
        return out

    out["shape_accuracy"] = 1.0 if (len(g_norm) == len(p_norm) and all(
        len(a) == len(b) for a, b in zip(g_norm, p_norm))) else 0.0

    pairs = align_rows(g_norm, p_norm)
    pair_by_g = dict(pairs)

    n_gold_cells = 0
    n_cell_match = 0
    n_numeric = 0
    n_numeric_match = 0
    n_value = 0
    n_value_ok = 0

    for i, grow in enumerate(g_norm):
        p_row = None
        if i in pair_by_g:
            pi = pair_by_g[i]
            if pi < len(p_norm):
                p_row = p_norm[pi]
        for j, gcell in enumerate(grow):
            n_gold_cells += 1
            pcell = ""
            if p_row is not None and j < len(p_row):
                pcell = p_row[j]

            if gcell and gcell == pcell:
                n_cell_match += 1

            g_tokens = find_number_tokens(gcell)
            if g_tokens:
                n_numeric += 1
                if find_number_tokens(pcell) == g_tokens:
                    n_numeric_match += 1

            if i > 0 and j > 0 and gcell:
                n_value += 1
                g_col_header = g_norm[0][j] if j < len(g_norm[0]) else ""
                g_row_header = grow[0] if grow else ""
                p_col_header = ""
                p_row_header = ""
                if p_norm:
                    p_col_header = p_norm[0][j] if j < len(p_norm[0]) else ""
                if p_row is not None and p_row:
                    p_row_header = p_row[0]
                if g_col_header == p_col_header and g_row_header == p_row_header:
                    n_value_ok += 1

    out["matched_cells"] = n_cell_match
    out["n_gold_cells"] = n_gold_cells
    out["n_numeric_cells"] = n_numeric
    out["n_value_cells"] = n_value
    out["cell_accuracy"] = n_cell_match / n_gold_cells if n_gold_cells else None
    out["numeric_accuracy"] = n_numeric_match / n_numeric if n_numeric else None
    out["header_value_accuracy"] = n_value_ok / n_value if n_value else None
    return out


def cell_metrics(gold: dict, pred: dict) -> dict:
    """Compute shape/cell/numeric/header-value metrics for one case.

    Detection is content-based: a gold table counts as detected when at least
    one predicted table actually contains a matching non-empty gold cell.
    For detection-only cases (no gold rows) we fall back to "any table found".
    """
    g_rows = gold.get("rows") or []
    p_tables = pred.get("tables") or []
    out = {
        "detected_raw": len(p_tables) > 0,
        "detected": len(p_tables) > 0,
        "shape_accuracy": None,
        "cell_accuracy": None,
        "numeric_accuracy": None,
        "header_value_accuracy": None,
        "n_gold_cells": 0,
        "n_numeric_cells": 0,
        "n_value_cells": 0,
    }
    if not gold.get("evaluate_cells", True) or not g_rows:
        return out

    g_norm = rows_to_normalized(g_rows)
    best = None
    for pt in p_tables:
        p_norm = rows_to_normalized(pt.get("rows") or [])
        s = score_table(g_norm, p_norm)
        if best is None or s["matched_cells"] > best["matched_cells"]:
            best = s
    best = best or score_table(g_norm, [])

    out["detected"] = best["matched_cells"] > 0
    out["shape_accuracy"] = best["shape_accuracy"]
    out["cell_accuracy"] = best["cell_accuracy"]
    out["numeric_accuracy"] = best["numeric_accuracy"]
    out["header_value_accuracy"] = best["header_value_accuracy"]
    out["n_gold_cells"] = best["n_gold_cells"]
    out["n_numeric_cells"] = best["n_numeric_cells"]
    out["n_value_cells"] = best["n_value_cells"]
    return out


def mean(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def tool_aggregate(tool: str, gold_cases: list[dict]) -> dict:
    detected = []
    shapes = []
    cells = []
    numerics = []
    headers = []
    failures = 0
    runtimes = []
    cold_start = None
    per_case = {}

    for case in gold_cases:
        cid = case["case_id"]
        pred = read_result(tool, cid)
        if pred is None or pred.get("error"):
            failures += 1
            per_case[cid] = {"detected": False, "error": pred.get("error") if pred else "missing result"}
            continue
        metrics = cell_metrics(case, pred)
        per_case[cid] = metrics
        detected.append(1 if metrics["detected"] else 0)
        if metrics["shape_accuracy"] is not None:
            shapes.append(metrics["shape_accuracy"])
            cells.append(metrics["cell_accuracy"])
            numerics.append(metrics["numeric_accuracy"])
            headers.append(metrics["header_value_accuracy"])
        elapsed = pred.get("elapsed_time_s")
        if elapsed is not None:
            runtimes.append(elapsed)
        if pred.get("is_cold") and cold_start is None:
            cold_start = elapsed

    if cold_start is None and runtimes:
        cold_start = runtimes[0]

    # warm page time: exclude the cold run (first case); if the first case failed
    # and has no runtime, use all but the earliest.
    warm = runtimes[1:] if runtimes and (cold_start == runtimes[0]) else (runtimes[1:] if len(runtimes) > 1 else [])

    return {
        "table_recall": sum(detected) / len(detected) if detected else None,
        "shape_accuracy": mean(shapes),
        "cell_accuracy": mean(cells),
        "numeric_accuracy": mean(numerics),
        "header_value_accuracy": mean(headers),
        "cold_start_time_s": round(cold_start, 2) if cold_start is not None else None,
        "mean_warm_page_time_s": round(mean(warm), 2) if warm else None,
        "failure_count": failures,
        "per_case": per_case,
    }


def category_breakdown(gold_cases: list[dict]) -> dict:
    cats: dict[str, list[dict]] = {}
    for case in gold_cases:
        cat = (case.get("category") or "?")[:1]
        cats.setdefault(cat, []).append(case)
    out = {}
    for cat, cases in cats.items():
        out[cat] = {"count": len(cases)}
        for tool in TOOLS:
            out[cat][tool] = tool_aggregate(tool, cases)
    return out


def render_review_page(gold_cases: list[dict]) -> None:
    import pymupdf

    for case in gold_cases:
        cid = case["case_id"]
        out_dir = REVIEW_DIR / cid
        out_dir.mkdir(parents=True, exist_ok=True)
        png = out_dir / "source_page.png"
        if not png.exists():
            pdf_path = BENCH_DIR.parents[1] / "data" / "literature_archive" / case["pdf"]
            if pdf_path.exists():
                doc = pymupdf.open(pdf_path)
                try:
                    doc[case["page"] - 1].get_pixmap(dpi=150).save(png)
                finally:
                    doc.close()
        (out_dir / "gold.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        for tool in TOOLS:
            pred = read_result(tool, cid)
            if pred is not None:
                (out_dir / f"{tool}.json").write_text(
                    json.dumps(pred, ensure_ascii=False, indent=1), encoding="utf-8"
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold-dir", default=str(BENCH_DIR / "gold"))
    parser.add_argument("--skip-review", action="store_true")
    args = parser.parse_args()

    gold_cases = load_gold_cases()
    per_tool = {tool: tool_aggregate(tool, gold_cases) for tool in TOOLS}

    diagnostics = []
    for case in gold_cases:
        diag = {
            "case_id": case["case_id"],
            "table_type": case.get("table_type"),
            "category": case.get("category"),
            "evaluate_cells": case.get("evaluate_cells", True),
            "results": {},
        }
        for tool in TOOLS:
            agg = per_tool[tool]["per_case"].get(case["case_id"], {})
            diag["results"][tool] = {
                "detected": bool(agg.get("detected")),
                "numeric_accuracy": agg.get("numeric_accuracy"),
                "header_value_accuracy": agg.get("header_value_accuracy"),
                "error": agg.get("error"),
            }
        diagnostics.append(diag)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold_case_count": len(gold_cases),
        "tools": TOOLS,
        "per_tool": per_tool,
        "per_category": category_breakdown(gold_cases),
        "diagnostics": diagnostics,
    }
    summary_path = RESULTS_DIR / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    (RESULTS_DIR / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    with open(RESULTS_DIR / "summary.csv", "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["Tool", "Table Recall", "Shape Accuracy", "Cell Accuracy",
             "Numeric Accuracy", "Header-Value Accuracy",
             "Cold Start (s)", "Mean Page Time (s)", "Failure Count"]
        )
        for tool in TOOLS:
            a = per_tool[tool]
            writer.writerow(
                [tool,
                 f"{a['table_recall']:.3f}" if a["table_recall"] is not None else "",
                 f"{a['shape_accuracy']:.3f}" if a["shape_accuracy"] is not None else "",
                 f"{a['cell_accuracy']:.3f}" if a["cell_accuracy"] is not None else "",
                 f"{a['numeric_accuracy']:.3f}" if a["numeric_accuracy"] is not None else "",
                 f"{a['header_value_accuracy']:.3f}" if a["header_value_accuracy"] is not None else "",
                 a["cold_start_time_s"] if a["cold_start_time_s"] is not None else "",
                 a["mean_warm_page_time_s"] if a["mean_warm_page_time_s"] is not None else "",
                 a["failure_count"]]
            )

    if not args.skip_review:
        render_review_page(gold_cases)

    print("summary written to", summary_path)
    print()
    header = f"{'Tool':12s} {'Recall':>7s} {'Shape':>7s} {'Cell':>7s} {'Num':>7s} {'Hdr':>7s} {'Cold':>7s} {'Warm':>7s} {'Fail':>5s}"
    print(header)
    for tool in TOOLS:
        a = per_tool[tool]
        def fmt(v, spec=".3f"):
            return f"{v:{spec}}" if v is not None else "-"
        print(
            f"{tool:12s} "
            f"{fmt(a['table_recall']):>7s} "
            f"{fmt(a['shape_accuracy']):>7s} "
            f"{fmt(a['cell_accuracy']):>7s} "
            f"{fmt(a['numeric_accuracy']):>7s} "
            f"{fmt(a['header_value_accuracy']):>7s} "
            f"{fmt(a['cold_start_time_s'], '.1f'):>7s} "
            f"{fmt(a['mean_warm_page_time_s'], '.1f'):>7s} "
            f"{a['failure_count']:5d}"
        )


if __name__ == "__main__":
    main()



