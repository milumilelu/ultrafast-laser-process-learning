"""M6-5: batch audit runner (226-paper archive; benchmark-marked)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_ingestion.conditions.compiler import compile_conditions
from ultrafast_ingestion.conditions.models import ValidatedRelationGraph
from ultrafast_ingestion.graph.builder import build_candidate_graph
from ultrafast_ingestion.mentions.extractor import extract_mentions
from ultrafast_ingestion.tables.models import table_regions
from ultrafast_reconstructibility.adapter import to_source_condition_spec
from ultrafast_reconstructibility.report import build_readiness, build_report


def audit_paper(pdf_path: Path) -> dict[str, Any]:
    """One paper -> per-condition reports + readiness (no linking proposals:
    structural conditions only, matching the pilot pipeline's offline mode)."""
    doc = PyMuPDFDocumentParser().parse(pdf_path)
    mentions = extract_mentions(doc)
    regions = table_regions(doc)
    graph = build_candidate_graph(doc, build_ledger_view(doc, mentions, regions))
    compiled = compile_conditions(ValidatedRelationGraph(graph=graph))
    reports = []
    for condition in compiled.conditions:
        spec = to_source_condition_spec(condition, document_version_id=doc.document_version_id)
        reports.append(build_report(spec))
    readiness = build_readiness(reports)
    return {
        "paper_id": doc.paper_id,
        "condition_count": len(reports),
        "reports": [r.to_dict() for r in reports],
        "readiness": readiness.to_dict(),
    }


def build_ledger_view(doc, mentions, regions):
    from ultrafast_ingestion.candidates.ledger import build_ledger

    return build_ledger(doc, mentions, regions).for_condition_linking(doc, regions)


def audit_archive(archive_dir: Path, limit: int | None = None) -> dict[str, Any]:
    """Audit all PDFs in the archive; returns aggregate stats + damaged registry."""
    papers = sorted(archive_dir.glob("*.pdf"))
    if limit is not None:
        papers = papers[:limit]
    all_readiness: list = []
    damaged: list[dict[str, Any]] = []
    for pdf in papers:
        try:
            result = audit_paper(pdf)
        except FileNotFoundError:
            # Windows MAX_PATH: file exists but the path exceeds 260 chars.
            # Recoverable by rename/short path - not a content defect.
            all_readiness.append({"paper_id": pdf.name, "error": "path_too_long"})
            damaged.append(
                {
                    "paper_id": pdf.name,
                    "archive_sha256": _sha256(pdf),
                    "parser_error": "windows max path exceeded",
                    "recoverability": "PATH_TOO_LONG",
                    "fallback_attempted": False,
                }
            )
            continue
        except Exception as exc:  # noqa: BLE001 - batch audit must not abort
            all_readiness.append({"paper_id": pdf.name, "error": str(exc)})
            damaged.append(
                {
                    "paper_id": pdf.name,
                    "archive_sha256": _sha256(pdf),
                    "parser_error": str(exc)[:300],
                    "recoverability": "PDF_CORRUPT",
                    "fallback_attempted": False,
                }
            )
            continue
        all_readiness.append(result["readiness"])
    aggregate = _aggregate(all_readiness)
    return {
        "papers": len(papers),
        "aggregate": aggregate,
        "damaged": damaged,
    }


def _sha256(path: Path) -> str:
    import hashlib

    try:
        # Windows MAX_PATH: prefix \\?\ bypasses the 260-char limit
        raw = Path(r"\\?\\" + str(path)).read_bytes()
        return hashlib.sha256(raw).hexdigest()
    except OSError:
        return ""


def _aggregate(readiness_list: list[dict]) -> dict[str, Any]:
    keys = [
        "reported_field_count",
        "ambiguous_field_count",
        "missing_field_count",
        "coverage_blocked_field_count",
        "computable_coordinate_count",
        "blocked_coordinate_count",
        "reconstructible_conditions",
        "total_conditions",
    ]
    aggregate = {k: sum(r.get(k, 0) for r in readiness_list) for k in keys}
    coordinate_status: dict[str, int] = {}
    for r in readiness_list:
        for coordinate, count in (r.get("coordinate_status") or {}).items():
            coordinate_status[coordinate] = coordinate_status.get(coordinate, 0) + count
    aggregate["coordinate_status"] = coordinate_status
    aggregate["paper_errors"] = sum(1 for r in readiness_list if "error" in r)
    return aggregate
