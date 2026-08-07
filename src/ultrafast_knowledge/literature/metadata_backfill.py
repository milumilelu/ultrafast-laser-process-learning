"""Resumable metadata enrichment backfill.

Run with::

    python -m ultrafast_knowledge.literature.metadata_backfill --dry-run
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from ultrafast_knowledge.literature.chunk_builder import build_chunks
from ultrafast_knowledge.literature.extraction import (
    EXTRACTION_VERSION,
    ExtractionStatus,
)
from ultrafast_knowledge.literature.extraction.extractor import (
    build_extraction_llm_client,
    extract_paper_metadata,
)
from ultrafast_knowledge.literature.service import (
    _insert_chunk,
    _load_paper_sections,
    _paper_for_chunk,
    _persist_extraction,
)
from ultrafast_memory.core.config import load_config
from ultrafast_memory.core.ids import stable_id
from ultrafast_memory.core.time_utils import utc_now_iso
from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection

_AUTO_LLM = object()


def backfill_metadata(
    *,
    extractor_version: str = EXTRACTION_VERSION,
    batch_size: int = 25,
    resume_from: str | Path | None = None,
    dry_run: bool = False,
    rebuild_chunks: bool = False,
    reindex: bool = False,
    index_name: str = "literature_default",
    checkpoint_path: str | Path | None = None,
    llm_client: Any = _AUTO_LLM,
) -> dict[str, Any]:
    """Backfill one deterministic paper-id batch and return its next checkpoint."""
    target_version = _normalize_version(extractor_version)
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if target_version != EXTRACTION_VERSION:
        raise ValueError(
            f"this runtime can only produce {EXTRACTION_VERSION}, requested {target_version}"
        )
    if reindex and not rebuild_chunks:
        raise ValueError("--reindex requires --rebuild-chunks so indexed metadata cannot be stale")

    init_database()
    resume_token = _resolve_resume_token(resume_from, target_version)
    rows = _select_batch(target_version, resume_token, batch_size + 1)
    selected = rows[:batch_size]
    has_more = len(rows) > batch_size
    run_id = stable_id("metadata_backfill", target_version, utc_now_iso(), uuid.uuid4().hex)
    result: dict[str, Any] = {
        "run_id": run_id,
        "extractor_version": target_version,
        "dry_run": dry_run,
        "batch_size": batch_size,
        "resume_from": resume_token,
        "selected_count": len(selected),
        "success": 0,
        "abstain": 0,
        "needs_ocr": 0,
        "failed": 0,
        "processed_count": 0,
        "failures": [],
        "rebuild_chunks": rebuild_chunks,
        "reindex": reindex,
        "reindex_result": None,
        "has_more": has_more,
        "next_resume_from": selected[-1]["paper_id"] if selected else resume_token,
    }
    if dry_run:
        result["dry_run_paper_ids"] = [row["paper_id"] for row in selected]
        _write_checkpoint(checkpoint_path, result)
        return result

    client = build_extraction_llm_client() if llm_client is _AUTO_LLM else llm_client
    for selected_row in selected:
        paper_id = selected_row["paper_id"]
        started_at = utc_now_iso()
        stage = "load_sections"
        previous: dict[str, Any] = {}
        try:
            with get_connection() as conn:
                paper_row = conn.execute(
                    "SELECT * FROM literature_paper WHERE paper_id=?",
                    (paper_id,),
                ).fetchone()
                if paper_row is None:
                    raise RuntimeError("paper disappeared after batch selection")
                paper = dict(paper_row)
                previous = _metadata_snapshot(conn, paper)
                sections = _load_paper_sections(conn, paper_id)
                if not sections:
                    retryable_ocr = _ocr_retryable_state(conn, paper_id)
                    if retryable_ocr is not None:
                        _upsert_ledger(
                            conn,
                            extractor_version=target_version,
                            paper_id=paper_id,
                            run_id=run_id,
                            status="needs_ocr",
                            stage="needs_ocr",
                            previous=previous,
                            error_type="OcrRequired",
                            error_message=retryable_ocr,
                            started_at=started_at,
                        )
                        result["needs_ocr"] += 1
                        continue

                stage = "extract_metadata"
                metadata = extract_paper_metadata(
                    paper_id,
                    sections,
                    page_count=max((section.page_end for section in sections), default=1),
                    llm_client=client if sections else None,
                    paper_title=paper.get("canonical_title") or "",
                )
                if not sections:
                    metadata.warnings.append(
                        "no stored full text; structured metadata remains an unverified candidate"
                    )
                stage = "persist_metadata"
                _persist_extraction(conn, paper, metadata)
                status = (
                    "success"
                    if metadata.extraction_status
                    == ExtractionStatus.EXTRACTED_WITH_LLM.value
                    else "abstain"
                )
                if rebuild_chunks:
                    stage = "rebuild_chunks"
                    _rebuild_paper_chunks(conn, paper, metadata, sections)
                _upsert_ledger(
                    conn,
                    extractor_version=target_version,
                    paper_id=paper_id,
                    run_id=run_id,
                    status=status,
                    stage="complete",
                    previous=previous,
                    started_at=started_at,
                )
            result[status] += 1
        except Exception as exc:  # noqa: BLE001 - continue and persist retry evidence
            result["failed"] += 1
            failure = {
                "paper_id": paper_id,
                "stage": stage,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
            result["failures"].append(failure)
            with get_connection() as conn:
                _upsert_ledger(
                    conn,
                    extractor_version=target_version,
                    paper_id=paper_id,
                    run_id=run_id,
                    status="failed",
                    stage=stage,
                    previous=previous,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    started_at=started_at,
                )

    if reindex and (result["success"] or result["abstain"]):
        # Indexing is intentionally phase two.  All per-paper SQLite transactions
        # have committed before embeddings or lexical indexes are touched.
        from ultrafast_knowledge.rag.index_service import ensure_index, index_pending_chunks

        index = ensure_index(index_name)
        result["reindex_result"] = index_pending_chunks(index["index_id"])
    result["processed_count"] = sum(
        result[key] for key in ("success", "abstain", "needs_ocr", "failed")
    )
    _write_checkpoint(checkpoint_path, result)
    return result


def _select_batch(version: str, resume_token: str, limit: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.paper_id
            FROM literature_paper p
            LEFT JOIN literature_metadata_backfill b
              ON b.paper_id=p.paper_id AND b.extractor_version=?
            WHERE p.paper_id > ?
              AND (
                coalesce(p.metadata_extractor_version, '') <> ?
                OR p.metadata_extraction_status='failed'
              )
              AND (b.status IS NULL OR b.status NOT IN ('success','abstain'))
            ORDER BY p.paper_id
            LIMIT ?
            """,
            (version, resume_token, version, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _metadata_snapshot(conn, paper: dict[str, Any]) -> dict[str, Any]:
    mentions = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM literature_mention WHERE paper_id=? ORDER BY mention_id",
            (paper["paper_id"],),
        ).fetchall()
    ]
    return {
        key: paper.get(key)
        for key in (
            "primary_material",
            "primary_material_grade",
            "primary_process",
            "metadata_extraction_status",
            "metadata_extractor_version",
        )
    } | {"mentions": mentions}


def _ocr_retryable_state(conn, paper_id: str) -> str | None:
    rows = conn.execute(
        """
        SELECT a.parse_status,a.error_message
        FROM literature_artifact a
        JOIN literature_paper_source s ON s.artifact_id=a.artifact_id
        WHERE s.paper_id=? AND a.asset_type='raw_pdf'
        """,
        (paper_id,),
    ).fetchall()
    for row in rows:
        if row["parse_status"] in {"needs_ocr", "ocr_retryable"}:
            return str(row["error_message"] or row["parse_status"])
    return None


def _rebuild_paper_chunks(conn, paper: dict[str, Any], metadata, sections) -> None:
    chunk_config = load_config().get("rag", {}).get("chunking", {})
    conn.execute(
        "DELETE FROM rag_index_entry WHERE chunk_id IN "
        "(SELECT chunk_id FROM literature_chunk WHERE paper_id=?)",
        (paper["paper_id"],),
    )
    conn.execute("DELETE FROM literature_chunk WHERE paper_id=?", (paper["paper_id"],))
    paper["primary_material"] = json.dumps(metadata.primary_material, ensure_ascii=False)
    paper["primary_material_grade"] = json.dumps(
        metadata.primary_material_grade,
        ensure_ascii=False,
    )
    paper["primary_process"] = metadata.primary_process
    paper["material_roles"] = json.dumps(metadata.mention_roles(), ensure_ascii=False)
    paper["process_roles"] = json.dumps(metadata.process_roles(), ensure_ascii=False)
    chunks = build_chunks(
        _paper_for_chunk(paper),
        sections,
        target_tokens=int(chunk_config.get("target_tokens", 450)),
        min_tokens=int(chunk_config.get("min_tokens", 120)),
        max_tokens=int(chunk_config.get("max_tokens", 700)),
        overlap_tokens=int(chunk_config.get("overlap_tokens", 80)),
        include_references=bool(
            load_config().get("literature", {}).get("include_references_section", False)
        ),
    )
    for chunk in chunks:
        _insert_chunk(conn, chunk, ignore_existing=False)


def _upsert_ledger(
    conn,
    *,
    extractor_version: str,
    paper_id: str,
    run_id: str,
    status: str,
    stage: str,
    previous: dict[str, Any],
    started_at: str,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO literature_metadata_backfill
        (extractor_version,paper_id,run_id,status,stage,previous_metadata_json,
         error_type,error_message,started_at,finished_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(extractor_version,paper_id) DO UPDATE SET
          run_id=excluded.run_id,status=excluded.status,stage=excluded.stage,
          previous_metadata_json=CASE
            WHEN literature_metadata_backfill.previous_metadata_json IS NULL
            THEN excluded.previous_metadata_json
            ELSE literature_metadata_backfill.previous_metadata_json END,
          error_type=excluded.error_type,error_message=excluded.error_message,
          started_at=excluded.started_at,finished_at=excluded.finished_at
        """,
        (
            extractor_version,
            paper_id,
            run_id,
            status,
            stage,
            json.dumps(previous, ensure_ascii=False),
            error_type,
            error_message,
            started_at,
            utc_now_iso(),
        ),
    )


def _normalize_version(version: str) -> str:
    normalized = str(version).strip()
    if normalized == "v2":
        return EXTRACTION_VERSION
    return normalized


def _resolve_resume_token(value: str | Path | None, version: str) -> str:
    if value is None:
        return ""
    path = Path(value)
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("extractor_version") != version:
            raise ValueError("checkpoint extractor_version does not match requested version")
        return str(payload.get("next_resume_from") or "")
    return str(value)


def _write_checkpoint(path: str | Path | None, result: dict[str, Any]) -> None:
    if path is None:
        return
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resumable literature metadata backfill")
    parser.add_argument("--extractor-version", default=EXTRACTION_VERSION)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--resume-from")
    parser.add_argument("--checkpoint")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild-chunks", action="store_true")
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--index-name", default="literature_default")
    args = parser.parse_args(argv)
    result = backfill_metadata(
        extractor_version=args.extractor_version,
        batch_size=args.batch_size,
        resume_from=args.resume_from,
        checkpoint_path=args.checkpoint,
        dry_run=args.dry_run,
        rebuild_chunks=args.rebuild_chunks,
        reindex=args.reindex,
        index_name=args.index_name,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
