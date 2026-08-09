"""Load candidate PDFs after metadata-level paper retrieval."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ultrafast_ingestion.parsers.pymupdf_parser import PyMuPDFDocumentParser
from ultrafast_knowledge.evidence_pipeline.blocks import SemanticBlockBuilder
from ultrafast_knowledge.evidence_pipeline.query import RequirementQueryCompiler
from ultrafast_knowledge.evidence_pipeline.retrieval import TwoLevelEvidenceRetriever
from ultrafast_knowledge.evidence_pipeline.schemas import StructuredScientificPaper
from ultrafast_memory.core.config import get_project_root, load_config
from ultrafast_memory.db.session import get_connection
from ultrafast_requirements.schemas import Requirement


class DatabaseScientificPaperRepository:
    """Stage 1 reads title/abstract/metadata; PDF parsing starts only after ranking."""

    def __init__(self, *, connection: Any = None, root: Path | None = None) -> None:
        self.connection = connection or get_connection
        self.root = Path(root or get_project_root()).resolve()
        self.parser = PyMuPDFDocumentParser()
        self.block_builder = SemanticBlockBuilder()
        self.retriever = TwoLevelEvidenceRetriever()
        self.query_compiler = RequirementQueryCompiler()
        self._file_index: dict[str, Path] | None = None

    def load_for_requirement(
        self,
        requirement: Requirement,
        *,
        top_k: int = 5,
    ) -> tuple[list[StructuredScientificPaper], list[str]]:
        rows = self._metadata_rows()
        proxies = [self._proxy(row) for row in rows]
        query = self.query_compiler.compile(requirement)
        candidates = self.retriever.retrieve_papers(query, proxies, top_k=top_k)
        row_by_id = {str(row["paper_id"]): row for row in rows}
        papers: list[StructuredScientificPaper] = []
        warnings: list[str] = []
        for candidate in candidates:
            row = row_by_id[candidate.paper_id]
            pdf_path = self._resolve_pdf(row)
            if pdf_path is None:
                warnings.append(f"pdf_not_found:{candidate.paper_id}")
                continue
            try:
                document = self.parser.parse(pdf_path)
            except Exception as exc:  # noqa: BLE001 - one malformed PDF must not hide other papers
                warnings.append(f"pdf_parse_failed:{candidate.paper_id}:{type(exc).__name__}")
                continue
            metadata = self._metadata(row)
            # DB paper_id is canonical across file renames; semantic provenance
            # retains the parser's document version and native block ids.
            paper = self.block_builder.build(
                document,
                title=str(row.get("canonical_title") or ""),
                metadata=metadata,
            )
            papers.append(paper.model_copy(update={"metadata": {**metadata, "canonical_paper_id": candidate.paper_id}}))
        return papers, warnings

    def _metadata_rows(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT p.*,
                       a.original_path AS artifact_original_path,
                       a.archived_path AS artifact_archived_path,
                       (SELECT s.text FROM literature_section s
                        WHERE s.paper_id=p.paper_id AND lower(s.section_type)='abstract'
                        ORDER BY s.page_start, s.section_id LIMIT 1) AS abstract_text
                FROM literature_paper p
                LEFT JOIN literature_artifact a ON a.artifact_id=p.canonical_artifact_id
                WHERE coalesce(p.review_status, '') != 'rejected'
                """
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _proxy(row: dict[str, Any]) -> StructuredScientificPaper:
        return StructuredScientificPaper(
            paper_id=str(row["paper_id"]),
            document_version_id="metadata-only",
            title=str(row.get("canonical_title") or ""),
            abstract=str(row.get("abstract_text") or ""),
            metadata=DatabaseScientificPaperRepository._metadata(row),
        )

    @staticmethod
    def _metadata(row: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "authors",
            "year",
            "doi",
            "material",
            "material_grade",
            "process_type",
            "laser_type",
            "wavelength_nm",
            "pulse_width_fs",
            "power_or_energy",
            "frequency_kHz",
            "scan_speed_mm_s",
            "beam_shape",
            "environment",
        )
        return {key: row[key] for key in keys if row.get(key) not in (None, "")}

    def _resolve_pdf(self, row: dict[str, Any]) -> Path | None:
        raw_paths = [
            row.get("artifact_archived_path"),
            row.get("artifact_original_path"),
        ]
        for raw in raw_paths:
            if not raw:
                continue
            path = Path(str(raw))
            if path.is_file():
                return path.resolve()
        if self._file_index is None:
            self._file_index = self._build_file_index()
        for raw in raw_paths:
            if raw:
                found = self._file_index.get(Path(str(raw)).name.lower())
                if found is not None:
                    return found
        return None

    def _build_file_index(self) -> dict[str, Path]:
        config = load_config(self.root)
        literature = config.get("literature") or {}
        roots = [
            self.root / str(literature.get("archive_dir") or "data/literature_archive"),
            self.root / "artifacts" / "b1_annotation" / "papers",
            self.root / "artifacts" / "cfa_holdout" / "papers",
            self.root / "artifacts" / "cfa_holdout" / "papers_v2",
        ]
        output: dict[str, Path] = {}
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*.pdf"):
                output.setdefault(path.name.lower(), path.resolve())
        return output
