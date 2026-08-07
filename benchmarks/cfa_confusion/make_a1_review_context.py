"""A1 review context generator: system extraction vs human labels for the
three source-coordinate-missing papers (INTERACTION_STATE_CONSERVATISM_AUDIT
category A).

For each paper outputs:
  - system mention extraction (parameter/values/unit/status/anchor)
  - system compiled condition fields
  - human Level-2 AVAILABLE coordinates
  - human notes
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_ingestion.conditions.compiler import compile_conditions
from ultrafast_ingestion.conditions.models import ValidatedRelationGraph
from ultrafast_ingestion.graph.builder import build_candidate_graph
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import table_regions

ARCHIVE = Path(r"C:\Users\RZF\Desktop\博士课题资料\ultrafast agent\ultrafast_laser_memory\data\literature_archive")
GOLD = REPO / "artifacts" / "b1_annotation" / "gold_level2_level3_completed.jsonl"
OUTPUT = REPO / "artifacts" / "b1_annotation" / "a1_review" / "review_context.json"

A1_PAPERS = [
    "56485b9e491b5a05_sc04_025_Crafting interior holes on chemically strengthened thin glass based on ultrafast laser ablation and thermo-shock crack propagations.pdf",
    "a8b1391288403284_Laser micro-hole drilling in thermal barrier coated nickel based superalloy.pdf",
    "5eba6f6a648bfc74_Polymer Composites - 2024 - Li - Process optimization and performance verification of CFRP laser surface modification.pdf",
]


def main() -> None:
    gold_rows = {}
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            gold_rows[row["paper_id"]] = row
    out = []
    for paper_id in A1_PAPERS:
        pdf = ARCHIVE / paper_id
        doc = PyMuPDFDocumentParser().parse(pdf)
        mentions = extract_mentions(doc)
        regions = table_regions(doc)
        ledger = build_ledger(doc, mentions, regions)
        graph = build_candidate_graph(
            doc, ledger.for_condition_linking(doc, regions)
        )
        compiled = compile_conditions(ValidatedRelationGraph(graph=graph))
        human = gold_rows.get(paper_id, {})
        human_available = sorted(
            k for k, v in (human.get("level2_coordinates") or {}).items() if v == "AVAILABLE"
        )
        out.append(
            {
                "paper_id": paper_id,
                "document_version_id": doc.document_version_id,
                "mentions": [
                    {
                        "parameter": m.parameter,
                        "raw_text": m.raw_text,
                        "values": m.values,
                        "unit": m.normalized_unit,
                        "status": m.acceptance_status.value,
                        "context": m.context_class.value,
                        "anchor": m.anchor.block_id if m.anchor else "",
                    }
                    for m in mentions
                ],
                "condition_fields": [
                    {
                        "condition_id": c.condition_id,
                        "fields": {
                            param: {
                                "status": f.status.value,
                                "values": f.values,
                                "unit": f.unit,
                            }
                            for param, f in c.fields.items()
                        },
                    }
                    for c in compiled.conditions
                ],
                "human_level2_available": human_available,
                "human_notes": human.get("notes", ""),
            }
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for entry in out:
        params = sorted({m["parameter"] for m in entry["mentions"]})
        print(f"{entry['paper_id'][:45]}: mentions={len(entry['mentions'])} "
              f"params={params} conditions={len(entry['condition_fields'])} "
              f"human_available={entry['human_level2_available'][:4]}")
    print(f"artifact: {OUTPUT}")


if __name__ == "__main__":
    main()
