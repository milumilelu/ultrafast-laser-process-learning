"""Ultrafast scientific document ingestion (experimental infrastructure).

Scope (S0-2B7): structure-preserving, provenance-preserving PDF parsing.
Layer 1: ScientificDocument / DocumentStructure.
Layer 2: ConditionMention (no condition grouping/linking).

Design constraints (frozen):
- PDF archive = source of record; ScientificDocument = canonical parsed
  artifact; relational tables/RAG = derived projections (not built here).
- paper_id stable; document_version_id bound to parser/config/schema.
- Never writes to the legacy DB; never touches legacy RAG.
- Deterministic for identical input + config.

Schema v0.2 items reserved (not implemented): condition.role
(PROCESSING/MEASUREMENT/COMPARISON), conflict preservation (F2/F4).
F1 (multi-value mentions) and F3 (context classification) implemented in
mentions/.
"""

from __future__ import annotations

from ultrafast_ingestion.models.document import (
    PageBlock,
    Paragraph,
    ScientificDocument,
    Section,
)
from ultrafast_ingestion.models.provenance import ProvenanceAnchor
from ultrafast_ingestion.parsers.base import DocumentParser
from ultrafast_ingestion.parsers.pymupdf_parser import PyMuPDFDocumentParser

__all__ = [
    "DocumentParser",
    "PageBlock",
    "Paragraph",
    "ProvenanceAnchor",
    "PyMuPDFDocumentParser",
    "ScientificDocument",
    "Section",
]
