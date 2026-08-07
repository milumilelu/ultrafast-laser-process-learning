from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from ultrafast_knowledge.literature.canonicalizer import normalize_doi, normalize_title
from ultrafast_knowledge.literature.chunk_builder import build_chunks
from ultrafast_knowledge.literature.deduplicator import canonical_paper_id, find_canonical_paper
from ultrafast_knowledge.literature.extraction import EXTRACTION_STATUSES, ExtractionStatus
from ultrafast_knowledge.literature.extraction.extractor import (
    build_extraction_llm_client,
    extract_paper_metadata,
)
from ultrafast_knowledge.literature.extraction.schemas import PaperMetadata
from ultrafast_knowledge.literature.inventory import discover_inventory, inventory_summary
from ultrafast_knowledge.literature.quality import build_quality_report
from ultrafast_knowledge.literature.raw_pdf_loader import parse_pdf
from ultrafast_knowledge.literature.schemas import LiteratureSectionData
from ultrafast_knowledge.literature.section_parser import parse_sections
from ultrafast_knowledge.literature.source_classifier import (
    classify_source_root,
    discover_structured_roots,
)
from ultrafast_knowledge.literature.structured_loader import load_structured_deliverables
from ultrafast_memory.core.config import load_config, resolve_path
from ultrafast_memory.core.ids import stable_id
from ultrafast_memory.core.time_utils import utc_now_iso
from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection


def inventory_literature(root: str) -> dict:
    records = discover_inventory(root)
    summary = inventory_summary(records)
    return {"root": str(Path(root).expanduser().resolve()), **summary, "records": [row.model_dump(mode="json") for row in records]}


def plan_ingestion(root: str) -> dict:
    inventory = inventory_literature(root)
    classification = classify_source_root(root)
    return {
        **classification,
        "discovered_count": inventory["discovered_count"],
        "asset_counts": inventory["asset_counts"],
        "duplicate_file_count": inventory["duplicate_file_count"],
        "structured_roots": [str(path) for path in discover_structured_roots(root)],
    }


def ingest_literature(root: str, mode: str = "auto", force: bool = False) -> dict:
    init_database()
    root_path = Path(root).expanduser().resolve()
    plan = plan_ingestion(str(root_path))
    selected_mode = plan["recommended_mode"] if mode == "auto" else mode
    now = utc_now_iso()
    job_id = stable_id("literature_job", str(root_path), selected_mode, now, uuid.uuid4().hex)
    result = {
        "job_id": job_id,
        "root_path": str(root_path),
        "mode": selected_mode,
        "status": "running",
        "discovered_count": plan["discovered_count"],
        "ingested_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "needs_review_count": 0,
        "needs_ocr_count": 0,
        "paper_count": 0,
        "section_count": 0,
        "chunk_count": 0,
        "candidate_count": 0,
        "metadata_enrichment": {
            "llm_available": False,
            "papers_enriched": 0,
            **{status: 0 for status in sorted(EXTRACTION_STATUSES)},
        },
        "failures": [],
        "errors": [],
    }
    _insert_job(result, now)
    records = discover_inventory(root_path)
    with get_connection() as conn:
        for record in records:
            if record.asset_type != "raw_pdf":
                inserted = _register_artifact(
                    conn,
                    {
                        "artifact_id": stable_id("lart", record.sha256, record.asset_type),
                        "original_path": record.path,
                        "archived_path": record.path,
                        "asset_type": record.asset_type,
                        "sha256": record.sha256,
                        "file_size_bytes": record.file_size_bytes,
                        "parent_root": record.related_root,
                        "parse_status": "registered",
                        "parser_name": "inventory",
                        "parser_version": "1.0.0",
                        "error_message": "",
                        "discovered_at": record.discovered_at,
                        "imported_at": now,
                    },
                )
                result["ingested_count" if inserted else "skipped_count"] += 1
        conn.commit()
    cfg = load_config()
    llm_client = build_extraction_llm_client()
    result["metadata_enrichment"]["llm_available"] = llm_client is not None
    if llm_client is None:
        result["errors"].append(
            "metadata enrichment: LLM 不可用 → 语义角色 abstain（允许 unknown，禁止猜）"
        )

    paper_map: dict[str, str] = {}
    if selected_mode in {"structured_only", "structured_first_with_pdf_backfill", "mixed_unresolved"}:
        for structured_root in discover_structured_roots(root_path):
            try:
                loaded = load_structured_deliverables(structured_root)
                result["errors"].extend(loaded["errors"])
                result["failed_count"] += len(loaded["errors"])
                artifact_id = _structured_artifact_id(structured_root)
                for card_model in loaded["cards"]:
                    card = card_model.model_dump(mode="json")
                    stage = "structured_upsert_paper"
                    try:
                        # One paper per transaction: a later card failure cannot
                        # roll back an earlier successfully enriched paper.
                        with get_connection() as conn:
                            paper, created, needs_review = _upsert_paper(
                                conn,
                                card,
                                artifact_id,
                                source_role="structured_metadata",
                            )
                            stage = "structured_metadata_enrichment"
                            sections = _load_paper_sections(conn, paper["paper_id"])
                            metadata = extract_paper_metadata(
                                paper["paper_id"],
                                sections,
                                page_count=max((item.page_end for item in sections), default=1),
                                llm_client=llm_client if sections else None,
                                paper_title=paper.get("canonical_title") or "",
                            )
                            if not sections:
                                metadata.warnings.append(
                                    "structured literature has no stored full text; semantic fields abstained"
                                )
                            _persist_extraction(conn, paper, metadata)
                        paper_map[card["paper_id"]] = paper["paper_id"]
                        result["paper_count"] += int(created)
                        result["needs_review_count"] += int(needs_review)
                        _increment_metadata_status(result, metadata.extraction_status)
                    except Exception as exc:  # noqa: BLE001 - continue with remaining papers
                        _record_paper_failure(
                            result,
                            source=str(structured_root),
                            stage=stage,
                            exc=exc,
                            paper_id=str(card.get("paper_id") or ""),
                        )
                stage = "structured_candidates"
                try:
                    with get_connection() as conn:
                        candidates = loaded["candidates"] or loaded["claims"]
                        for candidate in candidates:
                            source_paper_id = str(candidate.get("paper_id") or "")
                            canonical_id = paper_map.get(source_paper_id, source_paper_id or None)
                            if _ingest_candidate(conn, candidate, canonical_id):
                                result["candidate_count"] += 1
                except Exception as exc:  # noqa: BLE001 - candidate import is independently retryable
                    result["failed_count"] += 1
                    result["errors"].append(
                        f"{structured_root} [stage={stage}] {type(exc).__name__}: {exc}"
                    )
            except Exception as exc:  # noqa: BLE001 - isolate malformed structured roots
                result["failed_count"] += 1
                result["errors"].append(
                    f"{structured_root} [stage=load_structured] {type(exc).__name__}: {exc}"
                )
    if selected_mode in {"raw_pdf_only", "structured_first_with_pdf_backfill", "mixed_unresolved"}:
        archive_dir = resolve_path(cfg.get("literature", {}).get("archive_dir", "data/literature_archive"))
        chunk_cfg = cfg.get("rag", {}).get("chunking", {})
        pdf_records = [record for record in records if record.asset_type == "raw_pdf"]
        seen_sha: set[str] = set()
        for record in pdf_records:
            if record.sha256 in seen_sha:
                result["skipped_count"] += 1
                continue
            seen_sha.add(record.sha256)
            stage = "duplicate_check"
            paper: dict[str, Any] | None = None
            artifact_ingested = 0
            paper_created = 0
            paper_needs_review = 0
            sections_created = 0
            chunks_created = 0
            metadata_status: str | None = None
            try:
                if not force:
                    with get_connection() as conn:
                        existing_artifact = conn.execute(
                            "SELECT artifact_id FROM literature_artifact WHERE sha256=? AND asset_type='raw_pdf'",
                            (record.sha256,),
                        ).fetchone()
                        if existing_artifact:
                            linked = conn.execute(
                                "SELECT 1 FROM literature_paper_source WHERE artifact_id=? LIMIT 1",
                                (existing_artifact["artifact_id"],),
                            ).fetchone()
                            chunked = conn.execute(
                                "SELECT 1 FROM literature_chunk WHERE artifact_id=? LIMIT 1",
                                (existing_artifact["artifact_id"],),
                            ).fetchone()
                            # Only a linked and chunked artifact is complete.
                            # needs_ocr/ocr_retryable are deliberately retried.
                            if linked and chunked:
                                result["skipped_count"] += 1
                                continue
                stage = "parse_pdf"
                parsed = parse_pdf(record.path, archive_dir)
                if parsed.parse_status == "needs_ocr":
                    stage = "ocr"
                    try:
                        parsed = _recover_needs_ocr(parsed)
                    except Exception as exc:  # noqa: BLE001 - persist retryable OCR state
                        parsed.artifact["parse_status"] = "ocr_retryable"
                        parsed.artifact["error_message"] = (
                            f"stage=ocr; {type(exc).__name__}: {exc}"
                        )
                        with get_connection() as conn:
                            artifact_created = _register_artifact(
                                conn,
                                parsed.artifact,
                                refresh_existing=True,
                            )
                            paper, created, needs_review = _upsert_paper(
                                conn,
                                parsed.metadata,
                                parsed.artifact["artifact_id"],
                                source_role="original_pdf",
                                prefer_existing=True,
                            )
                            failed_metadata = PaperMetadata(
                                paper_id=paper["paper_id"],
                                extraction_status=ExtractionStatus.FAILED.value,
                                warnings=[parsed.artifact["error_message"]],
                            )
                            _persist_extraction(conn, paper, failed_metadata)
                        result["ingested_count"] += int(artifact_created)
                        result["paper_count"] += int(created)
                        result["needs_review_count"] += int(needs_review)
                        result["needs_ocr_count"] += 1
                        _increment_metadata_status(
                            result,
                            ExtractionStatus.FAILED.value,
                        )
                        _record_paper_failure(
                            result,
                            source=record.path,
                            stage=stage,
                            exc=exc,
                            paper_id=paper["paper_id"],
                        )
                        continue
                stage = "persist_artifact"
                with get_connection() as conn:
                    artifact_created = _register_artifact(
                        conn,
                        parsed.artifact,
                        force=force,
                        refresh_existing=True,
                    )
                    if force:
                        conn.execute(
                            "DELETE FROM rag_index_entry WHERE chunk_id IN (SELECT chunk_id FROM literature_chunk WHERE artifact_id=?)",
                            (parsed.artifact["artifact_id"],),
                        )
                        conn.execute("DELETE FROM literature_chunk WHERE artifact_id=?", (parsed.artifact["artifact_id"],))
                        conn.execute("DELETE FROM literature_section WHERE artifact_id=?", (parsed.artifact["artifact_id"],))
                    if not artifact_created and not force:
                        existing_link = conn.execute(
                            "SELECT paper_id FROM literature_paper_source WHERE artifact_id = ?",
                            (parsed.artifact["artifact_id"],),
                        ).fetchone()
                        existing_chunks = conn.execute(
                            "SELECT count(*) AS count FROM literature_chunk WHERE artifact_id = ?",
                            (parsed.artifact["artifact_id"],),
                        ).fetchone()["count"]
                        if existing_link and existing_chunks:
                            result["skipped_count"] += 1
                            conn.commit()
                            continue
                    if parsed.parse_status == "failed":
                        _record_paper_failure(
                            result,
                            source=record.path,
                            stage="parse_pdf",
                            exc=RuntimeError(parsed.error_message or "PDF parse failed"),
                        )
                        continue
                    stage = "upsert_paper"
                    paper, created, needs_review = _upsert_paper(
                        conn,
                        parsed.metadata,
                        parsed.artifact["artifact_id"],
                        source_role="original_pdf",
                        prefer_existing=True,
                    )
                    paper_created = int(created)
                    paper_needs_review = int(needs_review)
                    stage = "parse_sections"
                    sections = parse_sections(paper["paper_id"], parsed.artifact["artifact_id"], parsed.pages)
                    for section in sections:
                        values = section.model_dump(mode="json")
                        values["created_at"] = utc_now_iso()
                        cursor = conn.execute(
                            """
                            INSERT OR IGNORE INTO literature_section
                            (section_id,paper_id,artifact_id,section_type,section_title,page_start,page_end,text,text_hash,parser_version,created_at)
                            VALUES (:section_id,:paper_id,:artifact_id,:section_type,:section_title,:page_start,:page_end,:text,:text_hash,:parser_version,:created_at)
                            """,
                            values,
                        )
                        sections_created += max(cursor.rowcount, 0)
                    stage = "metadata_enrichment"
                    paper_metadata = extract_paper_metadata(
                        paper["paper_id"],
                        sections,
                        page_count=parsed.page_count,
                        llm_client=llm_client,
                        paper_title=paper.get("canonical_title") or "",
                    )
                    _persist_extraction(conn, paper, paper_metadata)
                    metadata_status = paper_metadata.extraction_status
                    paper["primary_material"] = json.dumps(paper_metadata.primary_material, ensure_ascii=False)
                    paper["primary_material_grade"] = json.dumps(paper_metadata.primary_material_grade, ensure_ascii=False)
                    paper["primary_process"] = paper_metadata.primary_process
                    paper["material_roles"] = json.dumps(paper_metadata.mention_roles(), ensure_ascii=False)
                    paper["process_roles"] = json.dumps(paper_metadata.process_roles(), ensure_ascii=False)
                    stage = "build_chunks"
                    chunks = build_chunks(
                        _paper_for_chunk(paper),
                        sections,
                        target_tokens=int(chunk_cfg.get("target_tokens", 450)),
                        min_tokens=int(chunk_cfg.get("min_tokens", 120)),
                        max_tokens=int(chunk_cfg.get("max_tokens", 700)),
                        overlap_tokens=int(chunk_cfg.get("overlap_tokens", 80)),
                        include_references=bool(cfg.get("literature", {}).get("include_references_section", False)),
                    )
                    for chunk in chunks:
                        cursor = _insert_chunk(conn, chunk, ignore_existing=True)
                        chunks_created += max(cursor.rowcount, 0)
                    artifact_ingested = int(artifact_created)
                # Only publish counters after the per-paper transaction commits.
                result["ingested_count"] += artifact_ingested
                result["paper_count"] += paper_created
                result["needs_review_count"] += paper_needs_review
                result["section_count"] += sections_created
                result["chunk_count"] += chunks_created
                if metadata_status is not None:
                    _increment_metadata_status(result, metadata_status)
            except Exception as exc:  # noqa: BLE001 - isolate failure to this paper
                _record_paper_failure(
                    result,
                    source=record.path,
                    stage=stage,
                    exc=exc,
                    paper_id=(paper.get("paper_id") if paper is not None else ""),
                )
    result["status"] = "completed_with_errors" if result["failed_count"] else "completed"
    result["quality_report"] = build_quality_report()
    _finish_job(result)
    return result


def get_ingestion_status(job_id: str) -> dict:
    init_database()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM rag_ingestion_job WHERE job_id = ?", (job_id,)).fetchone()
    if not row:
        raise ValueError(f"ingestion job not found: {job_id}")
    result = dict(row)
    result["config"] = json.loads(result.pop("config_json") or "{}")
    return result


def list_papers(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    init_database()
    with get_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM literature_paper ORDER BY updated_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()]


def get_paper(paper_id: str) -> dict[str, Any]:
    init_database()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM literature_paper WHERE paper_id = ?", (paper_id,)).fetchone()
        if not row:
            raise ValueError(f"paper not found: {paper_id}")
        result = dict(row)
        result["sources"] = [dict(item) for item in conn.execute("SELECT * FROM literature_paper_source WHERE paper_id = ?", (paper_id,)).fetchall()]
        result["mentions"] = [
            dict(item)
            for item in conn.execute(
                "SELECT * FROM literature_mention WHERE paper_id = ? ORDER BY kind, page, canonical_id",
                (paper_id,),
            ).fetchall()
        ]
        return result


def get_paper_chunks(paper_id: str) -> list[dict[str, Any]]:
    init_database()
    with get_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM literature_chunk WHERE paper_id = ? ORDER BY chunk_index", (paper_id,)).fetchall()]


def _increment_metadata_status(result: dict[str, Any], status: str) -> None:
    normalized = status if status in EXTRACTION_STATUSES else ExtractionStatus.FAILED.value
    result["metadata_enrichment"]["papers_enriched"] += 1
    result["metadata_enrichment"][normalized] += 1


def _record_paper_failure(
    result: dict[str, Any],
    *,
    source: str,
    stage: str,
    exc: Exception,
    paper_id: str = "",
) -> None:
    failure = {
        "source": str(source),
        "paper_id": paper_id,
        "stage": stage,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "retryable": stage in {
            "parse_pdf",
            "ocr",
            "persist_artifact",
            "upsert_paper",
            "parse_sections",
            "metadata_enrichment",
            "build_chunks",
            "structured_upsert_paper",
            "structured_metadata_enrichment",
        },
    }
    result["failed_count"] += 1
    result["failures"].append(failure)
    result["errors"].append(
        f"{source} [stage={stage}] {failure['error_type']}: {failure['error_message']}"
    )


def _load_paper_sections(conn, paper_id: str) -> list[LiteratureSectionData]:
    rows = conn.execute(
        """
        SELECT section_id,paper_id,artifact_id,section_type,section_title,page_start,
               page_end,text,text_hash,parser_version
        FROM literature_section
        WHERE paper_id=?
        ORDER BY page_start, section_id
        """,
        (paper_id,),
    ).fetchall()
    return [LiteratureSectionData.model_validate(dict(row)) for row in rows]


def _insert_chunk(conn, chunk, *, ignore_existing: bool):
    values = chunk.model_dump(mode="json")
    values["metadata_json"] = json.dumps(values.pop("metadata"), ensure_ascii=False)
    values["active"] = int(values["active"])
    values["created_at"] = utc_now_iso()
    values["updated_at"] = values["created_at"]
    conflict = "OR IGNORE " if ignore_existing else ""
    return conn.execute(
        f"""
        INSERT {conflict}INTO literature_chunk
        (chunk_id,paper_id,section_id,artifact_id,chunk_index,page_start,page_end,
         section_type,section_title,content,content_hash,token_estimate,metadata_json,
         evidence_level,review_status,active,created_at,updated_at)
        VALUES
        (:chunk_id,:paper_id,:section_id,:artifact_id,:chunk_index,:page_start,:page_end,
         :section_type,:section_title,:content,:content_hash,:token_estimate,:metadata_json,
         :evidence_level,:review_status,:active,:created_at,:updated_at)
        """,
        values,
    )


def _recover_needs_ocr(parsed):
    """Resolve a scanned PDF into page text or raise a retryable, explicit error."""
    init_database()
    ocr_config = load_config().get("parsers", {}).get("paddleocr", {})
    if not bool(ocr_config.get("enabled", True)):
        raise RuntimeError("PaddleOCR is disabled by parsers.paddleocr.enabled")

    source_hash = str(parsed.artifact["sha256"])
    pages_by_number: dict[int, list[str]] = {}
    with get_connection() as conn:
        cached = conn.execute(
            "SELECT document_id FROM ocr_document WHERE source_hash=? ORDER BY created_at DESC LIMIT 1",
            (source_hash,),
        ).fetchone()
        if cached:
            rows = conn.execute(
                """
                SELECT page_number,content FROM document_element
                WHERE document_id=? ORDER BY page_number, rowid
                """,
                (cached["document_id"],),
            ).fetchall()
            for row in rows:
                pages_by_number.setdefault(int(row["page_number"]), []).append(row["content"])

    if not pages_by_number:
        from ultrafast_integrations.ocr import PaddleOcrProvider
        from ultrafast_integrations.storage.ocr_repository import OcrDocumentRepository

        provider = PaddleOcrProvider(
            parser_version=str(ocr_config.get("parser_version") or "3.x-adapter-1.0")
        )
        document = provider.parse(
            {
                "artifact_id": parsed.artifact["artifact_id"],
                "path": parsed.artifact.get("archived_path") or parsed.artifact["original_path"],
                "sha256": source_hash,
            }
        )
        if not document.elements:
            raise RuntimeError("PaddleOCR returned no text elements")
        OcrDocumentRepository().save(document)
        for element in document.elements:
            pages_by_number.setdefault(int(element.page_number), []).append(element.content)

    from ultrafast_knowledge.literature.schemas import PageText

    pages = [
        PageText(page_number=page, text="\n".join(parts))
        for page, parts in sorted(pages_by_number.items())
        if any(part.strip() for part in parts)
    ]
    if not pages:
        raise RuntimeError("PaddleOCR produced only blank text")
    parsed.pages = pages
    parsed.page_count = max(page.page_number for page in pages)
    parsed.average_chars_per_page = sum(len(page.text.strip()) for page in pages) / len(pages)
    parsed.parse_status = "parsed_with_ocr"
    parsed.error_message = ""
    parsed.artifact["parse_status"] = parsed.parse_status
    parsed.artifact["parser_name"] = "paddleocr"
    parsed.artifact["parser_version"] = str(
        ocr_config.get("parser_version") or "3.x-adapter-1.0"
    )
    parsed.artifact["error_message"] = ""
    return parsed


def _register_artifact(
    conn,
    artifact: dict[str, Any],
    force: bool = False,
    *,
    refresh_existing: bool = False,
) -> bool:
    existing = conn.execute(
        "SELECT artifact_id FROM literature_artifact WHERE sha256 = ? AND asset_type = ?",
        (artifact["sha256"], artifact["asset_type"]),
    ).fetchone()
    if existing:
        if force or refresh_existing:
            conn.execute(
                """
                UPDATE literature_artifact SET archived_path=?, parse_status=?, parser_name=?, parser_version=?,
                error_message=?, imported_at=? WHERE artifact_id=?
                """,
                (
                    artifact.get("archived_path"), artifact.get("parse_status"), artifact.get("parser_name"),
                    artifact.get("parser_version"), artifact.get("error_message"), artifact.get("imported_at"), existing["artifact_id"],
                ),
            )
        artifact["artifact_id"] = existing["artifact_id"]
        return False
    conn.execute(
        """
        INSERT INTO literature_artifact
        (artifact_id,original_path,archived_path,asset_type,sha256,file_size_bytes,parent_root,parse_status,parser_name,parser_version,error_message,discovered_at,imported_at)
        VALUES (:artifact_id,:original_path,:archived_path,:asset_type,:sha256,:file_size_bytes,:parent_root,:parse_status,:parser_name,:parser_version,:error_message,:discovered_at,:imported_at)
        """,
        artifact,
    )
    return True


def _structured_artifact_id(root: Path) -> str | None:
    for name in ("literature_cards.jsonl", "paper_table.csv"):
        path = root / name
        if path.exists():
            from ultrafast_knowledge.literature.inventory import sha256_path

            return stable_id("lart", sha256_path(path), "structured_literature_card" if name.endswith("jsonl") else "structured_paper_table")
    return None


PAPER_FIELDS = [
    "authors", "year", "doi", "source", "url", "scenario_id", "material", "material_grade",
    "component_type", "process_type", "laser_type", "wavelength_nm", "pulse_width_fs",
    "power_or_energy", "frequency_kHz", "scan_speed_mm_s", "beam_shape", "environment",
]


def _upsert_paper(conn, metadata: dict[str, Any], artifact_id: str | None, source_role: str, prefer_existing: bool = False):
    # A structured CSV/JSONL artifact can describe many papers. Only a PDF artifact
    # has a one-artifact-to-one-paper identity suitable for SHA-level paper lookup.
    dedup_artifact_id = artifact_id if source_role == "original_pdf" else None
    match = find_canonical_paper(conn, metadata, dedup_artifact_id)
    now = utc_now_iso()
    if match["paper"]:
        paper = match["paper"]
        updates: dict[str, Any] = {}
        for field in PAPER_FIELDS:
            incoming = metadata.get(field)
            if incoming in (None, ""):
                continue
            if paper.get(field) in (None, "") or not prefer_existing:
                updates[field] = normalize_doi(str(incoming)) if field == "doi" else incoming
            elif str(paper.get(field)) != str(incoming):
                updates["review_status"] = "needs_review"
        title = metadata.get("title") or metadata.get("canonical_title")
        if title and (not paper.get("canonical_title") or not prefer_existing):
            updates["canonical_title"] = title
            updates["normalized_title"] = normalize_title(str(title))
        if match["needs_review"]:
            updates["review_status"] = "needs_review"
        if updates:
            updates["updated_at"] = now
            assignments = ", ".join(f"{key} = :{key}" for key in updates)
            conn.execute(f"UPDATE literature_paper SET {assignments} WHERE paper_id = :paper_id", {**updates, "paper_id": paper["paper_id"]})
            paper.update(updates)
        created = False
    else:
        requested_id = canonical_paper_id(metadata)
        collision = conn.execute("SELECT normalized_title FROM literature_paper WHERE paper_id = ?", (requested_id,)).fetchone()
        paper_id = requested_id
        if collision and collision["normalized_title"] != normalize_title(str(metadata.get("title") or "")):
            paper_id = stable_id("paper", requested_id, normalize_title(str(metadata.get("title") or "")), metadata.get("year"))
        paper = {
            "paper_id": paper_id,
            "canonical_title": metadata.get("title") or metadata.get("canonical_title") or "",
            "normalized_title": normalize_title(str(metadata.get("title") or metadata.get("canonical_title") or "")),
            **{field: metadata.get(field) for field in PAPER_FIELDS},
            "doi": normalize_doi(str(metadata.get("doi") or "")),
            "geometry_json": json.dumps(metadata.get("geometry") or {}, ensure_ascii=False),
            "quality_metrics_json": json.dumps(metadata.get("quality_metrics") or {}, ensure_ascii=False),
            "defects_json": json.dumps(metadata.get("defects") or [], ensure_ascii=False),
            "measurement_methods_json": json.dumps(metadata.get("measurement_methods") or [], ensure_ascii=False),
            "usable_for_json": json.dumps(metadata.get("usable_for") or ["literature_background", "evidence_retrieval"], ensure_ascii=False),
            "not_usable_for_json": json.dumps(metadata.get("not_usable_for") or ["direct_parameter_recommendation", "BO_training"], ensure_ascii=False),
            "evidence_level": metadata.get("evidence_level") or "literature_evidence_candidate",
            "review_status": "needs_review" if match["needs_review"] else metadata.get("review_status") or "pending_review",
            "canonical_artifact_id": artifact_id,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO literature_paper
            (paper_id,canonical_title,normalized_title,authors,year,doi,source,url,
             scenario_id,material,material_grade,component_type,process_type,laser_type,
             wavelength_nm,pulse_width_fs,power_or_energy,frequency_kHz,scan_speed_mm_s,
             beam_shape,environment,geometry_json,quality_metrics_json,defects_json,
             measurement_methods_json,usable_for_json,not_usable_for_json,evidence_level,
             review_status,canonical_artifact_id,created_at,updated_at)
            VALUES
            (:paper_id,:canonical_title,:normalized_title,:authors,:year,:doi,:source,:url,:scenario_id,:material,:material_grade,:component_type,:process_type,:laser_type,:wavelength_nm,:pulse_width_fs,:power_or_energy,:frequency_kHz,:scan_speed_mm_s,:beam_shape,:environment,:geometry_json,:quality_metrics_json,:defects_json,:measurement_methods_json,:usable_for_json,:not_usable_for_json,:evidence_level,:review_status,:canonical_artifact_id,:created_at,:updated_at)
            """,
            paper,
        )
        created = True
    if artifact_id:
        conn.execute(
            """
            INSERT OR IGNORE INTO literature_paper_source
            (link_id,paper_id,artifact_id,source_role,version_label,is_canonical,created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (stable_id("paper_source", paper["paper_id"], artifact_id), paper["paper_id"], artifact_id, source_role, "", int(paper.get("canonical_artifact_id") == artifact_id), now),
        )
    return paper, created, paper.get("review_status") == "needs_review"


def _persist_extraction(conn, paper: dict[str, Any], metadata: PaperMetadata) -> None:
    """抽取结果落库：literature_paper 补列 + literature_mention 表（幂等重写）。"""
    row = metadata.as_dict()
    conn.execute(
        """
        UPDATE literature_paper
        SET primary_material=?, primary_material_grade=?, primary_process=?,
            metadata_extraction_status=?, metadata_extractor_version=?, updated_at=?
        WHERE paper_id=?
        """,
        (
            json.dumps(row["primary_material"], ensure_ascii=False),
            json.dumps(row["primary_material_grade"], ensure_ascii=False),
            row["primary_process"],
            row["extraction_status"],
            row["extractor_version"],
            utc_now_iso(),
            paper["paper_id"],
        ),
    )
    conn.execute("DELETE FROM literature_mention WHERE paper_id = ?", (paper["paper_id"],))
    for kind, mentions in (("material", row["material_mentions"]), ("process", row["process_mentions"])):
        for mention in mentions:
            canonical_id = mention.get("canonical_material_id") or mention.get("canonical_process_id")
            conn.execute(
                """
                INSERT INTO literature_mention
                (mention_id,paper_id,kind,raw_text,canonical_id,role,page,section_id,section_type,evidence_span,extraction_method,confidence,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    stable_id(
                        "mention",
                        paper["paper_id"],
                        kind,
                        canonical_id,
                        mention.get("page"),
                        mention.get("section_id"),
                        mention.get("evidence_span"),
                        mention.get("raw_text"),
                    ),
                    paper["paper_id"],
                    kind,
                    mention.get("raw_text"),
                    canonical_id,
                    mention.get("role"),
                    mention.get("page"),
                    mention.get("section_id"),
                    mention.get("section_type"),
                    json.dumps(mention.get("evidence_span")) if mention.get("evidence_span") else None,
                    mention.get("extraction_method"),
                    mention.get("confidence"),
                    utc_now_iso(),
                ),
            )


def _ingest_candidate(conn, candidate: dict[str, Any], paper_id: str | None) -> bool:
    claim = str(candidate.get("claim") or "").strip()
    if not claim:
        return False
    candidate_id = str(candidate.get("candidate_id") or candidate.get("claim_id") or stable_id("kc", paper_id, claim))
    if conn.execute("SELECT 1 FROM knowledge_candidate WHERE candidate_id = ?", (candidate_id,)).fetchone():
        return False
    confidence = candidate.get("confidence")
    if isinstance(confidence, str):
        confidence = {"low": 0.3, "medium": 0.6, "high": 0.85}.get(confidence.lower(), 0.3)
    record = {
        "candidate_id": candidate_id,
        "source_id": candidate.get("source_id"),
        "claim": claim,
        "material": candidate.get("material"),
        "process_type": candidate.get("process_type"),
        "component_type": candidate.get("component_type"),
        "parameter_json": json.dumps(candidate.get("parameter_json") or {}, ensure_ascii=False),
        "condition_json": json.dumps(candidate.get("condition_json") or {}, ensure_ascii=False),
        "usable_for_json": json.dumps(candidate.get("usable_for_json") or candidate.get("usable_for") or ["literature_background"], ensure_ascii=False),
        "not_usable_for_json": json.dumps(candidate.get("not_usable_for_json") or candidate.get("not_usable_for") or ["direct_parameter_recommendation", "BO_training"], ensure_ascii=False),
        "evidence_type": candidate.get("evidence_type") or "paper_evidence",
        "confidence": float(confidence or 0.3),
        "status": "candidate",
        "review_status": "pending_review",
        "risk_level": candidate.get("risk_level") or "medium",
        "suggested_action": candidate.get("suggested_action") or "accept_as_literature_evidence",
        "conflict_flag": 0,
        "duplicate_of": None,
        "source_quality_score": None,
        "created_at": candidate.get("created_at") or utc_now_iso(),
        "reviewed_by": None,
        "review_comment": None,
        "paper_id": paper_id,
        "evidence_level": candidate.get("evidence_level") or "literature_evidence_candidate",
        "extraction_method": candidate.get("extraction_method") or "structured_import",
    }
    conn.execute(
        """
        INSERT INTO knowledge_candidate
        (candidate_id,source_id,claim,material,process_type,component_type,parameter_json,condition_json,usable_for_json,not_usable_for_json,evidence_type,confidence,status,review_status,risk_level,suggested_action,conflict_flag,duplicate_of,source_quality_score,created_at,reviewed_by,review_comment,paper_id,evidence_level,extraction_method)
        VALUES (:candidate_id,:source_id,:claim,:material,:process_type,:component_type,:parameter_json,:condition_json,:usable_for_json,:not_usable_for_json,:evidence_type,:confidence,:status,:review_status,:risk_level,:suggested_action,:conflict_flag,:duplicate_of,:source_quality_score,:created_at,:reviewed_by,:review_comment,:paper_id,:evidence_level,:extraction_method)
        """,
        record,
    )
    review_id = stable_id("review", candidate_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO knowledge_review_task
        (review_id,candidate_id,review_status,priority,risk_level,assigned_to,created_at,updated_at,due_at,auto_suggestion,review_comment)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (review_id, candidate_id, "pending_review", "normal", record["risk_level"], None, utc_now_iso(), utc_now_iso(), None, record["suggested_action"], None),
    )
    return True


def _paper_for_chunk(paper: dict[str, Any]) -> dict[str, Any]:
    result = dict(paper)
    result["title"] = paper.get("canonical_title")
    result["source_id"] = paper.get("canonical_artifact_id")
    for source, target, default in (
        ("usable_for_json", "usable_for", []),
        ("not_usable_for_json", "not_usable_for", []),
    ):
        result[target] = json.loads(paper.get(source) or json.dumps(default))
    return result


def _insert_job(result: dict[str, Any], started_at: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO rag_ingestion_job VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                result["job_id"], result["root_path"], result["mode"], "running", result["discovered_count"],
                0, 0, 0, 0, started_at, None, None, json.dumps({}, ensure_ascii=False),
            ),
        )
        conn.commit()


def _finish_job(result: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE rag_ingestion_job SET status=?,ingested_count=?,skipped_count=?,failed_count=?,needs_review_count=?,finished_at=?,error_summary=?,config_json=? WHERE job_id=?
            """,
            (
                result["status"], result["ingested_count"], result["skipped_count"], result["failed_count"],
                result["needs_review_count"], utc_now_iso(), "\n".join(result["errors"][:100]),
                json.dumps({"needs_ocr_count": result["needs_ocr_count"], "paper_count": result["paper_count"], "section_count": result["section_count"], "chunk_count": result["chunk_count"], "candidate_count": result["candidate_count"]}, ensure_ascii=False),
                result["job_id"],
            ),
        )
        conn.commit()
