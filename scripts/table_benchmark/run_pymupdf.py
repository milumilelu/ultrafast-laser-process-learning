"""PyMuPDF table extraction adapter (find_tables, text-strategy fallback).

Fixed strategy per benchmark spec:
  default find_tables()
  -> if no table detected: strategy="text"
No additional parameter tuning.
"""

from __future__ import annotations

import argparse
import json
import time

import pymupdf

from common import (
    CASES_FILE,
    PAGE_RENDER_DPI,
    dump_pip_freeze,
    env_info,
    load_cases,
    package_version,
    raw_path,
    resolve_pdf,
    result_path,
    write_json,
    write_raw,
    write_result,
)

TOOL = "pymupdf"


def extract_case(doc: pymupdf.Document, case: dict) -> list[dict]:
    page = doc[case["page"] - 1]
    finder = page.find_tables()
    used_fallback = False
    if not finder.tables:
        finder = page.find_tables(strategy="text")
        used_fallback = True

    tables = []
    for index, table in enumerate(finder.tables):
        try:
            rows = table.extract()
        except Exception:
            rows = []
        tables.append(
            {
                "table_index": index,
                "bbox": [float(v) for v in table.bbox],
                "rows": rows,
            }
        )
    return tables, used_fallback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(CASES_FILE))
    parser.add_argument("--only", default=None, help="run a single case_id")
    args = parser.parse_args()

    cases = [c for c in load_cases() if args.only is None or c["case_id"] == args.only]
    results_dir = result_path(TOOL, "placeholder").parent
    results_dir.mkdir(parents=True, exist_ok=True)

    # per-case metadata
    meta = {
        "python_version": env_info()["python_version"],
        "os": env_info()["os"],
        "platform": env_info()["platform"],
        "package_version": package_version("pymupdf"),
        "device": "cpu",
        "strategy": "default find_tables() -> strategy=text fallback",
    }
    write_json(results_dir / "env.json", meta)
    dump_pip_freeze(results_dir / "pip_freeze.txt")

    cache: dict[str, pymupdf.Document] = {}
    try:
        for idx, case in enumerate(cases):
            pdf = resolve_pdf(case["pdf"])
            if pdf.name not in cache:
                cache[pdf.name] = pymupdf.open(pdf)
            doc = cache[pdf.name]

            start = time.perf_counter()
            try:
                tables, used_fallback = extract_case(doc, case)
                error = None
            except Exception as exc:  # noqa: BLE001
                tables, used_fallback = [], False
                error = f"{type(exc).__name__}: {exc}"

            elapsed = time.perf_counter() - start
            result = {
                "case_id": case["case_id"],
                "tool": TOOL,
                "pdf": case["pdf"],
                "page": case["page"],
                "package_version": meta["package_version"],
                "python_version": meta["python_version"],
                "device": meta["device"],
                "os": meta["os"],
                "elapsed_time_s": round(elapsed, 4),
                "is_cold": idx == 0,
                "error": error,
                "strategy_used": "text" if used_fallback else "default",
                "tables": tables,
            }
            write_result(TOOL, case["case_id"], result)

            # raw: keep every table's cell-level output (bbox + text)
            raw_tables = []
            for t in tables:
                raw_tables.append(
                    {
                        "table_index": t["table_index"],
                        "bbox": t["bbox"],
                        "extract": t["rows"],
                    }
                )
            write_raw(
                TOOL,
                case["case_id"],
                {
                    "case_id": case["case_id"],
                    "tool": TOOL,
                    "raw_tables": raw_tables,
                    "note": "PyMuPDF Table.extract() output; no per-cell bbox is exposed by the public API.",
                },
            )
            print(
                f"{case['case_id']}: tables={len(tables)} "
                f"error={error} elapsed={elapsed:.2f}s"
            )
    finally:
        for doc in cache.values():
            doc.close()


if __name__ == "__main__":
    main()
