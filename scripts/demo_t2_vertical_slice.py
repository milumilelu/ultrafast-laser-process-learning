"""DEMO runner: scripts/demo_t2_vertical_slice.py (contract §7).

Run the full vertical slice offline:
  python scripts/demo_t2_vertical_slice.py [--output outputs/t2_slice_run.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from demo.t2_slice.pipeline import run_vertical_slice
from demo.t2_slice.resources import PILOT_PAPER_IDS, resolve_pilot_pdf
from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import table_regions

TASK_SPEC = {
    "material": "SiC",
    "laser_type": "fs",
    "process_type": "fs_laser_processing",
    "geometry_type": "rectangular_groove",
    "equipment_profile_id": "EQ-DEMO-FS",
    "objective_metric": "depth_um",
    "random_seed": 42,
    # KnowledgeUseGate（BO 治理）：文献先验进入 BO 的唯一合法路径是
    # governed_prior；此处显式放行并在 audit_trace 中留痕
    "knowledge_gate_decision": {"status": "allowed"},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=REPO / "outputs" / "t2_slice_run.json"
    )
    args = parser.parse_args()

    documents, mentions_by_paper, regions_by_paper = [], {}, {}
    for paper in PILOT_PAPER_IDS:
        doc = PyMuPDFDocumentParser().parse(resolve_pilot_pdf(paper))
        documents.append(doc)
        mentions_by_paper[doc.paper_id] = extract_mentions(doc)
        regions_by_paper[doc.paper_id] = table_regions(doc)

    approval_repo = None  # Demo auto-approve（契约 §4）：approved claims 自动入 repo
    result = run_vertical_slice(
        csv_path=REPO / "data" / "test_fixture" / "topic2_experiments_v1.csv",
        documents=documents,
        mentions_by_paper=mentions_by_paper,
        regions_by_paper=regions_by_paper,
        task_spec=TASK_SPEC,
        approval_repo=approval_repo,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(_summary(result))
    print(f"artifact written: {args.output}")


def _summary(result: dict) -> str:
    lines = [
        "=== Topic2 Vertical Slice (Demo Scenario 01) ===",
        (
            f"target: {result['target_task']['material']} / "
            f"{result['target_task']['objective']} / "
            f"samples={result['target_task']['sample_count']}"
        ),
        (
            f"process learning: view={result['process_learning']['selected_feature_view']} "
            f"model={result['process_learning']['selected_model']}"
        ),
        (
            f"literature: {result['literature_evidence']['paper_count']} papers, "
            f"{result['literature_evidence']['ledger_count']} ledgers"
        ),
        (
            f"evidence: {result['evidence_ir']['meta'].get('claim_count', 0)} claims / "
            f"papers={result['evidence_ir']['meta'].get('paper_count', 0)}"
        ),
        (
            f"e2p prior: {result['e2p_prior']['prior_count']} priors "
            f"accepted={result['e2p_prior']['accepted_count']} "
            f"hash={result['e2p_prior']['governed_prior']['content_hash']}"
        ),
        f"BO vanilla:  {result['bo']['vanilla']['recommended_parameters']}",
        f"BO assisted: {result['bo']['evidence_assisted']['recommended_parameters']}",
        "CFA status: " + result["audit"]["cfa_status"],
        "CFA facets (uncalibrated): "
        + ", ".join(f"{k}={v}" for k, v in result["audit"]["cfa_facets"].items()),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
