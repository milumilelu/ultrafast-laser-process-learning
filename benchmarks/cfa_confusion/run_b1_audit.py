"""B1 full audit: 25-paper system predictions vs completed human labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from benchmarks.cfa_confusion.audit import audit_report
from benchmarks.cfa_confusion.system_predictor import predict_paper
from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import table_regions

ARCHIVE = Path(r"C:\Users\RZF\Desktop\博士课题资料\ultrafast agent\ultrafast_laser_memory\data\literature_archive")
GOLD = REPO / "artifacts" / "b1_annotation" / "gold_level2_level3_completed.jsonl"
OUTPUT = REPO / "benchmarks" / "cfa_confusion" / "results" / "b1_25_audit.json"

# evidence_material for the 5 seeded papers (Level-1 annotations); the other
# 20 papers have no Level-1 material label -> None (system never guesses)
SEED_MATERIALS = {
    "04_arxiv_2502.16530.pdf": "Diamond",
    "10_arxiv_2411.18093.pdf": "SiC",
    "11_arxiv_2404.09906.pdf": "SiC",
    "13_arxiv_2411.18868.pdf": "SiC",
    "Flat-top picosecond laser texturing of CFRP.pdf": "CFRP",
}


def _find_pdf(archive_dir: Path, paper_id: str) -> Path | None:
    """Archive files are prefixed (<sha256>_<paper_id>.pdf)."""
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
            evidence_material=SEED_MATERIALS.get(paper_id),
        )
        # parser derives paper_id by stripping the sha prefix; the gold key is
        # the full archive filename - align them for the audit
        prediction["paper_id"] = paper_id
        predictions.append(prediction)
    report = audit_report(gold, predictions)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {"gold_papers": len(gold), "predictions": predictions, "audit": report},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"gold: {len(gold)} papers, predicted: {len(predictions)}")
    print(json.dumps(report["severity_summary"], ensure_ascii=False, indent=1))
    for facet in report["level3_facets"]:
        print(
            f"  {facet['facet']:18s} matrix={facet['matrix']} "
            f"severe={facet['severe']} cons_miss={facet['conservative_miss']} "
            f"gap={facet['information_gap']}"
        )
    print(f"artifact: {OUTPUT}")


if __name__ == "__main__":
    main()
