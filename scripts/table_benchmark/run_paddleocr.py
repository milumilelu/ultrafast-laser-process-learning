"""PaddleOCR PP-StructureV3 table extraction adapter (local inference).

Input page is rendered to PNG with PyMuPDF at a fixed DPI (PAGE_RENDER_DPI).
The complete PaddleOCR JSON is preserved in <case_id>_raw.json.
"""

from __future__ import annotations

import argparse
import os
import time

# Models are already cached under ~/.paddlex; skip PaddleX's connectivity
# check to model hosters, which hangs behind a local HTTP proxy on this
# machine and would otherwise block pipeline construction.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
from html.parser import HTMLParser
from pathlib import Path

from common import (
    BENCH_DIR,
    CASES_FILE,
    PAGE_RENDER_DPI,
    dump_pip_freeze,
    env_info,
    load_cases,
    package_version,
    resolve_pdf,
    write_json,
    write_raw,
    write_result,
)

TOOL = "paddleocr"

PADDLE_PAGES_DIR = BENCH_DIR / "tmp" / "paddle_pages"


class _TableHTMLParser(HTMLParser):
    """Parse PaddleOCR pred_html into a grid, expanding rowspan/colspan."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict]] = []
        self._cur_row: list[dict] | None = None
        self._cur_cell: dict | None = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._cur_row = []
        elif tag in ("td", "th"):
            a = dict(attrs)
            self._in_cell = True
            try:
                rowspan = int(a.get("rowspan", "1") or 1)
            except ValueError:
                rowspan = 1
            try:
                colspan = int(a.get("colspan", "1") or 1)
            except ValueError:
                colspan = 1
            self._cur_cell = {"text": "", "rowspan": max(1, rowspan), "colspan": max(1, colspan)}

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._cur_cell is not None:
            if self._cur_row is not None:
                self._cur_row.append(self._cur_cell)
            self._cur_cell = None
            self._in_cell = False
        elif tag == "tr" and self._cur_row is not None:
            self.rows.append(self._cur_row)
            self._cur_row = None

    def handle_data(self, data):
        if self._in_cell and self._cur_cell is not None:
            self._cur_cell["text"] += data


def html_to_rows(html: str) -> list[list[str]]:
    parser = _TableHTMLParser()
    parser.feed(html or "")
    parser.close()

    # occupancy[r][c] == True means a spanning cell already covers it
    occupancy: list[dict[int, bool]] = []
    grid: list[list[str]] = []
    for r, row in enumerate(parser.rows):
        occ = dict(occupancy[r]) if r < len(occupancy) else {}
        out: list[str] = []
        c = 0
        for cell in row:
            while occ.get(c, False):
                out.append("")
                c += 1
            text = " ".join(cell["text"].split())
            for dc in range(cell["colspan"]):
                out.append(text if dc == 0 else "")
            for dr in range(cell["rowspan"]):
                if r + dr >= len(occupancy):
                    occupancy.extend([{} for _ in range(r + dr - len(occupancy) + 1)])
                for dc in range(cell["colspan"]):
                    occupancy[r + dr][c + dc] = True
            c += cell["colspan"]
        grid.append(out)

    # pad rows to equal width
    width = max((len(row) for row in grid), default=0)
    for row in grid:
        row.extend([""] * (width - len(row)))
    return grid


def render_page(pdf_path: Path, page: int, dpi: int = PAGE_RENDER_DPI, name: str = "") -> Path:
    import pymupdf

    PADDLE_PAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = name or pdf_path.stem[:40]
    out = PADDLE_PAGES_DIR / f"{stem}_p{page}_dpi{dpi}.png"
    if not out.exists():
        doc = pymupdf.open(pdf_path)
        try:
            pix = doc[page - 1].get_pixmap(dpi=dpi)
            pix.save(out)
        finally:
            doc.close()
    return out


def tables_from_raw(raw: list) -> list[dict]:
    """Extract unified table dicts from PaddleOCR PP-StructureV3 raw JSON.

    PP-StructureV3 result objects expose .json as a list of page dicts, each
    with a nested "res" key holding "table_res_list".
    """
    table_res = []
    for page_obj in raw or []:
        res = page_obj.get("res", page_obj) if isinstance(page_obj, dict) else page_obj
        if isinstance(res, dict):
            trl = res.get("table_res_list", [])
        else:
            trl = []
        table_res.extend(trl or [])
    tables = []
    for index, tr in enumerate(table_res):
        html = tr.get("pred_html", "") if isinstance(tr, dict) else ""
        rows = html_to_rows(html)
        boxes = tr.get("cell_box_list") or [] if isinstance(tr, dict) else []
        bbox = None
        if boxes:
            xs = [b[0] for b in boxes] + [b[2] for b in boxes]
            ys = [b[1] for b in boxes] + [b[3] for b in boxes]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
        tables.append({"table_index": index, "bbox": bbox, "rows": rows})
    return tables


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(CASES_FILE))
    parser.add_argument("--only", default=None)
    parser.add_argument("--dpi", type=int, default=PAGE_RENDER_DPI)
    parser.add_argument("--reparse-from-raw", action="store_true",
                        help="rebuild unified result JSONs from saved *_raw.json "
                             "(no inference; keeps metadata from existing results)")
    args = parser.parse_args()

    from paddleocr import PPStructureV3

    only_set = {x.strip() for x in args.only.split(",")} if args.only else None
    cases = [c for c in load_cases() if only_set is None or c["case_id"] in only_set]
    results_dir = write_result(TOOL, "placeholder", {}).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    if args.reparse_from_raw:
        from common import read_result
        import json as _json
        n = 0
        for case in cases:
            cid = case["case_id"]
            raw_path = results_dir / f"{cid}_raw.json"
            res_path = results_dir / f"{cid}.json"
            if not raw_path.exists():
                print(f"{cid}: no raw file, skipped")
                continue
            raw = _json.loads(raw_path.read_text(encoding="utf-8"))
            tables = tables_from_raw(raw)
            old_res = read_result(TOOL, cid) or {}
            result_obj = dict(old_res)
            result_obj["tables"] = tables
            result_obj.pop("error", None)
            write_json(res_path, result_obj)
            print(f"{cid}: tables={len(tables)} (reparsed from raw)")
            n += 1
        print(f"reparsed {n} cases")
        return

    pipeline_kwargs = {
        "lang": "en",
        "device": "cpu",
        "enable_mkldnn": True,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_region_detection": False,
        "use_formula_recognition": False,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
        "text_det_limit_side_len": 1600,
        "cpu_threads": 4,
    }
    pipeline = PPStructureV3(**pipeline_kwargs)

    meta = {
        "python_version": env_info()["python_version"],
        "os": env_info()["os"],
        "platform": env_info()["platform"],
        "package_version": package_version("paddleocr"),
        "paddlepaddle_version": package_version("paddlepaddle"),
        "device": "cpu",
        "dpi": args.dpi,
        "pipeline_kwargs": pipeline_kwargs,
    }
    write_json(results_dir / "env.json", meta)
    dump_pip_freeze(results_dir / "pip_freeze.txt")

    for idx, case in enumerate(cases):
        pdf = resolve_pdf(case["pdf"])
        start = time.perf_counter()
        error = None
        tables = []
        raw_pages = []
        try:
            png = render_page(pdf, case["page"], dpi=args.dpi, name=case["case_id"])
            results = pipeline.predict(str(png))
            raw = []
            for res in results:
                data = getattr(res, "json", None)
                if data is None:
                    data = res
                if isinstance(data, dict):
                    raw.append(data)
                elif isinstance(data, list):
                    raw.extend(data)
                else:
                    raw.append({"note": "unexpected result type", "value": repr(data)})
            raw_pages = raw
            tables = tables_from_raw(raw)
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
            "dpi": args.dpi,
            "pipeline_kwargs": pipeline_kwargs,
            "tables": tables,
        }
        write_result(TOOL, case["case_id"], result_obj)
        write_raw(TOOL, case["case_id"], raw_pages)
        print(
            f"{case['case_id']}: tables={len(tables)} "
            f"error={error} elapsed={elapsed:.2f}s"
        )


if __name__ == "__main__":
    main()
