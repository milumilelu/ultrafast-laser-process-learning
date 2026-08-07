from __future__ import annotations

import json

from ultrafast_knowledge.literature.metadata_backfill import backfill_metadata
from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection


class _FakeClient:
    def chat(self, messages: list[dict], **kwargs: object) -> dict:
        return {
            "content": json.dumps(
                {
                    "material_roles": {"0": "primary_workpiece"},
                    "process_roles": {"M0": "primary_process"},
                    "laser_type": "fs",
                    "wavelength_nm": 1030,
                    "pulse_width": None,
                    "material_grade": {},
                    "geometry": "plate",
                }
            )
        }


def _insert_paper_and_section(paper_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO literature_paper
            (paper_id,canonical_title,primary_material,metadata_extraction_status,
             metadata_extractor_version,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (paper_id, f"Title {paper_id}", '["legacy"]', None, "metadata-extractor-v1", "t", "t"),
        )
        conn.execute(
            """
            INSERT INTO literature_section
            (section_id,paper_id,artifact_id,section_type,section_title,page_start,
             page_end,text,text_hash,parser_version,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"section-{paper_id}",
                paper_id,
                None,
                "abstract",
                "Abstract",
                1,
                1,
                "Diamond plate laser micromachining.",
                f"hash-{paper_id}",
                "test",
                "t",
            ),
        )


def test_backfill_is_dry_run_resumable_and_preserves_snapshot(
    memory_root,
    tmp_path,
) -> None:
    init_database()
    _insert_paper_and_section("paper-a")
    _insert_paper_and_section("paper-b")
    checkpoint = tmp_path / "backfill-checkpoint.json"

    dry = backfill_metadata(batch_size=1, dry_run=True, llm_client=_FakeClient())
    assert dry["dry_run_paper_ids"] == ["paper-a"]
    with get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM literature_metadata_backfill").fetchone()[0] == 0

    first = backfill_metadata(
        batch_size=1,
        checkpoint_path=checkpoint,
        rebuild_chunks=True,
        llm_client=_FakeClient(),
    )
    second = backfill_metadata(
        batch_size=1,
        resume_from=checkpoint,
        checkpoint_path=checkpoint,
        rebuild_chunks=True,
        llm_client=_FakeClient(),
    )

    assert first["success"] == 1
    assert first["processed_count"] == 1
    assert second["success"] == 1
    assert second["processed_count"] == 1
    assert first["next_resume_from"] == "paper-a"
    assert second["next_resume_from"] == "paper-b"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT paper_id,previous_metadata_json,status FROM literature_metadata_backfill "
            "ORDER BY paper_id"
        ).fetchall()
        assert [row["paper_id"] for row in rows] == ["paper-a", "paper-b"]
        assert all(row["status"] == "success" for row in rows)
        assert json.loads(rows[0]["previous_metadata_json"])["primary_material"] == '["legacy"]'
        assert conn.execute("SELECT count(*) FROM literature_chunk").fetchone()[0] == 2

    again = backfill_metadata(batch_size=10, llm_client=_FakeClient())
    assert again["selected_count"] == 0
    assert again["processed_count"] == 0


def test_backfill_reindex_runs_only_after_chunk_commit(memory_root) -> None:
    init_database()
    _insert_paper_and_section("paper-reindex")

    result = backfill_metadata(
        batch_size=1,
        rebuild_chunks=True,
        reindex=True,
        llm_client=_FakeClient(),
    )

    assert result["success"] == 1
    assert result["reindex_result"] is not None
    assert result["reindex_result"]["active_chunk_count"] == 1
    with get_connection() as conn:
        chunk_count = conn.execute("SELECT count(*) FROM literature_chunk").fetchone()[0]
        entry_count = conn.execute("SELECT count(*) FROM rag_index_entry").fetchone()[0]
    assert chunk_count == 1
    assert entry_count == 1
