"""Persistent scientific document, semantic block, index and knowledge store."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from ultrafast_knowledge.evidence_pipeline.schemas import (
    ExtractionStatus,
    RequirementEvidence,
    SemanticBlock,
    StructuredScientificPaper,
)
from ultrafast_memory.db.session import get_connection
from ultrafast_requirements.schemas import Requirement

SCHEMA_VERSION = "scientific-index-store-v1"


class ScientificIndexStore:
    def __init__(self, connection: Any = None) -> None:
        if connection is None:
            self.connection = get_connection
        elif callable(connection):
            self.connection = connection
        else:
            @contextmanager
            def existing_connection() -> Any:
                yield connection

            self.connection = existing_connection
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS scientific_document_store (
                    document_version_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    pdf_path TEXT,
                    title TEXT,
                    abstract TEXT,
                    retrieval_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scientific_document_paper
                ON scientific_document_store(paper_id);

                CREATE TABLE IF NOT EXISTS scientific_semantic_block_store (
                    block_id TEXT PRIMARY KEY,
                    document_version_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    block_type TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    pdf_page_index INTEGER NOT NULL,
                    section_id TEXT,
                    section_path TEXT,
                    section_type TEXT,
                    section_title TEXT,
                    table_id TEXT,
                    raw_text TEXT NOT NULL,
                    retrieval_text TEXT NOT NULL,
                    bbox_json TEXT,
                    previous_block_id TEXT,
                    next_block_id TEXT,
                    related_block_ids_json TEXT NOT NULL,
                    source_text_type TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scientific_block_paper
                ON scientific_semantic_block_store(paper_id, pdf_page_index);
                CREATE INDEX IF NOT EXISTS idx_scientific_block_document
                ON scientific_semantic_block_store(document_version_id);

                CREATE TABLE IF NOT EXISTS scientific_hybrid_index_state (
                    index_name TEXT PRIMARY KEY,
                    revision TEXT NOT NULL,
                    encoder_name TEXT NOT NULL,
                    encoder_model_json TEXT NOT NULL,
                    item_count INTEGER NOT NULL,
                    schema_version TEXT NOT NULL,
                    built_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scientific_hybrid_index_vector (
                    index_name TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    document_version_id TEXT NOT NULL,
                    block_id TEXT,
                    vector_json TEXT NOT NULL,
                    PRIMARY KEY(index_name, revision, item_id)
                );
                CREATE INDEX IF NOT EXISTS idx_scientific_vector_paper
                ON scientific_hybrid_index_vector(index_name, revision, paper_id);

                CREATE TABLE IF NOT EXISTS structured_scientific_knowledge (
                    knowledge_id TEXT PRIMARY KEY,
                    requirement_signature TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    document_version_id TEXT NOT NULL,
                    extraction_status TEXT NOT NULL,
                    value REAL,
                    lower REAL,
                    upper REAL,
                    unit TEXT,
                    conditions_json TEXT NOT NULL,
                    semantic_role TEXT,
                    source_block_refs_json TEXT NOT NULL,
                    evidence_quote TEXT,
                    confidence REAL NOT NULL,
                    validation_state TEXT NOT NULL,
                    governance_status TEXT NOT NULL,
                    extractor_model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    extraction_schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(requirement_signature, paper_id, document_version_id,
                           extractor_model, prompt_version, extraction_schema_version)
                );
                CREATE INDEX IF NOT EXISTS idx_structured_knowledge_quantity
                ON structured_scientific_knowledge(quantity, extraction_status);
                """
            )
            conn.commit()

    def upsert_paper(self, paper: StructuredScientificPaper) -> None:
        now = _now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO scientific_document_store
                (document_version_id,paper_id,pdf_path,title,abstract,retrieval_text,
                 metadata_json,schema_version,indexed_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(document_version_id) DO UPDATE SET
                  paper_id=excluded.paper_id,pdf_path=excluded.pdf_path,title=excluded.title,
                  abstract=excluded.abstract,retrieval_text=excluded.retrieval_text,
                  metadata_json=excluded.metadata_json,indexed_at=excluded.indexed_at
                """,
                (
                    paper.document_version_id,
                    paper.paper_id,
                    paper.pdf_path,
                    paper.title,
                    paper.abstract,
                    paper.retrieval_text,
                    json.dumps(paper.metadata, ensure_ascii=False, sort_keys=True),
                    SCHEMA_VERSION,
                    now,
                ),
            )
            conn.execute(
                "DELETE FROM scientific_semantic_block_store WHERE document_version_id=?",
                (paper.document_version_id,),
            )
            conn.executemany(
                """
                INSERT INTO scientific_semantic_block_store
                (block_id,document_version_id,paper_id,block_type,page,pdf_page_index,
                 section_id,section_path,section_type,section_title,table_id,raw_text,
                 retrieval_text,bbox_json,previous_block_id,next_block_id,
                 related_block_ids_json,source_text_type,schema_version,indexed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [self._block_record(block, now) for block in paper.blocks],
            )
            conn.commit()

    @staticmethod
    def _block_record(block: SemanticBlock, now: str) -> tuple[Any, ...]:
        return (
            block.block_id,
            block.document_version_id,
            block.paper_id,
            block.block_type.value,
            block.page,
            block.pdf_page_index,
            block.section_id,
            block.section_path,
            block.section_type,
            block.section_title,
            block.table_id,
            block.text,
            block.retrieval_text,
            json.dumps(block.bbox) if block.bbox is not None else None,
            block.previous_block_id,
            block.next_block_id,
            json.dumps(block.related_block_ids, ensure_ascii=False),
            block.source_text_type,
            SCHEMA_VERSION,
            now,
        )

    def papers(self, paper_ids: list[str] | None = None) -> list[StructuredScientificPaper]:
        where = ""
        params: list[Any] = []
        if paper_ids:
            where = "WHERE paper_id IN ({})".format(",".join("?" * len(paper_ids)))
            params.extend(paper_ids)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM scientific_document_store {where} ORDER BY paper_id", params
            ).fetchall()
        return [self._paper_from_row(dict(row)) for row in rows]

    def _paper_from_row(self, row: dict[str, Any]) -> StructuredScientificPaper:
        return StructuredScientificPaper(
            paper_id=str(row["paper_id"]),
            document_version_id=str(row["document_version_id"]),
            title=str(row.get("title") or ""),
            abstract=str(row.get("abstract") or ""),
            retrieval_text=str(row.get("retrieval_text") or ""),
            metadata=json.loads(row.get("metadata_json") or "{}"),
            blocks=self.blocks(document_version_id=str(row["document_version_id"])),
            pdf_path=row.get("pdf_path"),
        )

    def blocks(
        self,
        *,
        paper_ids: list[str] | None = None,
        document_version_id: str | None = None,
    ) -> list[SemanticBlock]:
        clauses: list[str] = []
        params: list[Any] = []
        if paper_ids:
            clauses.append("paper_id IN ({})".format(",".join("?" * len(paper_ids))))
            params.extend(paper_ids)
        if document_version_id:
            clauses.append("document_version_id=?")
            params.append(document_version_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM scientific_semantic_block_store {where} "
                "ORDER BY paper_id,pdf_page_index,rowid",
                params,
            ).fetchall()
        return [self._block_from_row(dict(row)) for row in rows]

    @staticmethod
    def _block_from_row(row: dict[str, Any]) -> SemanticBlock:
        return SemanticBlock(
            paper_id=str(row["paper_id"]),
            document_version_id=str(row["document_version_id"]),
            block_id=str(row["block_id"]),
            block_type=str(row["block_type"]),
            page=int(row["page"]),
            pdf_page_index=int(row["pdf_page_index"]),
            section_id=row.get("section_id"),
            section_path=row.get("section_path"),
            section_type=row.get("section_type"),
            section_title=row.get("section_title"),
            table_id=row.get("table_id"),
            text=str(row.get("raw_text") or ""),
            retrieval_text=str(row.get("retrieval_text") or ""),
            bbox=tuple(json.loads(row["bbox_json"])) if row.get("bbox_json") else None,
            previous_block_id=row.get("previous_block_id"),
            next_block_id=row.get("next_block_id"),
            related_block_ids=json.loads(row.get("related_block_ids_json") or "[]"),
            source_text_type=str(row.get("source_text_type") or "native"),
        )

    def index_items(self, index_name: str) -> list[dict[str, Any]]:
        if index_name == "paper":
            with self.connection() as conn:
                rows = conn.execute(
                    "SELECT document_version_id AS item_id,paper_id,document_version_id,"
                    "NULL AS block_id,retrieval_text FROM scientific_document_store"
                ).fetchall()
        elif index_name == "block":
            with self.connection() as conn:
                rows = conn.execute(
                    "SELECT block_id AS item_id,paper_id,document_version_id,block_id,"
                    "retrieval_text FROM scientific_semantic_block_store"
                ).fetchall()
        else:
            raise ValueError(f"unknown scientific index: {index_name}")
        return [dict(row) for row in rows]

    def replace_index(
        self,
        index_name: str,
        revision: str,
        encoder_name: str,
        model: dict[str, Any],
        vectors: list[dict[str, Any]],
    ) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM scientific_hybrid_index_vector WHERE index_name=?", (index_name,))
            conn.executemany(
                """
                INSERT INTO scientific_hybrid_index_vector
                (index_name,revision,item_id,paper_id,document_version_id,block_id,vector_json)
                VALUES (?,?,?,?,?,?,?)
                """,
                [
                    (
                        index_name,
                        revision,
                        item["item_id"],
                        item["paper_id"],
                        item["document_version_id"],
                        item.get("block_id"),
                        json.dumps(item["vector"]),
                    )
                    for item in vectors
                ],
            )
            conn.execute(
                """
                INSERT INTO scientific_hybrid_index_state
                (index_name,revision,encoder_name,encoder_model_json,item_count,
                 schema_version,built_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(index_name) DO UPDATE SET
                  revision=excluded.revision,encoder_name=excluded.encoder_name,
                  encoder_model_json=excluded.encoder_model_json,item_count=excluded.item_count,
                  schema_version=excluded.schema_version,built_at=excluded.built_at
                """,
                (
                    index_name,
                    revision,
                    encoder_name,
                    json.dumps(model),
                    len(vectors),
                    SCHEMA_VERSION,
                    _now(),
                ),
            )
            conn.commit()

    def index_state(self, index_name: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM scientific_hybrid_index_state WHERE index_name=?",
                (index_name,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["encoder_model"] = json.loads(result.pop("encoder_model_json"))
        return result

    def index_vectors(self, index_name: str, revision: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM scientific_hybrid_index_vector "
                "WHERE index_name=? AND revision=?",
                (index_name, revision),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["vector"] = json.loads(item.pop("vector_json"))
            output.append(item)
        return output

    def upsert_knowledge(
        self,
        requirement: Requirement,
        evidence: RequirementEvidence,
        *,
        paper_id: str,
        document_version_id: str,
        extractor_model: str,
        extraction_schema_version: str,
    ) -> str:
        if not evidence.valid:
            raise ValueError("only mechanically validated evidence may enter structured knowledge")
        if evidence.status != ExtractionStatus.FOUND:
            raise ValueError("only positive scientific findings may enter structured knowledge")
        signature = requirement_signature(requirement)
        knowledge_id = _knowledge_id(
            signature,
            paper_id,
            document_version_id,
            extractor_model,
            evidence.prompt_version,
            extraction_schema_version,
        )
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO structured_scientific_knowledge
                (knowledge_id,requirement_signature,requirement_id,quantity,paper_id,
                 document_version_id,extraction_status,value,lower,upper,unit,
                 conditions_json,semantic_role,source_block_refs_json,evidence_quote,
                 confidence,validation_state,governance_status,extractor_model,
                 prompt_version,extraction_schema_version,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(requirement_signature,paper_id,document_version_id,
                            extractor_model,prompt_version,extraction_schema_version)
                DO UPDATE SET extraction_status=excluded.extraction_status,
                  value=excluded.value,lower=excluded.lower,upper=excluded.upper,
                  unit=excluded.unit,conditions_json=excluded.conditions_json,
                  semantic_role=excluded.semantic_role,
                  source_block_refs_json=excluded.source_block_refs_json,
                  evidence_quote=excluded.evidence_quote,confidence=excluded.confidence,
                  validation_state=excluded.validation_state,
                  governance_status=excluded.governance_status,created_at=excluded.created_at
                """,
                (
                    knowledge_id,
                    signature,
                    requirement.requirement_id,
                    requirement.quantity,
                    paper_id,
                    document_version_id,
                    evidence.status.value,
                    evidence.value,
                    evidence.lower,
                    evidence.upper,
                    evidence.unit,
                    json.dumps(evidence.conditions, ensure_ascii=False, sort_keys=True),
                    evidence.semantic_role,
                    json.dumps(evidence.source_block_refs, ensure_ascii=False),
                    evidence.evidence_quote,
                    evidence.confidence,
                    evidence.validation_state,
                    evidence.governance_status,
                    extractor_model,
                    evidence.prompt_version,
                    extraction_schema_version,
                    _now(),
                ),
            )
            conn.commit()
        return knowledge_id

    def query_knowledge(self, requirement: Requirement) -> list[dict[str, Any]]:
        """Governance status is returned, never used as a retrieval filter."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM structured_scientific_knowledge WHERE quantity=? "
                "ORDER BY confidence DESC,created_at DESC",
                (requirement.quantity,),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["conditions"] = json.loads(item.pop("conditions_json"))
            item["source_block_refs"] = json.loads(item.pop("source_block_refs_json"))
            output.append(item)
        return output


def requirement_signature(requirement: Requirement) -> str:
    payload = json.dumps(
        {
            "quantity": requirement.quantity,
            "role": requirement.role,
            "expected_unit": requirement.expected_unit,
            "conditions": requirement.conditions,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _knowledge_id(*parts: str) -> str:
    return "knowledge-" + hashlib.sha256("\n".join(parts).encode()).hexdigest()[:20]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
