"""Structured scientific knowledge persistence for validated EvidenceIR v2."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ultrafast_evidence_prior.extraction import EXTRACTION_SCHEMA_VERSION, PROMPT_VERSION
from ultrafast_evidence_prior.schemas import EvidenceIRV2, ValidationState
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore


class StructuredKnowledgeStoreV2:
    """Positive, mechanically validated claims—not an opaque response cache."""

    def __init__(self, scientific_store: ScientificIndexStore) -> None:
        self.store = scientific_store
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.store.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS structured_scientific_knowledge_v2 (
                    knowledge_id TEXT PRIMARY KEY,
                    evidence_id TEXT NOT NULL UNIQUE,
                    requirement_signature TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    document_version_id TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    validation_state TEXT NOT NULL,
                    governance_status TEXT NOT NULL,
                    extractor_model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    extraction_schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_structured_knowledge_v2_lookup
                ON structured_scientific_knowledge_v2(
                    requirement_signature,paper_id,document_version_id,
                    extractor_model,prompt_version,extraction_schema_version
                );
                CREATE INDEX IF NOT EXISTS idx_structured_knowledge_v2_type
                ON structured_scientific_knowledge_v2(evidence_type,governance_status);
                """
            )
            connection.commit()

    def upsert(self, evidence: EvidenceIRV2, *, requirement_signature: str) -> str:
        if evidence.validation_state != ValidationState.VALIDATED:
            raise ValueError("only mechanically validated EvidenceIR may enter knowledge storage")
        now = datetime.now(timezone.utc).isoformat()
        knowledge_id = f"knowledge-{evidence.evidence_id.removeprefix('evidence-')}"
        with self.store.connection() as connection:
            connection.execute(
                """
                INSERT INTO structured_scientific_knowledge_v2
                (knowledge_id,evidence_id,requirement_signature,requirement_id,
                 evidence_type,paper_id,document_version_id,evidence_json,
                 validation_state,governance_status,extractor_model,prompt_version,
                 extraction_schema_version,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                  requirement_signature=excluded.requirement_signature,
                  requirement_id=excluded.requirement_id,
                  evidence_type=excluded.evidence_type,
                  paper_id=excluded.paper_id,
                  document_version_id=excluded.document_version_id,
                  evidence_json=excluded.evidence_json,
                  validation_state=excluded.validation_state,
                  governance_status=excluded.governance_status,
                  extractor_model=excluded.extractor_model,
                  prompt_version=excluded.prompt_version,
                  extraction_schema_version=excluded.extraction_schema_version,
                  updated_at=excluded.updated_at
                """,
                (
                    knowledge_id,
                    evidence.evidence_id,
                    requirement_signature,
                    evidence.requirement_id,
                    evidence.evidence_type.value,
                    evidence.paper_id,
                    evidence.document_version_id,
                    json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False),
                    evidence.validation_state.value,
                    evidence.governance_status,
                    evidence.extractor_model,
                    evidence.prompt_version,
                    EXTRACTION_SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            connection.commit()
        return knowledge_id

    def for_requirement_paper(
        self,
        *,
        requirement_signature: str,
        paper_id: str,
        document_version_id: str,
        extractor_model: str,
        prompt_version: str = PROMPT_VERSION,
        extraction_schema_version: str = EXTRACTION_SCHEMA_VERSION,
    ) -> list[EvidenceIRV2]:
        """Return matching knowledge regardless of governance state."""

        with self.store.connection() as connection:
            rows = connection.execute(
                """
                SELECT evidence_json, governance_status
                FROM structured_scientific_knowledge_v2
                WHERE requirement_signature=? AND paper_id=?
                  AND document_version_id=? AND extractor_model=?
                  AND prompt_version=? AND extraction_schema_version=?
                  AND validation_state=?
                ORDER BY created_at,evidence_id
                """,
                (
                    requirement_signature,
                    paper_id,
                    document_version_id,
                    extractor_model,
                    prompt_version,
                    extraction_schema_version,
                    ValidationState.VALIDATED.value,
                ),
            ).fetchall()
        output: list[EvidenceIRV2] = []
        for row in rows:
            raw: dict[str, Any] = json.loads(row["evidence_json"])
            raw["governance_status"] = str(row["governance_status"] or "unreviewed")
            raw["extraction_route"] = "structured_knowledge"
            output.append(EvidenceIRV2.model_validate(raw))
        return output

    def for_requirement(
        self,
        *,
        requirement_signature: str,
        extractor_model: str,
        prompt_version: str = PROMPT_VERSION,
        extraction_schema_version: str = EXTRACTION_SCHEMA_VERSION,
    ) -> list[EvidenceIRV2]:
        """Reuse every validated paper-local claim for an exact Requirement signature."""

        with self.store.connection() as connection:
            rows = connection.execute(
                """
                SELECT evidence_json, governance_status
                FROM structured_scientific_knowledge_v2
                WHERE requirement_signature=? AND extractor_model=?
                  AND prompt_version=? AND extraction_schema_version=?
                  AND validation_state=?
                ORDER BY paper_id,document_version_id,created_at,evidence_id
                """,
                (
                    requirement_signature,
                    extractor_model,
                    prompt_version,
                    extraction_schema_version,
                    ValidationState.VALIDATED.value,
                ),
            ).fetchall()
        output: list[EvidenceIRV2] = []
        for row in rows:
            raw: dict[str, Any] = json.loads(row["evidence_json"])
            raw["governance_status"] = str(row["governance_status"] or "unreviewed")
            raw["extraction_route"] = "structured_knowledge"
            output.append(EvidenceIRV2.model_validate(raw))
        return output
