"""D1-D4 Calibration Feasibility Inventory (data assets only, NO fitting).

Contract: CFA_V2_0_BUGFIX_CONTRACT.md §6 - inventory is allowed in parallel;
fitting calibrators / selecting calibration mappings / comparing calibrated
scores is FORBIDDEN until v2 independent validation passes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from ultrafast_cfa.metadata import load_evidence_metadata

ARCHIVE = Path(r"C:\Users\RZF\Desktop\博士课题资料\ultrafast agent\ultrafast_laser_memory\data\literature_archive")
METADATA_GOLD = REPO / "benchmarks" / "literature_metadata" / "gold" / "annotations.jsonl"
TARGET_CSV = REPO / "data" / "test_fixture" / "topic2_experiments_v1.csv"
OUTPUT = REPO / "artifacts" / "calibration_inventory" / "d1_d4_inventory.json"


def _count_rows(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    return max(0, sum(1 for _ in csv_path.open(encoding="utf-8")) - 1)


def main() -> None:
    papers = sorted(p.name for p in ARCHIVE.glob("*.pdf"))
    metadata, _unmatched = load_evidence_metadata(METADATA_GOLD, papers)

    # D1: independent target tasks derivable from metadata gold.
    # A "task" = (material family, laser_type, process_type) triple.
    tasks: dict[tuple, dict] = {}
    for paper in papers:
        meta = metadata.get(paper)
        if meta is None or not meta.material_id:
            continue
        from ultrafast_cfa.cfa import _canonical_material

        fam = _canonical_material(meta.material_id)
        key = (fam, str(meta.laser_type or ""), str(meta.process_type or ""))
        entry = tasks.setdefault(key, {"count": 0, "papers": []})
        entry["count"] += 1
        entry["papers"].append(paper.split("_")[0])

    # D2: transfer outcomes - papers whose task triple matches a target
    # task WITH outcome data. Outcome proxy = topic2 fixture rows (the only
    # quantified transfer outcomes in the corpus) + B1 papers with gold facets
    # KNOWN/PARTIAL on Reconstructibility are NOT outcomes.
    target_rows = _count_rows(TARGET_CSV)

    # D3: grouping support for outer split - material families and their
    # per-family paper counts (groups for leave-family-out evaluation).
    families: dict[str, int] = {}
    for (fam, _laser, _proc), entry in tasks.items():
        families[fam] = families.get(fam, 0) + entry["count"]

    # D4: calibrator complexity bound at current sample size.
    # Rule of thumb: parameters << evidence points; with n effective
    # transfer-outcome points, a 1-parameter monotone calibrator (e.g.
    # isotonic without bins, or a single logistic slope) is the ceiling.
    n_outcome = target_rows  # only quantified transfer outcomes count

    report = {
        "D1_target_tasks": {
            "distinct_tasks": len(tasks),
            "breakdown": {
                f"{k[0]}/{k[1] or '?'}/{k[2] or '?'}": v["count"]
                for k, v in sorted(tasks.items())
            },
        },
        "D2_transfer_outcomes": {
            "quantified_target_rows": target_rows,
            "papers_with_quantified_outcome": 0,
            "note": "仅 topic2 fixture 行是量化 transfer outcome；metadata gold 无 outcome 字段",
        },
        "D3_outer_split_support": {
            "families": families,
            "single_paper_families": sum(1 for n in families.values() if n == 1),
            "note": "leave-family-out 要求每族 ≥2；族数 6",
        },
        "D4_calibrator_complexity_ceiling": {
            "effective_outcome_points": n_outcome,
            "max_complexity": "1-parameter monotone (single slope / isotonic 2-3 bins)"
            if n_outcome < 30
            else "2-parameter (sigmoid) if outcome points >= 30",
            "rule": "parameters << outcome points; never more than 1 param per ~10 points",
        },
        "policy": "INVENTORY ONLY - no calibration fitting; formal gate after v2 independent validation",
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"artifact: {OUTPUT}")


if __name__ == "__main__":
    main()
