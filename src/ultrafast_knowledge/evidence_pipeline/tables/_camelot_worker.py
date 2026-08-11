"""Minimal Camelot process boundary; deliberately imports no project package."""

from __future__ import annotations

import argparse
import json
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages", default="all")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    import camelot

    tables = camelot.read_pdf(args.pdf, pages=args.pages, flavor="ml")
    output = []
    for index, table in enumerate(tables):
        raw_bbox = getattr(table, "_bbox", None) or getattr(table, "bbox", None)
        bbox = [float(value) for value in raw_bbox] if raw_bbox is not None else None
        try:
            report = dict(table.parsing_report or {})
        except (AttributeError, TypeError, ValueError):
            report = {}
        page = max(1, int(getattr(table, "page", 1)))
        output.append(
            {
                "page": page,
                "pdf_page_index": page - 1,
                "table_index": index,
                "bbox": bbox,
                "rows": table.df.fillna("").astype(str).values.tolist(),
                "parsing_report": report,
            }
        )
    Path(args.output).write_text(
        json.dumps(
            {"camelot_version": version("camelot-py"), "tables": output},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
