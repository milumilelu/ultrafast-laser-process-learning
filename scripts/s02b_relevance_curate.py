"""S0-2B B5: human curation pass on the first-pass relevance classification.

Merges deterministic classification with title-level human decisions.
Produces docs/feasibility/S0-2B_B5_relevance_curated.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "docs" / "feasibility"
FIRST = BASE / "S0-2B_B5_relevance_classification.jsonl"
OUT = BASE / "S0-2B_B5_relevance_curated.jsonl"

# paper_id -> (final_category, note)  human curation
CURATION = {
    # --- duplicates / erratum: remove from corpus ---
    "5a1106dd9376c1d8_Single-crystal diamond refractive lens for focusing X-rays in two di.pdf": ("DUPLICATE", "erratum of 01_arxiv_1506.04016; no new conditions"),
    "972171e64dcabc55_Single-crystal diamond refractive lens for focusing.pdf": ("DUPLICATE", "same paper as 01_arxiv_1506.04016"),
    "01_arxiv_1506.04016.pdf": ("TARGET_RELEVANT", "diamond lens fabrication via fs machining"),
    # --- UNCERTAIN promoted to TARGET_RELEVANT (laser-processing papers) ---
    "Bessel beam fabrication of graphitic micro electrodes in diamond using laser bursts.pdf": ("TARGET_RELEVANT", "fs Bessel laser processing of diamond"),
    "Effect of Crystallographic Orientation on the Potential Barrier and Conductivity of Bessel Writ.pdf": ("TARGET_RELEVANT", "fs Bessel laser writing in diamond"),
    "Photoluminescence of Femtosecond Laser-irradiated Silicon Carbide.pdf": ("TARGET_RELEVANT", "fs irradiation of SiC (interaction study)"),
    "Probing Silicon Carbide with Phase-Modulated Femtosecond Laser Pulses: Insights into Multiphoto.pdf": ("TARGET_RELEVANT", "fs interaction study on SiC"),
    "Laser writing of scalable single colour centre in silicon carbide.pdf": ("TARGET_RELEVANT", "fs laser writing in SiC"),
    "Concurrent Effect of Laser Texturing and Resin Pre-Coating on the Performance of CFRP Single La.pdf": ("TARGET_RELEVANT", "laser surface texturing of CFRP"),
    "Process optimization and performance verification of CFRP laser surface modification.pdf": ("TARGET_RELEVANT", "CFRP laser surface modification"),
    "The effect of laser-texturing configurations on the interfacial resistance of carbon reinforced.pdf": ("TARGET_RELEVANT", "CFRP laser texturing"),
    "Ultrafast laser surface treatments for improved adhesion on carbon fiber-reinforced polymers.pdf": ("TARGET_RELEVANT", "CFRP laser surface treatment"),
    "Bioinspired Microcavities Enhancing the Interface of Fe-Carbon Fiber-Reinforced Polymer.pdf": ("TARGET_RELEVANT", "CFRP laser microcavity texturing"),
    "Laser ablation surface preparation for adhesive bonding of carbon fiber reinforced epoxy compos.pdf": ("TARGET_RELEVANT", "CFRP laser ablation pretreatment"),
    # --- MATERIAL_ONLY corrections ---
    "Polarization dependence of laser interaction with carbon fibers and CFRP.pdf": ("TARGET_RELEVANT", "laser-material interaction study (title-level)"),
    "Planar refractive lenses made of SiC for high intensity nanofocusing.pdf": ("UNCERTAIN", "X-ray lens; fabrication vs performance unclear"),
    "先进光源装置用碳化硅反射镜性能研究.pdf": ("IRRELEVANT", "SiC mirror performance, non-laser"),
    "Performance of CVD Diamond Single Crystals as Side-bounce Monochromators in the Laue Geometry a.pdf": ("IRRELEVANT", "X-ray monochromator performance, non-laser"),
    "Development of Cycloaliphatic Epoxy-POSS Nanocomposite Matrices with Enhanced Resistance to Ato.pdf": ("IRRELEVANT", "material science, non-laser"),
    "Thermal Effects on Mechanical Strength of Additive Manufactured CFRP Composites at Stable and C.pdf": ("IRRELEVANT", "AM CFRP mechanical, non-laser"),
    # --- IRRELEVANT corrections ---
    "Effects of drilling strategies for CFRP/Ti stacks on static mechanical property and fatigue beh.pdf": ("UNCERTAIN", "drilling strategies; laser vs mechanical unclear at title level"),
    # --- REVIEW: promote to LASER_RELATED_BUT_OTHER_TASK is fine; keep ---
    "A Review of an Investigation of the Ultrafast Laser Processing of Brittle and Hard Materials.pdf": ("LASER_RELATED_BUT_OTHER_TASK", "review; multi-material (incl. SiC/Diamond) - useful background, not experimental source"),
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = [json.loads(l) for l in FIRST.open(encoding="utf-8")]
    final = []
    for r in rows:
        pid = r["paper_id"]
        if pid in CURATION:
            cat, note = CURATION[pid]
            r["category"] = cat
            r["note"] = note
            r["curated"] = True
        else:
            r["curated"] = False
            r["note"] = ""
        final.append(r)
    OUT.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in final), encoding="utf-8"
    )
    from collections import Counter

    print("curated distribution (all 203):")
    for k, v in Counter(r["category"] for r in final).most_common():
        print(f"  {k}: {v}")
    targets = {"SiC", "CFRP", "Diamond", "SiCp/Al", "ZrO2"}
    sub = [r for r in final if set(r["primary_material"]) & targets]
    print("\ncurated distribution (58 target-material papers):")
    for k, v in Counter(r["category"] for r in sub).most_common():
        print(f"  {k}: {v}")
    rel = [r for r in sub if r["category"] == "TARGET_RELEVANT"]
    print("\nTARGET_RELEVANT count:", len(rel))
    for r in sorted(rel, key=lambda x: x["paper_id"]):
        print("  -", r["paper_id"][:95])
    print("\noutput:", OUT)


if __name__ == "__main__":
    main()
