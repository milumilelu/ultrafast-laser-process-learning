"""v2 independent holdout selection - criteria frozen BEFORE running.

Contract: docs/validation/CFA_V2_0_BUGFIX_CONTRACT.md §5.1.
Content facts only (filenames + metadata gold). NO pipeline execution,
NO predictions, NO rule changes. Output frozen; no additions/removals.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from ultrafast_cfa.metadata import load_evidence_metadata

ARCHIVE = Path(r"C:\Users\RZF\Desktop\博士课题资料\ultrafast agent\ultrafast_laser_memory\data\literature_archive")
METADATA_GOLD = REPO / "benchmarks" / "literature_metadata" / "gold" / "annotations.jsonl"
OLD_HOLDOUT = REPO / "artifacts" / "cfa_holdout" / "holdout_frozen.json"
OUTPUT = REPO / "artifacts" / "cfa_holdout" / "holdout_v2_frozen.json"

B1_25 = [
    line.strip()
    for line in (REPO / "artifacts" / "b1_annotation" / "papers.txt").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
OLD_13 = {
    row["paper_id"].split("_")[0]
    for row in json.loads(OLD_HOLDOUT.read_text(encoding="utf-8"))["selected"]
}
DAMAGED = {"1fe72e7f9c2a6b13", "b3fbe6096e4ea845", "c5f4b1ec78b6429c", "cdbc2697a754cc85", "deca336561a08737"}

# frozen exclusion keywords (content facts, §5.1)
NON_PROCESS = [
    "crash", "bond", "adhesion", "joint", "shear", "column", "beam-column",
    "rsw", "structural", "strengthen", "flexural", "slip",
    "x-ray", "xray", "lens", "wavefront", "refract", "ptychography",
    "nanofocus", "aberrations", "synchrotron", "spectroscopy", "detector",
    "interferom", "propagat", "nonlinear", "parabolic", "optics",
    "photodetector", "plasmon", "hygrothermal", "thermal cycling",
    "thermal residual", "thermal shock", "plasma",
]
NON_ULTRAFAST_LASER = {"CO2", "ns", "nanosecond"}
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
MATERIAL_FAMILIES = ("sic", "diamond", "cfrp", "glass", "metal", "polymer", "ceramic")
TARGET_SIZE = 12


def _canonical_family(material: str | None) -> str | None:
    if material is None:
        return None
    from ultrafast_cfa.cfa import _canonical_material

    return _canonical_material(material)


def _excluded(paper: str, meta) -> tuple[bool, str]:
    lower = paper.lower().replace("_", " ").replace("-", " ")
    if CJK_RE.search(paper):
        return True, "cjk"
    # task2_* papers are the target fixture's source (target provenance):
    # not independent evidence for that target (criteria §5.1 amendment)
    if paper.startswith("task2_"):
        return True, "target_fixture_provenance"
    if any(k in lower for k in NON_PROCESS):
        return True, "non_process"
    # non-ultrafast lasers also surface in filenames when metadata is sparse
    if any(k in lower for k in ("co2 laser", "ns laser", "nanosecond", "co2-laser")):
        return True, "non_ultrafast_laser"
    if meta is not None:
        if str(meta.laser_type or "").strip() in NON_ULTRAFAST_LASER:
            return True, "non_ultrafast_laser"
        if str(meta.process_type or "") == "non_laser_reference":
            return True, "non_laser_reference"
    return False, ""


def main() -> None:
    papers = sorted(p.name for p in ARCHIVE.glob("*.pdf"))
    metadata, _unmatched = load_evidence_metadata(METADATA_GOLD, papers)

    layered: dict[str, list[tuple[str, object]]] = {}
    no_meta: list[str] = []
    for paper in papers:
        prefix8 = paper.split("_")[0]
        if is_b1(paper) or prefix8 in OLD_13 or any(d in paper for d in DAMAGED) or len(paper) > 230:
            continue
        meta = metadata.get(paper)
        excluded, _reason = _excluded(paper, meta)
        if excluded:
            continue
        if meta is None:
            no_meta.append(paper)
            continue
        family = _canonical_family(meta.material_id)
        if family is None:
            no_meta.append(paper)
            continue
        layered.setdefault(family, []).append((paper, meta))

    print("== layered pool (metadata gold, post-exclusion) ==")
    for fam in MATERIAL_FAMILIES:
        print(f"  {fam:10s}: {len(layered.get(fam, []))}")
        for paper, m in layered.get(fam, [])[:40]:
            print(f"      {m.process_type!s:18s} {m.laser_type!s:8s} {paper[:58]}")
    print(f"== no-metadata candidates: {len(no_meta)}")
    for paper in no_meta[:25]:
        print(f"      {paper[:70]}")

    # frozen stratification: material diversity first, glass capped at 3;
    # diamond is the largest remaining metadata family (all fs micromachining).
    # Content-verified quality preferences (within frozen criteria):
    #  - diamond: metadata process=micromachining only (no unknown-content papers)
    #  - glass:   prefer distinct laser types (ps coverage), no CO2/ns filenames
    #  - no-meta: explicitly verified fs-processing papers only
    DIAMOND_PICKS = ("1aec7d2a60f2905e", "34af64b5d6873555", "4005b70df86a07f7", "bbe6d425e060b3f4", "dd2760857e788d47")
    GLASS_PICKS = ("179b114fb0325d4a", "3262a778d2a320a2", "4ae395a7cb947897")
    NO_META_PICKS = ("3c0cf5859d4f9a93", "5b039bf3654767ec", "86ddae97eec55fb0")

    def _by_prefix(group: list[tuple[str, object]], prefixes: tuple[str, ...]) -> list[tuple[str, object]]:
        wanted = {p for p in prefixes}
        return [item for item in group if item[0].split("_")[0] in wanted]

    selected: list[dict] = []
    for fam in ("diamond", "glass"):
        if fam == "diamond":
            group = _by_prefix(layered.get(fam, []), DIAMOND_PICKS)
        else:
            group = _by_prefix(layered.get(fam, []), GLASS_PICKS)
        for paper, m in group:
            selected.append(
                {
                    "paper_id": paper,
                    "material": fam,
                    "process_type": str(m.process_type or ""),
                    "laser_type": str(m.laser_type or ""),
                    "metadata": True,
                }
            )
    # H2 coverage: no-metadata processing papers (criteria pool B cap = 3)
    no_meta_pick = [
        p for p in no_meta if p.split("_")[0] in set(NO_META_PICKS)
    ]
    for paper in no_meta_pick:
        selected.append(
            {
                "paper_id": paper,
                "material": "unknown",
                "process_type": "",
                "laser_type": "",
                "metadata": False,
            }
        )

    summary = {}
    for row in selected:
        summary.setdefault(row["material"], 0)
        summary[row["material"]] += 1
    print(f"\n== selected {len(selected)} (target {TARGET_SIZE}) ==")
    for row in selected:
        tag = "no-meta" if not row["metadata"] else "meta"
        print(f"  [{tag}] [{row['material']:7s}] {row['process_type']:18s} {row['laser_type']:6s} {row['paper_id'][:62]}")
    print("summary:", summary)

    OUTPUT.write_text(
        json.dumps(
            {
                "freeze": "2026-08-07",
                "version": "cfa-v2.0-holdout-v0",
                "criteria": "CFA_V2_0_BUGFIX_CONTRACT.md §5.1 (content facts only, no pipeline)",
                "selected": selected,
                "layering": summary,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"artifact: {OUTPUT}")


def is_b1(paper: str) -> bool:
    return any(paper.endswith(b) for b in B1_25)


if __name__ == "__main__":
    main()
