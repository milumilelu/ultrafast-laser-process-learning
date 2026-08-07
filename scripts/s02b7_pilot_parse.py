"""S0-2B7 Layer 1/2 pilot runner: parse 5 pilot PDFs, write artifacts,
extract mentions, emit mention audit (no linking).

Usage:
    python scripts/s02b7_pilot_parse.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ultrafast_ingestion import PyMuPDFDocumentParser  # noqa: E402
from ultrafast_ingestion.mentions.extractor import extract_mentions  # noqa: E402
from ultrafast_ingestion.mentions.models import AcceptanceStatus  # noqa: E402

ARCHIVE = Path(
    r"C:\Users\RZF\Desktop\博士课题资料\ultrafast agent"
    r"\ultrafast_laser_memory\data\literature_archive"
)
PILOT = {
    "04_arxiv_2502.16530.pdf": "2dbee78cde23f8f0_04_arxiv_2502.16530.pdf",
    "10_arxiv_2411.18093.pdf": "c896b8bc0f3aac44_10_arxiv_2411.18093.pdf",
    "11_arxiv_2404.09906.pdf": "14bd5786dcb52033_11_arxiv_2404.09906.pdf",
    "13_arxiv_2411.18868.pdf": "2ee9b7fd04167bc5_13_arxiv_2411.18868.pdf",
    "Flat-top picosecond laser texturing of CFRP.pdf": "185a6a0667e0b43d_Flat-top picosecond laser texturing of CFRP.pdf",
}
ARTIFACTS = REPO / "artifacts" / "scientific_documents"
AUDIT_OUT = REPO / "docs" / "feasibility" / "S0-2B7_PILOT_MENTION_AUDIT.jsonl"

# hard regression expectations (paper 13)
REGRESSION = [
    ("13_arxiv_2411.18868.pdf", "kHz", 200.0, AcceptanceStatus.ACCEPTED),
    ("13_arxiv_2411.18868.pdf", "MHz", 40.0, AcceptanceStatus.ACCEPTED),
    ("13_arxiv_2411.18868.pdf", "W", 25.0, AcceptanceStatus.REJECTED_CONTEXT),
    ("13_arxiv_2411.18868.pdf", "nm", 1132.0, AcceptanceStatus.REJECTED_CONTEXT),
    ("13_arxiv_2411.18868.pdf", "nm", 515.0, AcceptanceStatus.ACCEPTED),
]


def main() -> None:
    parser = PyMuPDFDocumentParser()
    audit_rows = []
    summary = {}
    for paper_id, file_name in PILOT.items():
        pdf = ARCHIVE / file_name
        doc = parser.parse(pdf)
        artifact_path = doc.write_artifact(ARTIFACTS)
        mentions = extract_mentions(doc)
        status_counts = Counter(m.acceptance_status.value for m in mentions)
        param_counts = Counter(m.parameter for m in mentions)
        summary[paper_id] = {
            "pages": len(doc.pages),
            "blocks": sum(len(p) for p in doc.pages),
            "sections": len(doc.sections),
            "captions": len(doc.captions),
            "mentions": len(mentions),
            "status": dict(status_counts),
            "top_params": dict(param_counts.most_common(6)),
            "artifact": str(artifact_path.relative_to(REPO)),
        }
        for m in mentions:
            audit_rows.append(
                {
                    "paper_id": paper_id,
                    "parameter": m.parameter,
                    "raw_text": m.raw_text,
                    "values": m.values,
                    "value_type": m.value_type.value,
                    "unit": m.normalized_unit,
                    "status": m.acceptance_status.value,
                    "context_class": m.context_class.value,
                    "reason": m.rejection_reason,
                    "page": m.anchor.pdf_page_index if m.anchor else None,
                }
            )
    # regression checks
    checks = []
    for paper_id, unit, value, expected in REGRESSION:
        hits = [
            m
            for m in audit_rows
            if m["paper_id"] == paper_id
            and m["unit"] == unit
            and any(abs(v - value) < 1e-9 for v in m["values"])
        ]
        ok = bool(hits) and all(m["status"] == expected.value for m in hits)
        checks.append(
            {
                "paper": paper_id,
                "unit": unit,
                "value": value,
                "expected": expected.value,
                "actual": [h["status"] for h in hits],
                "pass": ok,
            }
        )

    with AUDIT_OUT.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"summary": summary, "regression": checks}, ensure_ascii=False) + "\n")
        for row in audit_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("== pilot parse + mention audit ==")
    for pid, s in summary.items():
        print(
            f"{pid[:40]:42s} pages={s['pages']:3d} blocks={s['blocks']:4d} "
            f"sections={s['sections']:2d} mentions={s['mentions']:3d} {s['status']}"
        )
    print("\n== regression ==")
    for c in checks:
        print(("PASS" if c["pass"] else "FAIL"), c["paper"][:30], c["unit"], c["value"], "->", c["actual"])
    print("\naudit:", AUDIT_OUT)


if __name__ == "__main__":
    main()
