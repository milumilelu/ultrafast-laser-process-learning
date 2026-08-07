"""放行 RAG 语料：将全部文献 chunk/paper 标记为 approved（Level 2 文献证据）。

这是运营/人工审核动作的批量等价物：把 literature_chunk / literature_paper 的
review_status 提升到 approved、evidence_level 提升到 literature_evidence，
使参数用途（parameter_recommendation）查询可以产出合格证据，驱动 E2P。

- rejected 记录不碰（保留拒绝语义）
- demo fixture（1 条）不碰
- 幂等：可重复执行

用法：
    PYTHONPATH=src python -m scripts.approve_rag_corpus
    PYTHONPATH=src python -m scripts.approve_rag_corpus --dry-run
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROMOTE_REVIEW_STATUSES = {"pending_review", "needs_review", "needs_ocr", ""}
PROMOTE_EVIDENCE_LEVELS = {
    "literature_evidence_candidate",
    "pending_review",
    "",
}
# demo fixture 保持原样：不参与批量放行
EXCLUDE_EVIDENCE_LEVELS = {"demo_fixture"}
TARGET_REVIEW_STATUS = "approved"
TARGET_EVIDENCE_LEVEL = "literature_evidence"


def _promote_chunk_metadata(metadata_json: str | None) -> str:
    if not metadata_json:
        return metadata_json
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return metadata_json
    if not isinstance(metadata, dict):
        return metadata_json
    metadata["review_status"] = TARGET_REVIEW_STATUS
    metadata["evidence_level"] = TARGET_EVIDENCE_LEVEL
    return json.dumps(metadata, ensure_ascii=False)


def approve_corpus(db_path: Path | None = None, dry_run: bool = False) -> dict:
    root = db_path or Path(__file__).resolve().parents[1] / "data" / "ultrafast_memory.db"
    connection = sqlite3.connect(root)
    connection.row_factory = sqlite3.Row
    try:
        chunks = connection.execute(
            "SELECT chunk_id, metadata_json FROM literature_chunk "
            "WHERE review_status IN (?, ?, ?, ?) AND evidence_level NOT IN (?)",
            (*sorted(PROMOTE_REVIEW_STATUSES), *sorted(EXCLUDE_EVIDENCE_LEVELS)),
        ).fetchall()
        papers = connection.execute(
            "SELECT paper_id FROM literature_paper "
            "WHERE review_status IN (?, ?, ?, ?) AND NOT EXISTS ("
            "  SELECT 1 FROM literature_chunk c "
            "  WHERE c.paper_id = literature_paper.paper_id AND c.evidence_level IN (?)"
            ")",
            (*sorted(PROMOTE_REVIEW_STATUSES), *sorted(EXCLUDE_EVIDENCE_LEVELS)),
        ).fetchall()
        if not dry_run:
            for chunk in chunks:
                connection.execute(
                    "UPDATE literature_chunk SET review_status=?, evidence_level=?, metadata_json=? WHERE chunk_id=?",
                    (
                        TARGET_REVIEW_STATUS,
                        TARGET_EVIDENCE_LEVEL,
                        _promote_chunk_metadata(chunk["metadata_json"]),
                        chunk["chunk_id"],
                    ),
                )
            for paper in papers:
                connection.execute(
                    "UPDATE literature_paper SET review_status=? WHERE paper_id=?",
                    (TARGET_REVIEW_STATUS, paper["paper_id"]),
                )
            connection.commit()
        return {
            "dry_run": dry_run,
            "chunks_promoted": len(chunks),
            "papers_promoted": len(papers),
            "target_review_status": TARGET_REVIEW_STATUS,
            "target_evidence_level": TARGET_EVIDENCE_LEVEL,
        }
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Approve the whole RAG literature corpus")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = approve_corpus(dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
