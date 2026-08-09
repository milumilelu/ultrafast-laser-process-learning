"""CURATED_LITERATURE_FIXTURE seeder (M3/M5).

Seeds the shared ultrafast_memory DB with the golden SiC corpus:

1. literature_paper / literature_section / literature_chunk rows
   (all marked CURATED_LITERATURE_FIXTURE, evidence_level=literature_evidence)
2. rag_index + lexical (FTS) + mock-vector entries via the canonical
   index service (deterministic, offline)
3. pre-recorded SourceScientificAnalysis entries in the analysis cache,
   keyed exactly as ScientificKnowledgeService computes them, so the
   golden path replays the LLM reading deterministically.

Run once per memory root; idempotent per paper_id.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from packages.e2p.application.traceability import new_run_id  # noqa: F401  (convention)

_CORPUS_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "test_fixture"
    / "literature"
    / "golden_sic_corpus.json"
)

_DEFAULT_SCOPE = {
    "task_context_id": "DEMO-P2P-001",
    "task_context_version": 1,
    "material": "SiC",
    "laser_type": "fs",
    "process_type": "fs_laser_processing",
    "geometry_type": "rectangular_groove",
    "target": "depth_um",
}


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = ":".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:24]}"


def _chunk_metadata(paper: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": paper["paper_id"],
        "title": paper["canonical_title"],
        "material": paper.get("material"),
        "material_grade": None,
        "process_type": paper.get("process_type"),
        "laser_type": paper.get("laser_type"),
        "section_type": section["section_type"],
        "section_title": section.get("section_title") or section["section_type"],
        "source_type": "literature",
        "evidence_level": "literature_evidence",
        "target_level": "LEVEL_2_LITERATURE_EVIDENCE",
        "review_status": "accepted_as_literature_evidence",
        "review_action_status": "accepted",
        "not_usable_for": [],
        "usable_for": ["parameter_recommendation"],
        "fixture_label": "CURATED_LITERATURE_FIXTURE",
        "year": paper.get("year"),
        "authors": paper.get("authors"),
    }


def _insert_paper_rows(paper: dict[str, Any]) -> None:
    from ultrafast_memory.core.time_utils import utc_now_iso
    from ultrafast_memory.db.session import get_connection

    now = utc_now_iso()
    paper_id = paper["paper_id"]
    title = paper["canonical_title"]
    normalized = " ".join(title.split()).casefold()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO literature_paper (
              paper_id,canonical_title,normalized_title,authors,year,doi,source,url,
              scenario_id,material,material_grade,component_type,process_type,laser_type,
              wavelength_nm,pulse_width_fs,power_or_energy,frequency_kHz,scan_speed_mm_s,
              beam_shape,environment,geometry_json,quality_metrics_json,defects_json,
              measurement_methods_json,usable_for_json,not_usable_for_json,evidence_level,
              review_status,canonical_artifact_id,created_at,updated_at
            ) VALUES (
              :paper_id,:canonical_title,:normalized_title,:authors,:year,:doi,:source,:url,
              :scenario_id,:material,:material_grade,:component_type,:process_type,:laser_type,
              :wavelength_nm,:pulse_width_fs,:power_or_energy,:frequency_kHz,:scan_speed_mm_s,
              :beam_shape,:environment,:geometry_json,:quality_metrics_json,:defects_json,
              :measurement_methods_json,:usable_for_json,:not_usable_for_json,:evidence_level,
              :review_status,:canonical_artifact_id,:created_at,:updated_at
            ) ON CONFLICT(paper_id) DO UPDATE SET
              canonical_title=excluded.canonical_title,
              material=excluded.material, process_type=excluded.process_type,
              laser_type=excluded.laser_type, updated_at=excluded.updated_at
            """,
            {
                "paper_id": paper_id,
                "canonical_title": title,
                "normalized_title": normalized,
                "authors": paper.get("authors"),
                "year": paper.get("year"),
                "doi": None,
                "source": "curated_literature_fixture",
                "url": None,
                "scenario_id": None,
                "material": paper.get("material"),
                "material_grade": paper.get("material_grade"),
                "component_type": None,
                "process_type": paper.get("process_type"),
                "laser_type": paper.get("laser_type"),
                "wavelength_nm": None,
                "pulse_width_fs": None,
                "power_or_energy": None,
                "frequency_kHz": None,
                "scan_speed_mm_s": None,
                "beam_shape": None,
                "environment": None,
                "geometry_json": None,
                "quality_metrics_json": None,
                "defects_json": None,
                "measurement_methods_json": None,
                "usable_for_json": json.dumps(["parameter_recommendation"], ensure_ascii=False),
                "not_usable_for_json": "[]",
                "evidence_level": "literature_evidence",
                "review_status": "accepted_as_literature_evidence",
                "canonical_artifact_id": None,
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            "UPDATE literature_chunk SET active=0, updated_at=? WHERE paper_id=?",
            (now, paper_id),
        )
        for index, section in enumerate(paper.get("sections") or []):
            text = str(section.get("text") or "").strip()
            if not text:
                continue
            section_id = _stable_id("section", paper_id, section.get("section_type"), index)
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            conn.execute(
                """
                INSERT INTO literature_section (
                  section_id,paper_id,artifact_id,section_type,section_title,page_start,
                  page_end,text,text_hash,parser_version,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(section_id) DO UPDATE SET
                  text=excluded.text,text_hash=excluded.text_hash,
                  section_title=excluded.section_title
                """,
                (
                    section_id, paper_id, None,
                    section.get("section_type", "other"),
                    section.get("section_title") or section.get("section_type", "other"),
                    int(section.get("page_start") or 1),
                    int(section.get("page_end") or section.get("page_start") or 1),
                    text, text_hash, "curated-corpus-v1", now,
                ),
            )
            chunk_id = _stable_id("chunk", paper_id, section.get("section_type"), index)
            metadata = _chunk_metadata(paper, section)
            conn.execute(
                """
                INSERT INTO literature_chunk (
                  chunk_id,paper_id,section_id,artifact_id,chunk_index,page_start,page_end,
                  section_type,section_title,content,content_hash,token_estimate,metadata_json,
                  evidence_level,review_status,active,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                  content=excluded.content,content_hash=excluded.content_hash,
                  metadata_json=excluded.metadata_json,evidence_level=excluded.evidence_level,
                  review_status=excluded.review_status,active=1,updated_at=excluded.updated_at
                """,
                (
                    chunk_id, paper_id, section_id, None, index,
                    int(section.get("page_start") or 1),
                    int(section.get("page_end") or section.get("page_start") or 1),
                    section.get("section_type", "other"),
                    section.get("section_title") or section.get("section_type", "other"),
                    text, text_hash, _estimate_tokens(text),
                    json.dumps(metadata, ensure_ascii=False),
                    "literature_evidence", "accepted_as_literature_evidence",
                    1, now, now,
                ),
            )
        conn.commit()


def _estimate_tokens(text: str) -> int:
    import re

    latin = len(re.findall(r"[A-Za-z0-9_]+", text))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return latin + cjk


def _build_and_seed_cache(
    corpus_payload: dict[str, Any],
    task_scope: dict[str, Any],
    *,
    model: str,
    requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the corpus exactly as resolution does, then pre-record analyses.

    The cache keys are computed with the same requirement-driven intent set
    as RequirementResolutionService so the golden path replays deterministically.
    """
    from apps.topic2_backend.application.requirement_resolution import (
        intents_for_requirements,
    )
    from ultrafast_knowledge.corpus.builder import ScientificCorpusBuilder
    from ultrafast_knowledge.corpus.schemas import RetrievalIntent
    from ultrafast_knowledge.scientific_analysis.cache import SQLiteSourceAnalysisCache
    from ultrafast_knowledge.scientific_analysis.service import (
        PipelineConfig,
        ScientificKnowledgeService,
    )

    cache = SQLiteSourceAnalysisCache()
    builder = ScientificCorpusBuilder()
    intent_values = (
        intents_for_requirements(requirements)
        if requirements
        else [
            intent.value
            for intent in (
                RetrievalIntent.THRESHOLD,
                RetrievalIntent.MATERIAL_PROPERTY,
                RetrievalIntent.MECHANISM,
                RetrievalIntent.FORMULA,
                RetrievalIntent.REPORTED_OPTIMUM,
                RetrievalIntent.PARAMETER_CONDITION,
                RetrievalIntent.PARAMETER_EFFECT,
            )
        ]
    )
    intents = [RetrievalIntent(value) for value in intent_values]
    pack = builder.build(task_scope, intents=intents)
    if not pack.sources:
        raise ValueError("golden corpus produced no sources - corpus texts cannot match RAG queries")

    class _Stub:
        def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict:
            raise AssertionError("cache seeding must never call the LLM")

    service = ScientificKnowledgeService(
        _Stub(),
        model=model,
        config=PipelineConfig(level="FAST", primary_count=8),
        cache=cache,
    )
    analyses_by_paper = corpus_payload.get("analyses") or {}
    seeded = 0
    for source in pack.sources:
        raw = analyses_by_paper.get(source.paper_id)
        if raw is None:
            continue
        analysis = _build_analysis(source, raw, model)
        key = service._cache_key(source, task_scope)
        cache.put(key, analysis)
        seeded += 1
    if seeded == 0:
        raise ValueError("golden corpus produced no seedable analyses")
    return {
        "corpus_pack_id": pack.corpus_pack_id,
        "sources": len(pack.sources),
        "seeded_analyses": seeded,
    }


def _build_analysis(source: Any, raw: dict[str, Any], model: str) -> Any:
    from ultrafast_knowledge.scientific_analysis.schemas import (
        LocalKnowledgeItem,
        SourceInternalConflict,
        SourceKnowledgeGap,
        SourceScientificAnalysis,
    )

    def items(key: str) -> list[LocalKnowledgeItem]:
        return [
            LocalKnowledgeItem(
                item_id=str(item.get("item_id") or f"{source.paper_id}-{key}-{index}"),
                type=item["type"],
                parameter=item.get("parameter"),
                target=item.get("target"),
                value=item.get("value"),
                lower=item.get("lower"),
                upper=item.get("upper"),
                unit=item.get("unit"),
                relation=item.get("relation"),
                property=item.get("property"),
                name=item.get("name"),
                expression=item.get("expression"),
                variables=dict(item.get("variables") or {}),
                assumptions=list(item.get("assumptions") or []),
                conditions=dict(item.get("conditions") or {}),
                semantic_role=item.get("semantic_role") or "observed_relation",
                explanation=item.get("explanation"),
                page=item.get("page"),
                chunk_ids=list(item.get("chunk_ids") or []),
                extraction_notes=list(item.get("extraction_notes") or []),
            )
            for index, item in enumerate(raw.get(key) or [])
        ]

    gaps = [
        SourceKnowledgeGap(
            type=str(gap.get("type") or "missing_information"),
            field=gap.get("field"),
            description=str(gap.get("description") or ""),
            search_hints=list(gap.get("search_hints") or []),
        )
        for gap in raw.get("knowledge_gaps") or []
    ]
    conflicts = [
        SourceInternalConflict(
            topic=str(conflict.get("topic") or ""),
            positions=[str(item) for item in conflict.get("positions") or []],
            description=str(conflict.get("description") or ""),
        )
        for conflict in raw.get("internal_conflicts") or []
    ]
    return SourceScientificAnalysis(
        source_id=source.source_id,
        paper_id=source.paper_id,
        title=source.title,
        status="completed",
        experimental_conditions=items("experimental_conditions"),
        parameter_values=items("parameter_values"),
        parameter_ranges=items("parameter_ranges"),
        parameter_effects=items("parameter_effects"),
        material_properties=items("material_properties"),
        thresholds=items("thresholds"),
        formulas=items("formulas"),
        mechanisms=items("mechanisms"),
        interactions=items("interactions"),
        reported_optima=items("reported_optima"),
        knowledge_gaps=gaps,
        internal_conflicts=conflicts,
        llm_model=model,
        prompt_version="source-map-v1",
    )


def seed_golden_corpus(
    *,
    task_scope: dict[str, Any] | None = None,
    model: str = "scientific-reading-v1",
    corpus_path: Path | None = None,
    requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Seed the golden SiC literature fixture into the shared memory DB."""
    from ultrafast_knowledge.rag.index_service import create_index, index_pending_chunks
    from ultrafast_memory.db.init_db import init_database

    init_database()
    payload_path = corpus_path or _CORPUS_PATH
    corpus_payload = json.loads(payload_path.read_text(encoding="utf-8"))
    scope = dict(task_scope or corpus_payload.get("task_scope") or _DEFAULT_SCOPE)
    for paper in corpus_payload.get("papers") or []:
        _insert_paper_rows(paper)
    index = create_index({"index_name": "literature_default"})
    index_pending_chunks(index["index_id"])
    seeded = _build_and_seed_cache(
        corpus_payload, scope, model=model, requirements=requirements
    )
    return {
        "label": "CURATED_LITERATURE_FIXTURE",
        "papers": len(corpus_payload.get("papers") or []),
        "task_scope": scope,
        "index_id": index["index_id"],
        **seeded,
    }


def main() -> None:
    """CLI entry: seed the dev memory DB with the golden corpus."""
    import argparse

    parser = argparse.ArgumentParser(description="Seed CURATED_LITERATURE_FIXTURE")
    parser.add_argument("--task-context-id", default="DEMO-P2P-001")
    parser.add_argument("--model", default="scientific-reading-v1")
    args = parser.parse_args()
    scope = dict(_DEFAULT_SCOPE)
    scope["task_context_id"] = args.task_context_id
    summary = seed_golden_corpus(task_scope=scope, model=args.model)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# PILOT_PDF ingestion (阶段三 T4): PDF -> ScientificDocument -> literature
# tables -> RAG projection.  PDF is the source of record; ScientificDocument
# is the canonical parsed artifact; RAG is only a projection — PDF text never
# bypasses ScientificDocument.  No pre-recorded analysis cache is seeded:
# real PDFs require live LLM reading (analysis_method=PENDING_LLM until then).
# ---------------------------------------------------------------------------


def _project_document(doc: Any) -> None:
    """Project one ScientificDocument into literature_paper/section/chunk."""
    import re

    from ultrafast_memory.core.time_utils import utc_now_iso
    from ultrafast_memory.db.session import get_connection

    now = utc_now_iso()
    paper_id = doc.paper_id
    title = (
        str(doc.sections[0].title).strip()
        if doc.sections
        else paper_id
    )
    normalized = re.sub(r"\s+", " ", title).strip().casefold()
    pdf_path = str(doc.pdf_path)
    pdf_sha256 = str(doc.pdf_sha256)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO literature_paper (
              paper_id,canonical_title,normalized_title,authors,year,doi,source,url,
              scenario_id,material,material_grade,component_type,process_type,laser_type,
              wavelength_nm,pulse_width_fs,power_or_energy,frequency_kHz,scan_speed_mm_s,
              beam_shape,environment,geometry_json,quality_metrics_json,defects_json,
              measurement_methods_json,usable_for_json,not_usable_for_json,evidence_level,
              review_status,canonical_artifact_id,created_at,updated_at
            ) VALUES (
              :paper_id,:canonical_title,:normalized_title,:authors,:year,:doi,:source,:url,
              :scenario_id,:material,:material_grade,:component_type,:process_type,:laser_type,
              :wavelength_nm,:pulse_width_fs,:power_or_energy,:frequency_kHz,:scan_speed_mm_s,
              :beam_shape,:environment,:geometry_json,:quality_metrics_json,:defects_json,
              :measurement_methods_json,:usable_for_json,:not_usable_for_json,:evidence_level,
              :review_status,:canonical_artifact_id,:created_at,:updated_at
            ) ON CONFLICT(paper_id) DO UPDATE SET
              canonical_title=excluded.canonical_title,
              source=excluded.source, url=excluded.url, updated_at=excluded.updated_at
            """,
            {
                "paper_id": paper_id,
                "canonical_title": title,
                "normalized_title": normalized,
                "authors": None,
                "year": None,
                "doi": None,
                "source": "pilot_pdf",
                "url": pdf_path,
                "scenario_id": None,
                "material": None,
                "material_grade": None,
                "component_type": None,
                "process_type": None,
                "laser_type": None,
                "wavelength_nm": None,
                "pulse_width_fs": None,
                "power_or_energy": None,
                "frequency_kHz": None,
                "scan_speed_mm_s": None,
                "beam_shape": None,
                "environment": None,
                "geometry_json": None,
                "quality_metrics_json": None,
                "defects_json": None,
                "measurement_methods_json": None,
                "usable_for_json": json.dumps(["parameter_recommendation"], ensure_ascii=False),
                "not_usable_for_json": "[]",
                "evidence_level": "literature_evidence",
                "review_status": "accepted_as_literature_evidence",
                "canonical_artifact_id": None,
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            "UPDATE literature_chunk SET active=0, updated_at=? WHERE paper_id=?",
            (now, paper_id),
        )
        sections = list(doc.sections or [])
        if not sections:
            sections = [
                type(doc.sections[0])(
                    section_id="s-other",
                    title=paper_id,
                    section_type="other",
                    level=1,
                    page_start=0,
                    page_end=0,
                    path="Other",
                )
            ] if doc.sections else []
        for index, section in enumerate(sections):
            block_texts = [
                doc.blocks_by_id[block_id].text
                for block_id in (section.block_ids or [])
                if block_id in doc.blocks_by_id
            ]
            text = "\n".join(block_texts).strip()
            if not text:
                continue
            section_id = str(section.section_id) or _stable_id(
                "section", paper_id, str(section.section_type), index
            )
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            conn.execute(
                """
                INSERT INTO literature_section (
                  section_id,paper_id,artifact_id,section_type,section_title,page_start,
                  page_end,text,text_hash,parser_version,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(section_id) DO UPDATE SET
                  text=excluded.text,text_hash=excluded.text_hash,
                  section_title=excluded.section_title
                """,
                (
                    section_id, paper_id, doc.document_version_id,
                    str(section.section_type) or "other",
                    str(section.title) or str(section.section_type),
                    int(section.page_start or 0),
                    int(section.page_end or section.page_start or 0),
                    text, text_hash, f"pymupdf:{doc.parser_version}", now,
                ),
            )
            chunk_id = _stable_id("chunk", paper_id, section_id)
            metadata = {
                "paper_id": paper_id,
                "document_version_id": doc.document_version_id,
                "title": title,
                "section_type": str(section.section_type) or "other",
                "section_title": str(section.title) or "",
                "section_id": section_id,
                "source_type": "literature",
                "evidence_level": "literature_evidence",
                "target_level": "LEVEL_2_LITERATURE_EVIDENCE",
                "review_status": "accepted_as_literature_evidence",
                "review_action_status": "accepted",
                "not_usable_for": [],
                "usable_for": ["parameter_recommendation"],
                "fixture_label": "PILOT_PDF",
                "pdf_ref": pdf_path,
                "pdf_sha256": pdf_sha256,
                "page_start": int(section.page_start or 0),
            }
            conn.execute(
                """
                INSERT INTO literature_chunk (
                  chunk_id,paper_id,section_id,artifact_id,chunk_index,page_start,page_end,
                  section_type,section_title,content,content_hash,token_estimate,metadata_json,
                  evidence_level,review_status,active,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                  content=excluded.content,content_hash=excluded.content_hash,
                  metadata_json=excluded.metadata_json,evidence_level=excluded.evidence_level,
                  review_status=excluded.review_status,active=1,updated_at=excluded.updated_at
                """,
                (
                    chunk_id, paper_id, section_id, doc.document_version_id, index,
                    int(section.page_start or 0),
                    int(section.page_end or section.page_start or 0),
                    str(section.section_type) or "other",
                    str(section.title) or "",
                    text, text_hash, _estimate_tokens(text),
                    json.dumps(metadata, ensure_ascii=False),
                    "literature_evidence", "accepted_as_literature_evidence",
                    1, now, now,
                ),
            )
        conn.commit()


def seed_from_pdfs(
    *,
    paper_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Pilot PDF -> ScientificDocument -> RAG projection (阶段三 T4).

    Raises RuntimeError when the literature archive is unavailable.
    Returns analysis_method=PENDING_LLM: no pre-recorded analysis cache is
    seeded for real PDFs (live LLM reading required).
    """
    from demo.t2_slice.resources import (
        PILOT_PAPER_IDS,
        resolve_literature_archive,
        resolve_pilot_pdf,
    )
    from ultrafast_ingestion import PyMuPDFDocumentParser
    from ultrafast_knowledge.rag.index_service import create_index, index_pending_chunks
    from ultrafast_memory.db.init_db import init_database

    resolve_literature_archive()  # raises if archive unavailable
    init_database()
    parser = PyMuPDFDocumentParser()
    ids = list(paper_ids or PILOT_PAPER_IDS)
    documents = []
    for paper_id in ids:
        pdf = resolve_pilot_pdf(paper_id)
        documents.append(parser.parse(pdf))
    for document in documents:
        _project_document(document)
    index = create_index({"index_name": "literature_default"})
    index_pending_chunks(index["index_id"])
    return {
        "label": "PILOT_PDF",
        "papers": len(documents),
        "index_id": index["index_id"],
        "analysis_method": "PENDING_LLM",
        "document_refs": [
            {
                "paper_id": document.paper_id,
                "document_version_id": document.document_version_id,
                "pdf_ref": str(document.pdf_path),
                "pdf_sha256": document.pdf_sha256,
            }
            for document in documents
        ],
    }


if __name__ == "__main__":
    main()
