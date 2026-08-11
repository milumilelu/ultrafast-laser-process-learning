"""Docling + TableFormer (ACCURATE) table extraction adapter."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import re
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DOCLING_INFERENCE_COMPILE_TORCH_MODELS", "false")
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")


def _ensure_utf8_mode() -> None:
    # Chinese Windows default encoding is GBK; torch._inductor and other
    # libraries read UTF-8 files with open() in text mode, so force UTF-8.
    if not sys.flags.utf8_mode:
        os.execv(
            sys.executable,
            [sys.executable, "-X", "utf8", os.path.abspath(__file__), *sys.argv[1:]],
        )


_ensure_utf8_mode()


def _prefer_ascii_docling_parse() -> None:
    """Work around docling-parse failing to resolve its glyph resources when
    the interpreter path contains non-ASCII characters (Windows + Chinese
    paths).  The installed docling_parse package is exposed through an ASCII
    junction on sys.path (before any docling_parse import) so the native
    extension resolves pdf_resources from an ASCII path.
    """
    site_packages = Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages"
    if not (site_packages / "docling_parse").exists():
        return
    if not re.search(r"[^\x00-\x7f]", str(site_packages)):
        return
    digest = hashlib.sha1(str(site_packages).encode("utf-8")).hexdigest()[:12]
    junction = Path(tempfile.gettempdir()) / f"docling_parse_ascii_{digest}" / "site-packages"
    if not junction.exists():
        junction.parent.mkdir(parents=True, exist_ok=True)
        try:
            import subprocess

            subprocess.run(
                ["cmd", "/c", "chcp", "65001", ">nul", "&", "mklink", "/J", str(junction), str(site_packages)],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except Exception:  # pragma: no cover
            return
        if not junction.exists():
            return
    if str(junction) not in sys.path:
        sys.path.insert(0, str(junction))


_prefer_ascii_docling_parse()

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

TOOL = "docling"


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

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
    )
    from docling.document_converter import (
        DocumentConverter,
        PdfFormatOption,
    )

    cases = [c for c in load_cases() if args.only is None or c["case_id"] == args.only]
    results_dir = write_result(TOOL, "placeholder", {}).parent
    results_dir.mkdir(parents=True, exist_ok=True)

    pipeline_options = PdfPipelineOptions(do_table_structure=True)
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    meta = {
        "python_version": env_info()["python_version"],
        "os": env_info()["os"],
        "platform": env_info()["platform"],
        "package_version": package_version("docling"),
        "tableformer_mode": "ACCURATE",
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
            result = converter.convert(
                str(pdf),
                page_range=(case["page"], case["page"]),
            )
            for index, table in enumerate(result.document.tables):
                try:
                    df = table.export_to_dataframe(doc=result.document)
                    rows = df.fillna("").astype(str).values.tolist()
                except Exception as exc:  # noqa: BLE001
                    rows = []
                    error = error or f"dataframe export failed: {exc}"
                bbox = None
                provs = getattr(table, "prov", None) or []
                if provs:
                    try:
                        bbox = [float(v) for v in provs[0].bbox.as_tuple()]
                    except Exception:
                        bbox = None
                md = ""
                try:
                    md = table.export_to_markdown(doc=result.document)
                except Exception:
                    md = ""
                tables.append(
                    {"table_index": index, "bbox": bbox, "rows": rows}
                )
                raw_tables.append(
                    {
                        "table_index": index,
                        "bbox": bbox,
                        "markdown": md,
                        "label": getattr(table, "label", None),
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
                "note": "Docling TableItem markdown + provenance bbox.",
            },
        )
        print(
            f"{case['case_id']}: tables={len(tables)} "
            f"error={error} elapsed={elapsed:.2f}s"
        )


if __name__ == "__main__":
    main()
