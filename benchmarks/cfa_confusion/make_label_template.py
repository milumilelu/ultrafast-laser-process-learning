"""B1 labeling template generator (Level 2/3).

Produces gold_level2_level3.jsonl with empty slots for the human annotator.
Coordinates are listed from the canonical namespace; the annotator judges
each against the paper (NOT against the system prediction - independence
is the point of the audit).

Usage:
    python benchmarks/cfa_confusion/make_label_template.py \
        --papers papers.txt --output gold_level2_level3.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from ultrafast_physics.registry import available_formulas
from ultrafast_reconstructibility.coordinates import COORDINATES

TARGET_TASK = "sic_fs_depth"

FACETS = (
    "Material",
    "Task",
    "InteractionState",
    "Reconstructibility",
    "Reachability",
)

# already-known Level-1 materials (from S0-2B_B1_annotations.jsonl) as hints
LEVEL1_HINTS = {
    "04_arxiv_2502.16530.pdf": "Diamond",
    "10_arxiv_2411.18093.pdf": "SiC",
    "11_arxiv_2404.09906.pdf": "SiC",
    "13_arxiv_2411.18868.pdf": "SiC",
    "Flat-top picosecond laser texturing of CFRP.pdf": "CFRP",
}


def coordinate_list() -> list[str]:
    """Canonical coordinate namespace (Formula Registry + reported coordinates)."""
    return sorted(set(available_formulas()) | set(COORDINATES))


def template_row(paper_id: str) -> dict:
    row = {
        "paper_id": paper_id,
        "target_task": TARGET_TASK,
        "level2_coordinates": {name: None for name in coordinate_list()},
        "level3_facets": {facet: None for facet in FACETS},
        "notes": "",
    }
    if paper_id in LEVEL1_HINTS:
        row["hint_material_level1"] = LEVEL1_HINTS[paper_id]
    return row


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--papers", required=True, type=Path, help="paper id list (one per line)")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "benchmarks" / "cfa_confusion" / "gold_level2_level3.jsonl",
    )
    args = parser.parse_args()
    paper_ids = [
        p.strip()
        for p in args.papers.read_text(encoding="utf-8").splitlines()
        if p.strip()
    ]
    rows = [template_row(pid) for pid in paper_ids]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"template: {len(rows)} papers -> {args.output}")
    print(f"coordinates per paper: {len(coordinate_list())}")
    print(
        "coordinate vocabulary: AVAILABLE / UNKNOWN / NOT_REPORTED / AMBIGUOUS / "
        "DEPENDENCY_MISSING / TEXT_COVERAGE_BLOCKED / NOT_APPLICABLE"
    )
    print(
        "facet vocabulary: KNOWN / PARTIAL / UNKNOWN / MISMATCH "
        "(Material: KNOWN=同材料, MISMATCH=不同材料, UNKNOWN=材料不明)"
    )


if __name__ == "__main__":
    main()
