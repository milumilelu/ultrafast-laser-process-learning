from __future__ import annotations

from ultrafast_knowledge.literature.extraction.extractor import extract_paper_metadata
from ultrafast_knowledge.literature.schemas import LiteratureSectionData
from ultrafast_knowledge.literature.service import _persist_extraction, get_paper
from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection


def _section(section_id: str, section_type: str, text: str, page: int = 1) -> LiteratureSectionData:
    return LiteratureSectionData(
        section_id=section_id,
        paper_id="paper-storage-1",
        artifact_id=None,
        section_type=section_type,
        section_title="",
        page_start=page,
        page_end=page,
        text=text,
        text_hash=f"hash-{section_id}",
        parser_version="test",
    )


def test_persist_extraction_writes_paper_columns_and_mentions(memory_root) -> None:
    init_database()
    paper = {
        "paper_id": "paper-storage-1",
        "canonical_title": "Diamond lens",
    }
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO literature_paper (paper_id, canonical_title, created_at, updated_at) VALUES (?,?,?,?)",
            (paper["paper_id"], paper["canonical_title"], "t", "t"),
        )
        conn.commit()

    sections = [
        _section("s1", "abstract", "Single crystal diamond refractive lenses were manufactured by femtosecond laser micromachining of diamond."),
    ]
    metadata = extract_paper_metadata(paper["paper_id"], sections, llm_client=None, page_count=1)

    with get_connection() as conn:
        _persist_extraction(conn, paper, metadata)
        conn.commit()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT primary_material, primary_process, metadata_extraction_status, metadata_extractor_version FROM literature_paper WHERE paper_id=?",
            (paper["paper_id"],),
        ).fetchone()
        assert row["metadata_extraction_status"] == "rule_only_abstained"
        assert row["metadata_extractor_version"]
        assert row["primary_material"] == "[]"
        mentions = conn.execute(
            "SELECT kind, canonical_id, role, extraction_method FROM literature_mention WHERE paper_id=?",
            (paper["paper_id"],),
        ).fetchall()
        assert any(m["kind"] == "material" and m["canonical_id"] == "Diamond" for m in mentions)
        assert any(m["kind"] == "process" and m["canonical_id"] == "micromachining" for m in mentions)
        assert all(m["extraction_method"] == "rule" for m in mentions)

    detail = get_paper(paper["paper_id"])
    assert detail["mentions"]
    assert detail["mentions"][0]["paper_id"] == paper["paper_id"]


def test_persist_extraction_idempotent(memory_root) -> None:
    init_database()
    paper = {
        "paper_id": "paper-storage-2",
        "canonical_title": "TBC drilling",
    }
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO literature_paper (paper_id, canonical_title, created_at, updated_at) VALUES (?,?,?,?)",
            (paper["paper_id"], paper["canonical_title"], "t", "t"),
        )
        conn.commit()
    sections = [
        _section("s1", "abstract", "Laser drilling of thermal barrier coated nickel superalloy."),
    ]
    metadata = extract_paper_metadata(paper["paper_id"], sections, llm_client=None, page_count=1)
    with get_connection() as conn:
        _persist_extraction(conn, paper, metadata)
        _persist_extraction(conn, paper, metadata)
        conn.commit()
    with get_connection() as conn:
        count = conn.execute(
            "SELECT count(*) AS n FROM literature_mention WHERE paper_id=?",
            (paper["paper_id"],),
        ).fetchone()["n"]
        assert count == len(metadata.material_mentions) + len(metadata.process_mentions)


def test_mention_ids_include_page_section_and_span(memory_root) -> None:
    init_database()
    paper = {"paper_id": "paper-storage-pages", "canonical_title": "Repeated diamond"}
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO literature_paper (paper_id, canonical_title, created_at, updated_at) "
            "VALUES (?,?,?,?)",
            (paper["paper_id"], paper["canonical_title"], "t", "t"),
        )
    sections = [
        _section("page-1", "methods", "Diamond and diamond.", page=1),
        _section("page-2", "results", "Diamond.", page=2),
    ]
    metadata = extract_paper_metadata(paper["paper_id"], sections, llm_client=None, page_count=2)
    with get_connection() as conn:
        _persist_extraction(conn, paper, metadata)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT mention_id,page,section_id,evidence_span
            FROM literature_mention
            WHERE paper_id=? AND canonical_id='Diamond'
            ORDER BY page,evidence_span
            """,
            (paper["paper_id"],),
        ).fetchall()
    assert len(rows) == 3
    assert len({row["mention_id"] for row in rows}) == 3
    assert {row["page"] for row in rows} == {1, 2}
    assert {row["section_id"] for row in rows} == {"page-1", "page-2"}
