"""B1 gold label validator (format + vocabulary + completeness)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from ultrafast_physics.registry import available_formulas
from ultrafast_reconstructibility.coordinates import COORDINATES

COORDINATE_VOCAB = {
    "AVAILABLE",
    "UNKNOWN",
    "NOT_REPORTED",
    "AMBIGUOUS",
    "DEPENDENCY_MISSING",
    "TEXT_COVERAGE_BLOCKED",
    "NOT_APPLICABLE",
}
FACET_VOCAB = {"KNOWN", "PARTIAL", "UNKNOWN", "MISMATCH"}
FACETS = ("Material", "Task", "InteractionState", "Reconstructibility", "Reachability")


def validate(path: Path, *, require_complete: bool = False) -> dict:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    errors: list[str] = []
    incomplete: list[str] = []
    for row in rows:
        paper = row.get("paper_id", "?")
        coordinates = row.get("level2_coordinates") or {}
        for name, value in coordinates.items():
            if name not in set(available_formulas()) | set(COORDINATES):
                errors.append(f"{paper}: unknown coordinate {name!r}")
            if value is not None and value not in COORDINATE_VOCAB:
                errors.append(f"{paper}: bad coordinate value {name}={value!r}")
            if value is None:
                incomplete.append(f"{paper}:{name}")
        facets = row.get("level3_facets") or {}
        for facet, value in facets.items():
            if facet not in FACETS:
                errors.append(f"{paper}: unknown facet {facet!r}")
            if value is not None and value not in FACET_VOCAB:
                errors.append(f"{paper}: bad facet value {facet}={value!r}")
            if value is None:
                incomplete.append(f"{paper}:{facet}")
    return {
        "papers": len(rows),
        "errors": errors,
        "incomplete_slots": len(incomplete),
        "incomplete": incomplete[:20],
        "complete": len(incomplete) == 0,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "gold",
        type=Path,
        nargs="?",
        default=REPO / "benchmarks" / "cfa_confusion" / "gold_level2_level3.jsonl",
    )
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    report = validate(args.gold, require_complete=args.require_complete)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if report["errors"] or (args.require_complete and not report["complete"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
