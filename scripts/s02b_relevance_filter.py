"""S0-2B B5: corpus relevance classification (deterministic, no LLM).

Classifies gold/annotations.jsonl papers into:

    TARGET_RELEVANT             -> paper whose laser-processing state we should
                                   try to reconstruct for the target materials
    LASER_RELATED_BUT_OTHER_TASK-> laser paper but not target-material machining
                                   (other material / review / different task)
    MATERIAL_ONLY               -> target material appears but no laser process
    IRRELEVANT                  -> not part of the laser-machining research
                                   corpus at all (structural/adhesive/simulation)
    UNCERTAIN                   -> human review required

This is NOT CFA applicability. It answers: "is this paper part of the corpus
we should attempt reconstructibility measurement on?"

Signals: primary_material, primary_process, laser_type, is_review, title.
Output: docs/feasibility/S0-2B_B5_relevance_classification.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GOLD = Path(
    r"C:\Users\RZF\Desktop\博士课题资料\ultrafast agent"
    r"\ultrafast_laser_memory\benchmarks\literature_metadata\gold\annotations.jsonl"
)
OUT = Path(__file__).resolve().parents[1] / "docs" / "feasibility" / "S0-2B_B5_relevance_classification.jsonl"

TARGET_MATERIALS = {"SiC", "CFRP", "Diamond", "SiCp/Al", "ZrO2"}

LASER_PROCESSES = {
    "cutting", "scribing", "drilling", "milling", "ablation", "surface_texturing",
    "micromachining", "laser_induced_etching",
}
NON_LASER_PROCESSES = {"bonding", "wet_etching", "cleaning", "polishing", "non_laser_reference"}

# title signals -> category hints (lowercase substring match)
STRUCTURAL_KEYWORDS = (
    "strengthen", "shear wall", "bond-slip", "flexural", "crashworthiness", "timber",
    "adhesive", "lap joint", "beam-column", "rc beam", "pull-out", "anchoring",
    "joint", "degradation", "durability", "hygrothermal", "spacecraft", "ao coating",
)
XRAY_SIMULATION_KEYWORDS = (
    "x-ray", "x ray", "synchrotron", "wavefront", "metrology", "ray tracing",
    "molecular dynamics", "ab initio", "simulation", "modelling", "modeling of",
)
REVIEW_HINTS = ("review", "overview", "advances in", "perspective", "state of the art")


def classify(rec: dict) -> dict:
    title = (rec.get("title") or "").lower()
    materials = set(rec.get("primary_material") or [])
    process = rec.get("primary_process") or ""
    laser = rec.get("laser_type") or ""
    is_review = bool(rec.get("is_review"))
    reasons = []

    hits_target = bool(materials & TARGET_MATERIALS)

    if is_review:
        return _result(rec, "LASER_RELATED_BUT_OTHER_TASK", ["is_review"])

    if process in NON_LASER_PROCESSES:
        return _result(rec, "IRRELEVANT", [f"non_laser_process={process}"])

    if process not in LASER_PROCESSES and not laser:
        if any(k in title for k in STRUCTURAL_KEYWORDS):
            return _result(rec, "IRRELEVANT", ["structural/adhesive keywords, no laser signal"])
        if any(k in title for k in XRAY_SIMULATION_KEYWORDS):
            return _result(rec, "IRRELEVANT", ["x-ray/simulation keywords, no laser signal"])
        if hits_target:
            return _result(rec, "MATERIAL_ONLY", ["target material, no laser signal"])
        return _result(rec, "UNCERTAIN", ["no laser signal, no target material"])

    if laser in ("fs", "ps", "ns", "uv"):
        if hits_target and process in LASER_PROCESSES:
            return _result(rec, "TARGET_RELEVANT", ["laser + target material + laser process"])
        if not hits_target:
            return _result(rec, "LASER_RELATED_BUT_OTHER_TASK", ["laser but not target material"])
        return _result(rec, "UNCERTAIN", ["laser + target material, process unclear"])

    # laser type unknown but process is laser-ish
    if process in LASER_PROCESSES:
        if hits_target:
            return _result(rec, "UNCERTAIN", ["laser process + target material, laser_type empty"])
        return _result(rec, "LASER_RELATED_BUT_OTHER_TASK", ["laser process, not target material"])
    if hits_target:
        return _result(rec, "UNCERTAIN", ["target material, weak laser signal"])
    return _result(rec, "UNCERTAIN", ["weak laser signal"])


def _result(rec: dict, category: str, reasons: list[str]) -> dict:
    return {
        "paper_id": rec.get("paper_id"),
        "title": rec.get("title"),
        "primary_material": rec.get("primary_material") or [],
        "primary_process": rec.get("primary_process") or "",
        "laser_type": rec.get("laser_type") or "",
        "category": category,
        "reasons": reasons,
    }


def main() -> None:
    records = [json.loads(line) for line in GOLD.open(encoding="utf-8") if line.strip()]
    results = [classify(r) for r in records]
    OUT.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8"
    )
    from collections import Counter

    counts = Counter(r["category"] for r in results)
    print("total:", len(results))
    for k, v in counts.most_common():
        print(f"  {k}: {v}")
    target_subset = [r for r in results if set(r["primary_material"]) & TARGET_MATERIALS]
    print("\ntarget-material subset:", len(target_subset))
    for k, v in Counter(r["category"] for r in target_subset).most_common():
        print(f"  {k}: {v}")
    print("output:", OUT)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
