"""S0-2B B5: human curation pass (v2, fixed exact-ID matching).

Resolves curation entries by exact paper_id OR title-prefix; warns on any
unmatched key. Produces docs/feasibility/S0-2B_B5_relevance_curated.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "docs" / "feasibility"
FIRST = BASE / "S0-2B_B5_relevance_classification.jsonl"
OUT = BASE / "S0-2B_B5_relevance_curated.jsonl"

# paper_id -> (final_category, note)
CURATION = {
    # --- duplicates / erratum: remove from corpus ---
    "5a1106dd9376c1d8_Single-crystal diamond refractive lens for focusing X-rays in two di.pdf": ("DUPLICATE", "erratum of 01_arxiv_1506.04016; no new conditions"),
    "972171e64dcabc55_Single-crystal diamond refractive lens for focusing.pdf": ("DUPLICATE", "same paper as 01_arxiv_1506.04016"),
    # --- UNCERTAIN -> TARGET_RELEVANT (laser-processing papers, verified by full-text scan) ---
    "06_arxiv_2406.12886.pdf": ("TARGET_RELEVANT", "fs Bessel laser processing of diamond"),
    "07_arxiv_2401.02340.pdf": ("TARGET_RELEVANT", "fs Bessel laser writing in diamond"),
    "11_arxiv_2404.09906.pdf": ("TARGET_RELEVANT", "fs irradiation of SiC (interaction study)"),
    "12_arxiv_2310.16315.pdf": ("TARGET_RELEVANT", "fs interaction study on SiC"),
    "20_arxiv_1812.04284.pdf": ("TARGET_RELEVANT", "fs laser writing in SiC"),
    "Concurrent Effect of Laser Texturing and Resin Pre-Coating on the Performance of CFRP Single Lap Joints.pdf": ("TARGET_RELEVANT", "laser surface texturing of CFRP"),
    "Polymer Composites - 2024 - Li - Process optimization and performance verification of CFRP laser surface modification.pdf": ("TARGET_RELEVANT", "CFRP laser surface modification"),
    "The effect of laser-texturing configurations on the interfacial resistance of ca.pdf": ("TARGET_RELEVANT", "CFRP laser texturing"),
    "Ultrafast laser surface treatments for improved adhesion on carbon fiber-re.pdf": ("TARGET_RELEVANT", "CFRP laser surface treatment"),
    "epmc_2025_bioinspired_microcavities_fe_cfrp.pdf": ("TARGET_RELEVANT", "CFRP laser microcavity texturing"),
    "palmieri_ijaa_2016_laser_ablation_cfrp_hygrothermal.pdf": ("TARGET_RELEVANT", "CFRP laser ablation pretreatment"),
    # --- UNCERTAIN -> IRRELEVANT (non-laser X-ray/simulation) ---
    "28_arxiv_1207.1981.pdf": ("IRRELEVANT", "X-ray monochromator beamline, non-laser"),
    "1e1db7c47f124124": ("IRRELEVANT", "X-ray optics model, non-laser"),
    "677e00e7c1eee09f": ("IRRELEVANT", "X-ray grating interferometry light source, non-laser"),
    # --- material-only corrections ---
    "Polarization dependence of laser interaction with carbon fibers and CFRP.pdf": ("TARGET_RELEVANT", "laser-material interaction study (full-text confirmed)"),
    "先进光源装置用碳化硅反射镜性能研究.pdf": ("IRRELEVANT", "SiC mirror performance, non-laser"),
    "Performance of CVD Diamond Single Crystals as Side-bounce Monochromators in the Laue Geometry a.pdf": ("IRRELEVANT", "X-ray monochromator performance, non-laser"),
    "Development of Cycloaliphatic Epoxy-POSS Nanocomposite Matrices with Enhanced Resistance to Ato.pdf": ("IRRELEVANT", "material science, non-laser"),
    "Thermal Effects on Mechanical Strength of Additive Manufactured CFRP Composites at Stable and C.pdf": ("IRRELEVANT", "AM CFRP mechanical, non-laser"),
    # --- keep UNCERTAIN pending abstract-level review ---
    "Effects of drilling strategies for CFRP/Ti stacks on static mechanical property and fatigue beh.pdf": ("UNCERTAIN", "drilling strategies; laser vs mechanical unclear at title level"),
    "Planar refractive lenses made of SiC for high intensity nanofocusing.pdf": ("UNCERTAIN", "X-ray lens; fabrication vs performance unclear"),
    # --- review -> other-task ---
    "A Review of an Investigation of the Ultrafast Laser Processing of Brittle and Hard Materials.pdf": ("LASER_RELATED_BUT_OTHER_TASK", "review; multi-material background, not experimental source"),
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = [json.loads(l) for l in FIRST.open(encoding="utf-8")]
    by_id = {r["paper_id"]: r for r in rows}
    by_title_prefix = {}
    for r in rows:
        by_title_prefix[(r.get("title") or "").lower()] = r

    unresolved = []
    for key, (cat, note) in CURATION.items():
        rec = by_id.get(key)
        if rec is None:
            key_l = key.lower()
            rec = next(
                (r for r in rows if r["paper_id"].lower().startswith(key_l)),
                None,
            )
        if rec is None:
            key_l = key.lower()
            rec = next(
                (r for r in rows if key_l in r["paper_id"].lower()),
                None,
            )
        if rec is None:
            key_l = key.lower()
            for ext in (".pdf", ".txt"):
                if key_l.endswith(ext):
                    key_l = key_l[: -len(ext)]
            rec = next(
                (r for r in rows if key_l in r["paper_id"].lower()),
                None,
            )
        if rec is None:
            key_l = key.lower()
            for ext in (".pdf", ".txt"):
                if key_l.endswith(ext):
                    key_l = key_l[: -len(ext)]
            rec = next(
                (r for r in rows if key_l in (r.get("title") or "").lower()),
                None,
            )
        if rec is None:
            unresolved.append(key)
            continue
        rec["category"] = cat
        rec["note"] = note
        rec["curated"] = True

    if unresolved:
        print("UNRESOLVED curation keys (no match):")
        for u in unresolved:
            print("  -", u)
    else:
        print("all curation keys resolved")

    for r in rows:
        r.setdefault("curated", False)
        r.setdefault("note", "")

    OUT.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    from collections import Counter

    targets = {"SiC", "CFRP", "Diamond", "SiCp/Al", "ZrO2"}
    sub = [r for r in rows if set(r["primary_material"]) & targets]
    print("\ncurated distribution (58 target-material papers):")
    for k, v in Counter(r["category"] for r in sub).most_common():
        print(f"  {k}: {v}")
    rel = [r for r in sub if r["category"] == "TARGET_RELEVANT"]
    print("\nTARGET_RELEVANT:", len(rel))
    for r in sorted(rel, key=lambda x: x["paper_id"]):
        print("  -", r["paper_id"][:95])
    unc = [r for r in sub if r["category"] == "UNCERTAIN"]
    print("\nremaining UNCERTAIN in target subset:", len(unc))
    for r in unc:
        print("  -", r["paper_id"][:95])
    print("\noutput:", OUT)


if __name__ == "__main__":
    main()
