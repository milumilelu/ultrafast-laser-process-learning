"""v2 holdout three-layer gold template generator (empty slots for human)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from ultrafast_physics.registry import available_formulas
from ultrafast_reconstructibility.coordinates import COORDINATES

HOLDOUT = REPO / "artifacts" / "cfa_holdout" / "holdout_v2_frozen.json"
OUTPUT = REPO / "artifacts" / "cfa_holdout" / "gold_holdout_v2_level1_2_3.jsonl"
PAPERS_DIR = REPO / "artifacts" / "cfa_holdout" / "papers_v2"

FACETS = ("Material", "Task", "InteractionState", "Reconstructibility", "Reachability")


def main() -> None:
    selection = json.loads(HOLDOUT.read_text(encoding="utf-8"))["selected"]
    coordinates = sorted(set(available_formulas()) | set(COORDINATES))
    rows = []
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    for row in selection:
        rows.append(
            {
                "paper_id": row["paper_id"],
                "target_task": "sic_fs_depth",
                "level1": {
                    "material": None,
                    "material_grade": None,
                    "laser_type": None,
                    "process_type": None,
                    "geometry_type": None,
                    "wavelength_nm": None,
                    "notes": "",
                },
                "level2_coordinates": {name: None for name in coordinates},
                "level3_facets": {facet: None for facet in FACETS},
            }
        )
    OUTPUT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"v2 holdout template: {len(rows)} papers -> {OUTPUT}")


if __name__ == "__main__":
    main()
