"""B1 system-side predictor (Level 1/2/3) - contract B1_CHECKPOINT_V0_1 §1.

Per paper, over the fixed demo target task (SiC fs depth_um):
  Level 1: field statuses (M6 field classification)
  Level 2: canonical coordinate availability (M8 source_state)
  Level 3: CFA facets (M9 assess_all)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ultrafast_cfa.cfa import CFA_VERSION, assess_all
from ultrafast_interaction.canonical import source_state
from ultrafast_interaction.target import (
    TargetCoordinateEvaluator,
    build_target_condition_spec,
)
from ultrafast_reconstructibility.adapter import paper_level_spec, to_source_condition_spec
from ultrafast_reconstructibility.report import build_report

TARGET_SCOPE = {
    "material_id": "SiC",
    "laser_type": "fs",
    "process_type": "fs_laser_processing",
    "geometry_type": "rectangular_groove",
    "target_metric": "depth_um",
}

TARGET_CSV = Path(__file__).resolve().parents[2] / "data" / "test_fixture" / "topic2_experiments_v1.csv"


def predict_paper(
    document,
    mentions: list,
    regions: list,
    *,
    target_scope: dict[str, Any] | None = None,
    evidence_material: str | None = None,
    evidence_scope: dict[str, Any] | None = None,
    version: str = CFA_VERSION,
) -> dict[str, Any]:
    """System prediction for one paper (all three levels).

    evidence_scope comes from EvidenceMetadata (③A) - material/laser/process/
    geometry are metadata inputs, never guessed from M6 physics conditions.
    Missing metadata -> UNKNOWN (never inferred).
    """
    from ultrafast_ingestion.candidates.ledger import build_ledger
    from ultrafast_ingestion.conditions.compiler import compile_conditions
    from ultrafast_ingestion.conditions.models import ValidatedRelationGraph
    from ultrafast_ingestion.graph.builder import build_candidate_graph

    scope = target_scope or TARGET_SCOPE
    if evidence_scope is None:
        evidence_scope = {"material_id": evidence_material}
    ledger = build_ledger(document, mentions, regions)
    graph = build_candidate_graph(
        document, ledger.for_condition_linking(document, regions)
    )
    compiled = compile_conditions(ValidatedRelationGraph(graph=graph))

    # Level 1: field statuses across conditions (parameter -> status set)
    field_statuses: dict[str, list[str]] = {}
    for condition in compiled.conditions:
        for param, field in condition.fields.items():
            field_statuses.setdefault(param, []).append(field.status.value)

    # Level 2/3: per-condition evaluation + paper-level fallback.
    # A1 fix (COMPILER_SINGLETON): singleton mentions never join a compiled
    # condition, so the paper-level spec covers papers whose frequency/speed
    # only appear outside condition components. Multi-condition papers keep
    # per-condition precision; the facet summary takes the highest judgement
    # across conditions AND the paper-level view.
    specs = [
        to_source_condition_spec(c, document_version_id=document.document_version_id)
        for c in compiled.conditions
    ]
    paper_spec = paper_level_spec(document, mentions)
    states = [source_state(build_report(s)) for s in specs] + [
        source_state(build_report(paper_spec))
    ]
    coordinates: dict[str, dict[str, Any]] = {}
    for state in states:
        for name, coord in state.coordinates.items():
            coordinates[name] = {
                "availability": coord.availability.value,
                "reason": coord.reason,
            }

    # Level 3: CFA facets (per condition + paper level)
    target_spec = build_target_condition_spec(
        TARGET_CSV,
        equipment_profile={"spot_radius_um": (5.0, "um", False)},
        equipment_profile_id="EQ-DEMO-FS",
    )
    target = _target_state(target_spec)
    cfa_reports = []
    for state in states:
        cfa_reports.append(
            assess_all(
                task_scope=scope,
                evidence_scope=evidence_scope,
                source=state,
                target=target,
                evidence_claim_id=paper_spec.condition_id,
                version=version,
            ).to_dict()
        )
    return {
        "paper_id": document.paper_id,
        "target_task": scope["material_id"],
        "evidence_material": evidence_scope.get("material_id"),
        "level1_field_statuses": field_statuses,
        "level2_coordinates": coordinates,
        "level3_cfa": {
            "reports": cfa_reports,
            # InteractionState = highest judgement across conditions + paper level
            "facet_summary": _facet_summary(cfa_reports),
        },
    }


def _target_state(target_spec):
    from ultrafast_interaction.canonical import target_state

    return target_state(TargetCoordinateEvaluator().evaluate(target_spec), condition_id="target")


def _facet_summary(reports: list[dict]) -> dict[str, str]:
    """Per-facet summary across ALL conditions (③B-G fix).

    InteractionState takes the highest judgment (any PARTIAL -> PARTIAL;
    all UNKNOWN -> UNKNOWN); other facets follow the first report's status
    (they depend on shared evidence scope).
    """
    summary: dict[str, str] = {}
    if not reports:
        return summary
    facet_names = [f["facet"] for f in reports[0]["facets"]]
    for name in facet_names:
        statuses = [
            next(f for f in rep["facets"] if f["facet"] == name)["status"]
            for rep in reports
        ]
        if name == "InteractionState":
            if "PARTIAL" in statuses:
                summary[name] = "PARTIAL"
            elif "KNOWN" in statuses:
                summary[name] = "KNOWN"
            elif "UNKNOWN" in statuses:
                summary[name] = "UNKNOWN"
            else:
                summary[name] = statuses[0] if statuses else "UNKNOWN"
        else:
            summary[name] = statuses[0] if statuses else "UNKNOWN"
    return summary


def predict_archive_papers(
    archive_dir: Path,
    paper_ids: list[str],
    output: Path | None = None,
) -> list[dict]:
    """Run the predictor over a list of archive papers (B1 list)."""
    from ultrafast_ingestion import PyMuPDFDocumentParser
    from ultrafast_ingestion.mentions.extractor import extract_mentions
    from ultrafast_ingestion.tables.models import table_regions

    results = []
    for paper_id in paper_ids:
        pdf = archive_dir / paper_id
        try:
            doc = PyMuPDFDocumentParser().parse(pdf)
            result = predict_paper(doc, extract_mentions(doc), table_regions(doc))
        except Exception as exc:  # noqa: BLE001 - batch predictor must not abort
            results.append({"paper_id": paper_id, "error": str(exc)[:200]})
            continue
        results.append(result)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results
