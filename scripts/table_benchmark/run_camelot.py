"""Camelot 2.0 (flavor="ml") table extraction adapter."""

from __future__ import annotations

import argparse
import time

from common import (
    CASES_FILE,
    dump_pip_freeze,
    env_info,
    load_cases,
    package_version,
    resolve_pdf,
    write_json,
    write_raw,
    write_result,
)

TOOL = "camelot"


def get_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(CASES_FILE))
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    import camelot

    cases = [c for c in load_cases() if args.only is None or c["case_id"] == args.only]
    results_dir = write_result(TOOL, "placeholder", {}).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "python_version": env_info()["python_version"],
        "os": env_info()["os"],
        "platform": env_info()["platform"],
        "package_version": package_version("camelot-py"),
        "flavor": "ml",
        "device": get_device(),
    }
    write_json(results_dir / "env.json", meta)
    dump_pip_freeze(results_dir / "pip_freeze.txt")

    for idx, case in enumerate(cases):
        pdf = resolve_pdf(case["pdf"])
        start = time.perf_counter()
        error = None
        tables = []
        raw_tables = []
        try:
            tables_raw = camelot.read_pdf(str(pdf), pages=str(case["page"]), flavor="ml")
            for index, table in enumerate(tables_raw):
                bbox = None
                if getattr(table, "_bbox", None) is not None:
                    bbox = [float(v) for v in table._bbox]
                elif getattr(table, "bbox", None) is not None:
                    bbox = [float(v) for v in table.bbox]
                df = None
                try:
                    df = table.df.fillna("").astype(str)
                    rows = df.values.tolist()
                except Exception:
                    rows = []
                report = {}
                try:
                    report = dict(table.parsing_report or {})
                except Exception:
                    report = {}
                tables.append(
                    {"table_index": index, "bbox": bbox, "rows": rows}
                )
                raw_tables.append(
                    {
                        "table_index": index,
                        "bbox": bbox,
                        "parsing_report": report,
                        "df_csv": (df.to_csv(index=False) if df is not None else None),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

        elapsed = time.perf_counter() - start
        result_obj = {
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
            "tables": tables,
        }
        write_result(TOOL, case["case_id"], result_obj)
        write_raw(
            TOOL,
            case["case_id"],
            {
                "case_id": case["case_id"],
                "tool": TOOL,
                "raw_tables": raw_tables,
                "note": "Camelot parsing_report + dataframe CSV.",
            },
        )
        print(
            f"{case['case_id']}: tables={len(tables)} "
            f"error={error} elapsed={elapsed:.2f}s"
        )


if __name__ == "__main__":
    main()

