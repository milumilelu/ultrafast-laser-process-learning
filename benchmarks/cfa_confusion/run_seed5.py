"""B1 seed-5 runner: system predictions vs existing Level-1 annotations.

Reads docs/feasibility/S0-2B_B1_annotations.jsonl (paper-level fields) for
the evidence material, predicts all three levels, and produces a Level-1
confrontation. Level 2/3 human labels land in
gold_level2_level3.jsonl once annotated (B1 17->25 expansion).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from benchmarks.cfa_confusion.system_predictor import predict_paper
from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import table_regions

ARCHIVE = Path(r"C:\Users\RZF\Desktop\博士课题资料\ultrafast agent\ultrafast_laser_memory\data\literature_archive")
ANNOTATIONS = REPO / "docs" / "feasibility" / "S0-2B_B1_annotations.jsonl"
OUTPUT = REPO / "benchmarks" / "cfa_confusion" / "results" / "seed5.json"

# human field name -> system canonical parameter
FIELD_MAP = {
    "wavelength": "wavelength",
    "pulse_width": "pulse_width",
    "frequency": "frequency",
    "average_power": "average_power",
    "pulse_energy": "pulse_energy",
    "spot_size": "spot_size",
    "scan_speed": "scan_speed",
    "hatch_spacing": "hatch_spacing",
    "passes": "passes",
}

HUMAN_STATUS_TO_SYSTEM = {
    "REPORTED_CLEAR": "REPORTED_CLEAR",
    "REPORTED_AMBIGUOUS": "AMBIGUOUS",
    "NOT_REPORTED": "NOT_REPORTED",
    "NOT_APPLICABLE": "NOT_APPLICABLE",
}


def load_annotations(path: Path) -> dict[str, dict]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[row["paper_id"]] = row
    return rows


# 11/13 condition-level reference (S0-2B_B1_REFERENCE_11_13.jsonl): coarse material
REFERENCE_MATERIALS = {
    "11_arxiv_2404.09906.pdf": "SiC",
    "13_arxiv_2411.18868.pdf": "SiC",
}


def level1_confrontation(annotations: dict[str, dict], predictions: list[dict]) -> list[dict]:
    """Human field status vs system condition-level field status (paper level)."""
    out = []
    for prediction in predictions:
        paper_id = prediction["paper_id"]
        human = annotations.get(paper_id)
        if human is None:
            continue
        human_fields = human.get("fields", {})
        system = prediction["level1_field_statuses"]
        rows = []
        for human_name, canonical in FIELD_MAP.items():
            h_entry = human_fields.get(human_name) or {}
            h = HUMAN_STATUS_TO_SYSTEM.get(h_entry.get("status"))
            if h is None:
                continue
            s_statuses = system.get(canonical, [])
            s = "NOT_REPORTED"
            if s_statuses:
                if any(x == "REPORTED_CLEAR" for x in s_statuses):
                    s = "REPORTED_CLEAR"
                elif any(x in ("CONFLICT_PRESERVED", "LINKAGE_AMBIGUOUS") for x in s_statuses):
                    s = "AMBIGUOUS"
            rows.append({"field": human_name, "human": h, "system": s})
        out.append({"paper_id": paper_id, "fields": rows})
    return out


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
    annotations = load_annotations(ANNOTATIONS)
    predictions = []
    for paper_id, row in annotations.items():
        pdf = _find_pdf(ARCHIVE, paper_id)
        if pdf is None:
            print(f"  missing pdf: {paper_id}")
            continue
        doc = PyMuPDFDocumentParser().parse(pdf)
        predictions.append(
            predict_paper(
                doc,
                extract_mentions(doc),
                table_regions(doc),
                evidence_material=row.get("material"),
            )
        )
    # 11/13 from the condition-level reference (S0-2B_B1_REFERENCE_11_13.jsonl)
    for paper_id, material in REFERENCE_MATERIALS.items():
        pdf = _find_pdf(ARCHIVE, paper_id)
        if pdf is None:
            continue
        doc = PyMuPDFDocumentParser().parse(pdf)
        predictions.append(
            predict_paper(
                doc,
                extract_mentions(doc),
                table_regions(doc),
                evidence_material=material,
            )
        )
    confrontation = level1_confrontation(annotations, predictions)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {"predictions": predictions, "level1_confrontation": confrontation},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"predictions: {len(predictions)}")
    for conf in confrontation:
        mismatches = [
            f
            for f in conf["fields"]
            if f["human"] != f["system"]
            and not (f["human"] == "NOT_APPLICABLE" and f["system"] == "NOT_REPORTED")
        ]
        print(
            f"  {conf['paper_id'][:40]}: {len(conf['fields'])} fields, "
            f"{len(mismatches)} mismatches"
        )
        for f in mismatches[:4]:
            print(f"    {f['field']}: human={f['human']} system={f['system']}")
    print(f"artifact: {OUTPUT}")


if __name__ == "__main__":
    main()
