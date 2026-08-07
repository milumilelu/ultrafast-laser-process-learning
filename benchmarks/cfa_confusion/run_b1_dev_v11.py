"""③A/③B dev regression: v1.1 (EvidenceMetadata + InteractionState summary fix)
vs the frozen v1 baseline, on the B1-25 development set.

Version discipline (contract §5): B1-25 is a DEVELOPMENT set for v1.1 -
results here are "known gaps resolved / not resolved", never generalization
evidence.
"""

from __future__ import annotations

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
GOLD = REPO / "artifacts" / "b1_annotation" / "gold_level2_level3_completed.jsonl"
METADATA_GOLD = REPO / "benchmarks" / "literature_metadata" / "gold" / "annotations.jsonl"
OUTPUT = REPO / "benchmarks" / "cfa_confusion" / "results" / "b1_25_dev_v11.json"

V11_VERSION = "uncalibrated-cfa-v1.1"


def _find_pdf(archive_dir: Path, paper_id: str) -> Path | None:
    exact = archive_dir / paper_id
    if exact.exists():
        return exact
    for candidate in archive_dir.glob("*.pdf"):
        if candidate.name.endswith(paper_id):
            return candidate
    return None


def main() -> None:
    gold = [
        json.loads(line)
        for line in GOLD.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    paper_ids = [row["paper_id"] for row in gold]
    metadata, unmatched = load_evidence_metadata(METADATA_GOLD, paper_ids)
    print(f"metadata matched: {len(metadata)}/{len(paper_ids)}; unmatched: {len(unmatched)}")

    predictions = []
    for row in gold:
        paper_id = row["paper_id"]
        pdf = _find_pdf(ARCHIVE, paper_id)
        if pdf is None:
            print(f"missing pdf: {paper_id}")
            continue
        doc = PyMuPDFDocumentParser().parse(pdf)
        prediction = predict_paper(
            doc,
            extract_mentions(doc),
            table_regions(doc),
            evidence_scope=(
                metadata[paper_id].to_scope() if paper_id in metadata else {}
            ),
            version=V11_VERSION,
        )
        prediction["paper_id"] = paper_id
        prediction["evidence_metadata_matched"] = paper_id in metadata
        predictions.append(prediction)
    report = audit_report(gold, predictions)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {"version": V11_VERSION, "predictions": predictions, "audit": report},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("v1.1 dev regression on B1-25 (development set only):")
    print(json.dumps(report["severity_summary"], ensure_ascii=False, indent=1))
    for facet in report["level3_facets"]:
        print(
            f"  {facet['facet']:18s} matrix={facet['matrix']} "
            f"severe={facet['severe']} cons_miss={facet['conservative_miss']}"
        )
    print(f"artifact: {OUTPUT}")


if __name__ == "__main__":
    main()
