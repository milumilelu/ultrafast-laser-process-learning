"""③ Holdout stratified selection (v2): metadata-gold-driven layers.

Layering authority = literature_metadata gold (human material/process),
not filename heuristics. Non-laser-processing papers (structural/crash/
bond/adhesion engineering) are excluded. Run AFTER the code freeze.
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
OUTPUT = REPO / "artifacts" / "cfa_holdout" / "holdout_selection.json"

B1_25 = [
    line.strip()
    for line in (REPO / "artifacts" / "b1_annotation" / "papers.txt").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
DAMAGED = {"1fe72e7f9c2a6b13", "b3fbe6096e4ea845", "c5f4b1ec78b6429c", "cdbc2697a754cc85", "deca336561a08737"}

# non-laser-processing domains (structural/crash/bond/adhesion engineering etc.)
NON_PROCESS = [
    "crash", "bond", "adhesion", "joint", "shear", "column", "beam-column",
    "crosslap", "rsw", "structural", "strengthen", "flexural", "slip",
    "x-ray", "lens", "wavefront", "refract", "ptychography", "nanofocus",
    "aberrations", "synchrotron", "spectroscopy", "detector", "interferom",
    "propagat", "nonlinear", "parabolic",
]
MATERIAL_FAMILIES = ("sic", "diamond", "cfrp", "glass", "metal", "polymer", "ceramic")


def _canonical_family(material: str | None) -> str | None:
    if material is None:
        return None
    from ultrafast_cfa.cfa import _canonical_material

    return _canonical_material(material)


def is_b1(paper: str) -> bool:
    return any(paper.endswith(b) for b in B1_25)


def main() -> None:
    papers = sorted(p.name for p in ARCHIVE.glob("*.pdf"))
    metadata, _unmatched = load_evidence_metadata(METADATA_GOLD, papers)

    pool: list[str] = []
    by_material: dict[str, list[str]] = {}
    no_meta: list[str] = []
    for paper in papers:
        if is_b1(paper) or any(d in paper for d in DAMAGED) or len(paper) > 230:
            continue
        lower = paper.lower()
        if any(k in lower for k in NON_PROCESS):
            continue
        meta = metadata.get(paper)
        if meta is None:
            no_meta.append(paper)
            continue
        family = _canonical_family(meta.material_id)
        if family is None:
            no_meta.append(paper)
            continue
        pool.append(paper)
        by_material.setdefault(family, []).append(paper)
    print(f"pool (metadata-gold layered): {len(pool)}; no-metadata candidates: {len(no_meta)}")
    for material in MATERIAL_FAMILIES:
        print(f"  {material}: {len(by_material.get(material, []))}")

    # stratified pick: 12 papers, materials balanced, tasks mixed
    selected: list[str] = []
    quota = {"sic": 2, "diamond": 1, "cfrp": 2, "glass": 2, "metal": 2, "polymer": 1, "ceramic": 1}
    for material in MATERIAL_FAMILIES:
        papers_in = by_material.get(material, [])
        for paper in papers_in:
            if len(selected) >= 12 or quota.get(material, 0) <= 0:
                break
            selected.append(paper)
            quota[material] -= 1
    if len(selected) < 12:
        for material in MATERIAL_FAMILIES:
            if len(selected) >= 12:
                break
            for paper in by_material.get(material, []):
                if len(selected) >= 12:
                    break
                if paper not in selected:
                    selected.append(paper)
    # no-metadata papers only as last resort (<=2) to exercise the UNKNOWN path
    if len(selected) < 12 and no_meta:
        for paper in sorted(no_meta):
            if len(selected) >= 12:
                break
            selected.append(paper)

    result = {
        "freeze": "2026-08-07",
        "pool_size": len(pool),
        "no_metadata_candidates": len(no_meta),
        "selected": [
            {
                "paper_id": paper,
                "material": _canonical_family(metadata.get(paper).material_id) if paper in metadata else "unknown",
                "process": metadata.get(paper).process_type if paper in metadata else None,
                "laser_type": metadata.get(paper).laser_type if paper in metadata else None,
                "metadata_available": paper in metadata,
            }
            for paper in sorted(selected)
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"selected: {len(selected)}")
    for row in result["selected"]:
        print(
            f"  [{row['material']!s:8s}][{row['process'] or '-'!s:14s}] "
            f"meta={int(row['metadata_available'])} {row['paper_id'][:55]}"
        )
    print(f"artifact: {OUTPUT}")


if __name__ == "__main__":
    main()
