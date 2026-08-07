from __future__ import annotations

import json
from pathlib import Path

from ultrafast_domain.documents import DocumentElement, OcrDocument
from ultrafast_knowledge.literature.inventory import sha256_path
from ultrafast_knowledge.literature.schemas import PageText, ParsedPdf
from ultrafast_knowledge.literature.service import _recover_needs_ocr, ingest_literature
from ultrafast_memory.core.ids import stable_id
from ultrafast_memory.core.time_utils import utc_now_iso
from ultrafast_memory.db.session import get_connection


class _FakeClient:
    def chat(self, messages: list[dict], **kwargs: object) -> dict:
        return {
            "content": json.dumps(
                {
                    "material_roles": {"0": "primary_workpiece", "1": "primary_workpiece"},
                    "process_roles": {"M0": "primary_process"},
                    "laser_type": "fs",
                    "wavelength_nm": 1030,
                    "pulse_width": {"value": 300, "unit": "fs", "evidence": "300 fs"},
                    "material_grade": {"Diamond": "single crystal"},
                    "geometry": "lens",
                }
            )
        }


def _parsed(path: Path, *, status: str = "parsed") -> ParsedPdf:
    sha = sha256_path(path)
    now = utc_now_iso()
    return ParsedPdf(
        artifact={
            "artifact_id": stable_id("lart", sha, "raw_pdf"),
            "original_path": str(path),
            "archived_path": str(path),
            "asset_type": "raw_pdf",
            "sha256": sha,
            "file_size_bytes": path.stat().st_size,
            "parent_root": str(path.parent),
            "parse_status": status,
            "parser_name": "fake-parser",
            "parser_version": "test",
            "error_message": "scan requires OCR" if status == "needs_ocr" else "",
            "discovered_at": now,
            "imported_at": now,
        },
        metadata={
            "title": "Femtosecond machining of diamond lenses",
            "authors": "A. Researcher",
            "year": "2025",
            "doi": "10.1000/test-ingestion",
            "source": "Test Journal",
        },
        pages=[
            PageText(
                page_number=1,
                text=(
                    "Abstract\nSingle crystal diamond lenses were manufactured by "
                    "femtosecond laser micromachining at 1030 nm and 300 fs."
                ),
            ),
            PageText(
                page_number=2,
                text="Methods\nDiamond was machined again and inspected.",
            ),
        ],
        page_count=2,
        average_chars_per_page=100,
        parse_status=status,
        error_message="scan requires OCR" if status == "needs_ocr" else "",
    )


def test_new_pdf_runs_full_enrichment_and_chunk_chain(
    memory_root,
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"fake-pdf")
    parsed = _parsed(pdf)
    monkeypatch.setattr(
        "ultrafast_knowledge.literature.service.parse_pdf",
        lambda path, archive: parsed,
    )
    monkeypatch.setattr(
        "ultrafast_knowledge.literature.service.build_extraction_llm_client",
        lambda: _FakeClient(),
    )

    result = ingest_literature(str(tmp_path), mode="raw_pdf_only")

    assert result["status"] == "completed"
    assert result["paper_count"] == 1
    assert result["metadata_enrichment"]["extracted_with_llm"] == 1
    assert result["section_count"] >= 1
    assert result["chunk_count"] >= 1
    with get_connection() as conn:
        paper = dict(conn.execute("SELECT * FROM literature_paper").fetchone())
        assert paper["metadata_extraction_status"] == "extracted_with_llm"
        assert paper["primary_material"] == '["Diamond"]'
        assert conn.execute("SELECT count(*) FROM literature_mention").fetchone()[0] >= 3
        assert conn.execute("SELECT count(*) FROM literature_chunk").fetchone()[0] >= 1


def test_structured_card_without_body_uses_explicit_abstention(
    memory_root,
    tmp_path,
    monkeypatch,
) -> None:
    card = {
        "paper_id": "structured-source-id",
        "title": "Structured candidate without full text",
        "year": "2024",
        "material": "diamond",
        "process_type": "micromachining",
    }
    (tmp_path / "literature_cards.jsonl").write_text(
        json.dumps(card) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ultrafast_knowledge.literature.service.build_extraction_llm_client",
        lambda: _FakeClient(),
    )

    result = ingest_literature(str(tmp_path), mode="structured_only")

    assert result["paper_count"] == 1
    assert result["metadata_enrichment"]["rule_only_abstained"] == 1
    with get_connection() as conn:
        paper = conn.execute("SELECT * FROM literature_paper").fetchone()
        assert paper["metadata_extraction_status"] == "rule_only_abstained"
        assert paper["primary_material"] == "[]"
        assert conn.execute("SELECT count(*) FROM literature_mention").fetchone()[0] == 0


def test_ingestion_failure_reports_stage_and_rolls_back_paper(
    memory_root,
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "broken-stage.pdf"
    pdf.write_bytes(b"fake-pdf")
    monkeypatch.setattr(
        "ultrafast_knowledge.literature.service.parse_pdf",
        lambda path, archive: _parsed(pdf),
    )
    monkeypatch.setattr(
        "ultrafast_knowledge.literature.service.build_chunks",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("chunk failure")),
    )

    result = ingest_literature(str(tmp_path), mode="raw_pdf_only")

    assert result["failed_count"] == 1
    assert result["failures"][0]["stage"] == "build_chunks"
    assert result["paper_count"] == 0
    assert result["section_count"] == 0
    assert result["chunk_count"] == 0
    with get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM literature_paper").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM literature_artifact").fetchone()[0] == 0


def test_needs_ocr_failure_is_persisted_and_retried(
    memory_root,
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"fake-scan")
    calls = {"ocr": 0}

    monkeypatch.setattr(
        "ultrafast_knowledge.literature.service.parse_pdf",
        lambda path, archive: _parsed(pdf, status="needs_ocr"),
    )

    def unavailable(parsed):
        calls["ocr"] += 1
        raise RuntimeError("PaddleOCR provider is unavailable")

    monkeypatch.setattr(
        "ultrafast_knowledge.literature.service._recover_needs_ocr",
        unavailable,
    )

    first = ingest_literature(str(tmp_path), mode="raw_pdf_only")
    second = ingest_literature(str(tmp_path), mode="raw_pdf_only")

    assert first["failures"][0]["stage"] == "ocr"
    assert second["skipped_count"] == 0
    assert calls["ocr"] == 2
    with get_connection() as conn:
        artifact = conn.execute(
            "SELECT parse_status,error_message FROM literature_artifact"
        ).fetchone()
        assert artifact["parse_status"] == "ocr_retryable"
        assert "stage=ocr" in artifact["error_message"]


def test_needs_ocr_uses_available_provider_and_returns_page_text(
    memory_root,
    tmp_path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "ocr-success.pdf"
    pdf.write_bytes(b"fake-scan")
    parsed = _parsed(pdf, status="needs_ocr")
    source_hash = parsed.artifact["sha256"]
    document = OcrDocument(
        document_id="ocr-document-test",
        artifact_id=parsed.artifact["artifact_id"],
        parser_name="paddleocr",
        parser_version="test",
        source_hash=source_hash,
        elements=(
            DocumentElement(
                document_id="ocr-document-test",
                page_number=1,
                element_id="element-1",
                element_type="paragraph",
                content="Diamond laser micromachining by a 300 fs source.",
                bbox=None,
                confidence=0.99,
                parser_name="paddleocr",
                parser_version="test",
                source_image_hash=source_hash,
            ),
        ),
    )

    class _Provider:
        def __init__(self, **kwargs: object) -> None:
            pass

        def parse(self, artifact: dict) -> OcrDocument:
            return document

    monkeypatch.setattr("ultrafast_integrations.ocr.PaddleOcrProvider", _Provider)

    recovered = _recover_needs_ocr(parsed)

    assert recovered.parse_status == "parsed_with_ocr"
    assert recovered.pages[0].page_number == 1
    assert "Diamond" in recovered.pages[0].text
    with get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM ocr_document").fetchone()[0] == 1
