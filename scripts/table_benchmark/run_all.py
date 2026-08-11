"""Unified entry point for the table benchmark.

Each adapter runs in its own virtual environment (see README); this script
only orchestrates subprocesses and then runs the evaluator.

Usage:
    python scripts/table_benchmark/run_all.py [--cases ...] [--skip-evaluate]
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

from common import BENCH_DIR, CASES_FILE, REPO_ROOT, TOOL_DIRS

VENV_DIRS = {
    "pymupdf": ".venv-table-pymupdf",
    "docling": ".venv-table-docling",
    "paddleocr": ".venv-table-paddle",
    "camelot": ".venv-table-camelot",
}


def venv_python(venv_name: str) -> Path:
    # Allow an environment override (e.g. TABLE_BENCH_VENV_CAMELOT) because
    # some Windows machines cannot unpack torch inside a long Chinese path
    # (WinError 206), so the Camelot venv may live in a short ASCII path.
    override = os.environ.get(f"TABLE_BENCH_VENV_{venv_name.upper()}")
    if override:
        py = Path(override)
        if not py.exists():
            raise FileNotFoundError(f"venv python not found (override): {py}")
        return py
    root = REPO_ROOT / venv_name
    if platform.system() == "Windows":
        py = root / "Scripts" / "python.exe"
    else:
        py = root / "bin" / "python"
    if not py.exists():
        raise FileNotFoundError(f"venv python not found: {py}")
    return py


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(CASES_FILE))
    parser.add_argument("--skip-evaluate", action="store_true")
    parser.add_argument("--only", default=None, help="run a single case_id through all tools")
    parser.add_argument("--tools", default=",".join(TOOL_DIRS), help="comma-separated tools")
    args = parser.parse_args()

    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    for tool in tools:
        if tool not in TOOL_DIRS:
            raise SystemExit(f"unknown tool: {tool}")

    for tool in tools:
        py = venv_python(VENV_DIRS[tool])
        script = BENCH_DIR / f"run_{tool}.py"
        cmd = [str(py), str(script), "--cases", args.cases]
        if args.only:
            cmd += ["--only", args.only]
        print(f"=== {tool} ({py}) ===")
        subprocess.run(cmd, check=True)

    if not args.skip_evaluate:
        print("=== evaluate ===")
        subprocess.run([sys.executable, str(BENCH_DIR / "evaluate.py")], check=True)


if __name__ == "__main__":
    main()
