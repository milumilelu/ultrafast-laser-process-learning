"""Shared helpers for the table extraction benchmark.

This module must stay import-light (stdlib only) so it can be reused
from four different virtual environments (pymupdf / docling / paddle /
camelot) without dragging in heavy ML dependencies.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parents[1]
ARCHIVE_DIR = REPO_ROOT / "data" / "literature_archive"
CASES_FILE = BENCH_DIR / "benchmark_cases.json"
RESULTS_DIR = BENCH_DIR / "results"
REVIEW_DIR = RESULTS_DIR / "review"

TOOL_DIRS = {
    "pymupdf": "pymupdf",
    "docling": "docling",
    "paddleocr": "paddleocr",
    "camelot": "camelot",
}

PAGE_RENDER_DPI = 300


def load_cases() -> list[dict]:
    with open(CASES_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["cases"]


def resolve_pdf(pdf_name: str) -> Path:
    path = ARCHIVE_DIR / pdf_name
    if not path.exists():
        raise FileNotFoundError(f"PDF not found in archive: {path}")
    return path


def env_info() -> dict:
    return {
        "python_version": platform.python_version(),
        "os": f"{platform.system()}-{platform.release()}",
        "platform": platform.platform(),
    }


def package_versions() -> dict:
    """Best-effort version map of the relevant packages in the running env."""
    names = [
        "pymupdf",
        "docling",
        "docling-core",
        "paddlepaddle",
        "paddleocr",
        "camelot-py",
        "opencv-python",
        "torch",
        "pandas",
        "numpy",
        "pdfplumber",
    ]
    found: dict[str, str] = {}
    for name in names:
        try:
            mod = __import__(name.replace("-", "_"))
            found[name] = getattr(mod, "__version__", "unknown")
        except Exception:
            pass
    return found


def dump_pip_freeze(out_path: Path) -> None:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out_path.write_text(result.stdout, encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        out_path.write_text(f"pip freeze failed: {exc}", encoding="utf-8")


def normalize_text(text: str) -> str:
    """Conservative normalization applied to gold and predictions.

    Only whitespace handling and unambiguous unicode folding are allowed:
      - strip leading/trailing whitespace
      - collapse consecutive whitespace (incl. newlines) to a single space
      - unify mu/micro (U+03BC, U+00B5) -> "u"
      - unify minus signs (U+2212, U+2013, U+2014 are NOT all minus; only
        U+2212 is folded to "-")
    Explicitly forbidden: unit conversion, rounding, semantic completion.
    """
    if text is None:
        return ""
    s = text.replace("\u00a0", " ").replace("\u2009", " ")
    s = s.replace("\u03bc", "u").replace("\u00b5", "u")
    s = s.replace("\u2212", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def rows_to_normalized(rows: list[list[str]]) -> list[list[str]]:
    return [[normalize_text(c) for c in row] for row in rows]


def find_number_tokens(cell: str) -> list[str]:
    """Extract all numeric tokens from a normalized cell."""
    return re.findall(r"\d+(?:[.,]\d+)?", cell)


def result_path(tool: str, case_id: str) -> Path:
    return RESULTS_DIR / TOOL_DIRS[tool] / f"{case_id}.json"


def raw_path(tool: str, case_id: str) -> Path:
    return RESULTS_DIR / TOOL_DIRS[tool] / f"{case_id}_raw.json"


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def timed(fn, *args, **kwargs) -> tuple[object, float]:
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - start

# --- benchmark-case helpers (kept import-light) ---

GOLD_DIR = BENCH_DIR / "gold"


def load_gold_cases() -> list[dict]:
    """Load gold annotations from gold/*.json (source of truth for rows)."""
    files = sorted(GOLD_DIR.glob("*.json"))
    cases = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            cases.append(json.load(fh))
    return cases


def write_result(tool: str, case_id: str, obj: object) -> Path:
    """Write a unified per-case result, atomically-ish."""
    path = result_path(tool, case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    tmp.replace(path)
    return path


def write_raw(tool: str, case_id: str, obj: object) -> Path:
    path = raw_path(tool, case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    tmp.replace(path)
    return path


def read_result(tool: str, case_id: str) -> dict | None:
    path = result_path(tool, case_id)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def package_version(pkg_name: str) -> str:
    """Query installed distribution version without importing heavy modules."""
    try:
        from importlib import metadata
        return metadata.version(pkg_name)
    except Exception:
        return "unknown"

