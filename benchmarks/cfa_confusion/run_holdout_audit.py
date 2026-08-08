"""Holdout audit: CFA predictions vs completed three-level gold (v1.1 / v2).

H1-H5 gates (docs/validation/CFA_V1_1_EVALUATION_CANDIDATE_FREEZE.md §2):
  H1  severe = 0 (asymmetric-risk first metric)
  H2  Unknown is never converted to Mismatch due to missing metadata
  H3  unverified physics coordinates do not contribute positive
      InteractionState evidence
  H4  Material/Task explicit mismatch recognized when metadata available
  H5  Reconstructibility keeps high consistency with human gold

Usage:
  v1.1 (former holdout / v2 diagnostic): python run_holdout_audit.py
  v2 independent holdout:                python run_holdout_audit.py
      --gold artifacts/cfa_holdout/gold_holdout_v2_level1_2_3_completed.jsonl
      --output benchmarks/cfa_confusion/results/holdout_v2_audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from benchmarks.cfa_confusion.audit import audit_report
from benchmarks.cfa_confusion.system_predictor import predict_paper
from ultrafast_cfa.metadata import load_evidence_metadata
from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import table_regions

ARCHIVE = Path(r"C:\Users\RZF\Desktop\博士课题资料\ultrafast agent\ultrafast_laser_memory\data\literature_archive")
GOLD = REPO / "artifacts" / "cfa_holdout" / "gold_holdout_level1_2_3_completed.jsonl"
METADATA_GOLD = REPO / "benchmarks" / "literature_metadata" / "gold" / "annotations.jsonl"
OUTPUT = REPO / "benchmarks" / "cfa_confusion" / "results" / "holdout_audit.json"

FACETS = ("Material", "Task", "InteractionState", "Reconstructibility", "Reachability")


def _find_pdf(prefix8: str) -> Path | None:
    for candidate in ARCHIVE.glob("*.pdf"):
        if candidate.name.startswith(prefix8 + "_"):
            return candidate
    return None


def _evidence_scope(meta) -> dict:
    if meta is None:
        return None
    scope = {}
    for key in ("material_id", "laser_type", "process_type", "geometry_type"):
        value = getattr(meta, key, None)
        if value:
            scope[key] = value
    return scope or None


def _gate_verdicts(gold: list[dict], predictions: list[dict]) -> dict:
    pred_by_paper = {p["paper_id"]: p for p in predictions}
    no_meta_papers = [r for r in gold if not r.get("_metadata_available")]
    h2_violations, h4_material, h4_task, h3_violations = [], [], [], []
    reco_consistent, reco_total = 0, 0
    for row in gold:
        sysp = pred_by_paper.get(row["paper_id"])
        if sysp is None:
            continue
        human = row["level3_facets"]
        system = sysp["level3_cfa"]["facet_summary"]
        if not row["_metadata_available"]:
            for facet in ("Material", "Task"):
                if system.get(facet) == "MISMATCH":
                    h2_violations.append((row["paper_id"], facet))
        if row["_metadata_available"]:
            if human.get("Material") == "MISMATCH" and system.get("Material") == "MISMATCH":
                h4_material.append(row["paper_id"])
            if human.get("Task") == "MISMATCH" and system.get("Task") == "MISMATCH":
                h4_task.append(row["paper_id"])
        if human.get("InteractionState") == "UNKNOWN" and system.get("InteractionState") in ("PARTIAL", "KNOWN"):
            h3_violations.append((row["paper_id"], system.get("InteractionState")))
        if human.get("Reconstructibility") == system.get("Reconstructibility"):
            reco_consistent += 1
        reco_total += 1
    return {
        "H2": {
            "checked_papers": [r["paper_id"].split("_")[0] for r in no_meta_papers],
            "violations": h2_violations,
            "pass": len(h2_violations) == 0,
        },
        "H3": {
            "gold_unknown_interaction": [
                r["paper_id"].split("_")[0]
                for r in gold
                if r["level3_facets"].get("InteractionState") == "UNKNOWN"
            ],
            "violations": h3_violations,
            "pass": len(h3_violations) == 0,
        },
        "H4": {
            "material_recognized": len(h4_material),
            "material_gold_mismatch": sum(
                1 for r in gold if r["_metadata_available"] and r["level3_facets"].get("Material") == "MISMATCH"
            ),
            "task_recognized": len(h4_task),
            "task_gold_mismatch": sum(
                1 for r in gold if r["_metadata_available"] and r["level3_facets"].get("Task") == "MISMATCH"
            ),
        },
        "H5": {
            "consistent": reco_consistent,
            "total": reco_total,
            "rate": round(reco_consistent / reco_total, 3) if reco_total else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, default=GOLD)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    gold = [
        json.loads(line)
        for line in args.gold.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    metadata, _ = load_evidence_metadata(METADATA_GOLD, [p.name for p in ARCHIVE.glob("*.pdf")])

    predictions = []
    for row in gold:
        prefix8 = row["paper_id"].split("_")[0]
        pdf = _find_pdf(prefix8)
        if pdf is None:
            print(f"missing pdf: {row['paper_id']}")
            continue
        meta = next((v for k, v in metadata.items() if k.startswith(prefix8[:8])), None)
        row["_metadata_available"] = meta is not None
        doc = PyMuPDFDocumentParser().parse(pdf)
        prediction = predict_paper(
            doc,
            extract_mentions(doc),
            table_regions(doc),
            evidence_scope=_evidence_scope(meta),
        )
        prediction["paper_id"] = row["paper_id"]
        predictions.append(prediction)

    report = audit_report(gold, predictions)
    gates = _gate_verdicts(gold, predictions)
    gates["H1"] = {
        "severe": report["severity_summary"]["severe"],
        "pass": report["severity_summary"]["severe"] == 0,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"gold_papers": len(gold), "predictions": predictions, "audit": report, "gates": gates},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    print(f"gold: {len(gold)} papers, predicted: {len(predictions)}")
    print("=== per-paper facets (human / system) ===")
    pred_by_paper = {p["paper_id"]: p for p in predictions}
    for row in gold:
        sysp = pred_by_paper.get(row["paper_id"])
        h = row["level3_facets"]
        s = sysp["level3_cfa"]["facet_summary"] if sysp else {}
        meta_tag = "no-meta" if not row["_metadata_available"] else "meta   "
        cells = " ".join(f"{f[:5]}:{h.get(f,'?')[:5]}/{s.get(f,'?')[:5]}" for f in FACETS)
        print(f"  [{meta_tag}] {row['paper_id'].split('_')[0]} {cells}")
    print("=== severity summary ===")
    print(json.dumps(report["severity_summary"], indent=1))
    for facet in report["level3_facets"]:
        print(
            f"  {facet['facet']:18s} severe={facet['severe']} cons_miss={facet['conservative_miss']} "
            f"gap={facet['information_gap']} consistent={facet['consistent']}"
        )
    print("=== H gates ===")
    for name in ("H1", "H2", "H3", "H4", "H5"):
        verdict = gates[name]
        passed = verdict.get("pass")
        print(f"  {name}: {'PASS' if passed else 'CHECK'}  {json.dumps(verdict, ensure_ascii=False)}")
    print(f"artifact: {OUTPUT}")


if __name__ == "__main__":
    main()
