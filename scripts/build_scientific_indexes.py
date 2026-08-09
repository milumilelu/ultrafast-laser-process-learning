"""Offline one-time PDF ingestion for persistent scientific Paper/Block indexes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ultrafast_knowledge.evidence_pipeline import (
    ScientificIndexIngestionService,
    ScientificIndexStore,
)
from ultrafast_memory.db.init_db import init_database


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse PDFs once, persist SemanticBlocks, then rebuild Paper/Block indexes."
    )
    parser.add_argument("--pdf", action="append", default=[], help="PDF path; repeatable")
    parser.add_argument("--pdf-root", action="append", default=[], help="Recursive PDF root")
    parser.add_argument(
        "--metadata-json",
        help="Optional mapping keyed by filename with title and metadata fields.",
    )
    return parser.parse_args()


def _metadata(path: Path, mapping: dict[str, Any]) -> dict[str, Any]:
    record = dict(mapping.get(path.name) or {})
    metadata = dict(record.get("metadata") or {})
    return {
        "pdf_path": path,
        "title": str(record.get("title") or path.stem),
        "metadata": metadata,
    }


def main() -> int:
    args = _arguments()
    mapping: dict[str, Any] = {}
    if args.metadata_json:
        mapping = json.loads(Path(args.metadata_json).read_text(encoding="utf-8"))
    paths = {Path(item).expanduser().resolve() for item in args.pdf}
    for root in args.pdf_root:
        paths.update(Path(root).expanduser().resolve().rglob("*.pdf"))
    missing = sorted(str(path) for path in paths if not path.is_file())
    if missing:
        raise FileNotFoundError(f"PDF files not found: {missing}")
    if not paths:
        raise ValueError("at least one --pdf or --pdf-root is required")

    init_database()
    result = ScientificIndexIngestionService(ScientificIndexStore()).ingest_many(
        [_metadata(path, mapping) for path in sorted(paths)],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
