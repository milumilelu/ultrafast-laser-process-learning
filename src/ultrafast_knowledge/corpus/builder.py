"""CorpusBuilder：两阶段检索 → EvidenceCorpusPack（文档 §7、§9 F1）。

Stage 1 Paper Retrieval：按意图查询 RAG，识别最相关论文；
Stage 2 In-paper Context Expansion：从 literature_section 表取同一论文的
Methods / Results / Discussion / Tables 等 section 文本，按意图的 section
优先级组织，让 LLM 精读时能看到上下文而非孤立 chunk。
"""

from __future__ import annotations

import uuid
from typing import Any

from ultrafast_knowledge.corpus.planner import (
    build_queries,
    context_sections_for,
    default_intents,
    section_priority_for,
)
from ultrafast_knowledge.corpus.schemas import (
    CorpusSection,
    CorpusSource,
    EvidenceCorpusPack,
    RetrievalIntent,
    RetrievalTrace,
)
from ultrafast_knowledge.rag.metadata_filter import enforce_purpose, metadata_for_hit
from ultrafast_knowledge.rag.query_service import query_rag
from ultrafast_knowledge.rag.relaxed_query import query_rag_relaxed
from ultrafast_memory.core.ids import stable_id
from ultrafast_memory.db.session import get_connection

# literature_section.section_type（字符串）→ CorpusSection.section_type
_SECTION_TYPE_MAP = {
    "abstract": "abstract",
    "introduction": "introduction",
    "methods": "methods",
    "experimental": "experimental_setup",
    "experimental_setup": "experimental_setup",
    "results": "results",
    "discussion": "discussion",
    "conclusion": "conclusion",
    "table": "table",
    "figure_caption": "figure_caption",
    "equation": "equation",
    "other": "other",
}


def _map_section_type(raw: str | None) -> str:
    return _SECTION_TYPE_MAP.get(str(raw or "").strip().lower(), "other")


class ScientificCorpusBuilder:
    """按 TaskScope 构建 EvidenceCorpusPack（RAG 唯一正式输出）。"""

    def __init__(
        self,
        *,
        connection: Any = None,
        per_intent_top_k: int = 5,
        context_sections_per_paper: int = 4,
    ):
        self.connection = connection or get_connection
        self.per_intent_top_k = per_intent_top_k
        self.context_sections_per_paper = context_sections_per_paper

    def build(
        self,
        task_scope: dict[str, Any],
        *,
        task_context_id: str = "task-local",
        task_context_version: int = 1,
        intents: list[RetrievalIntent] | None = None,
    ) -> EvidenceCorpusPack:
        intents = intents or default_intents(task_scope)
        queries = build_queries(task_scope, intents)
        filters = {"material": task_scope["material"]} if task_scope.get("material") else {}
        trace = RetrievalTrace(
            retrieval_run_id=stable_id("corpus", task_context_id, uuid.uuid4().hex),
            intents=intents,
            query_by_intent={intent.value: queries[intent] for intent in intents},
        )
        sources: dict[str, CorpusSource] = {}
        all_raw = 0
        all_filtered = 0
        for intent in intents:
            pack = query_rag_relaxed(
                {
                    "query": queries[intent],
                    "filters": filters,
                    "top_k": self.per_intent_top_k,
                    "purpose": "parameter_recommendation",
                    "index_name": "literature_default",
                }
            )
            relaxed = (pack.get("retrieval_metadata") or {}).get("relaxed") or {}
            if relaxed.get("material_filter_relaxed"):
                trace.warnings.append(
                    f"material_filter_relaxed:{relaxed.get('strict_material')} — 语料标签不一致，"
                    "已放宽材料过滤（适用性由 E2P 逐维判定）"
                )
            hits = list(pack.get("hits") or [])
            all_raw += int(
                (pack.get("retrieval_metadata") or {})
                .get("evidence_waterfall", {})
                .get("raw_hits", 0)
            )
            for hit in hits:
                if not enforce_purpose(hit, "parameter_recommendation"):
                    continue
                all_filtered += 1
                paper_id = str(hit.get("paper_id") or "unknown")
                source = sources.setdefault(
                    paper_id,
                    CorpusSource(
                        source_id=f"src-{paper_id[-8:]}",
                        source_type="literature",
                        paper_id=paper_id,
                        title=str(hit.get("title") or ""),
                        material_id=task_scope.get("material"),
                        process_type=task_scope.get("process_type"),
                    ),
                )
                section_type = _map_section_type(
                    str(hit.get("section_type") or metadata_for_hit(hit).get("section_type"))
                )
                section = self._upsert_section(source, section_type)
                if hit.get("page_start") is not None:
                    section.page = int(hit["page_start"])
                for chunk_id in _chunk_ids(hit):
                    if chunk_id not in section.chunk_ids:
                        section.chunk_ids.append(chunk_id)
                # 命中 chunk 的内容必须进入语料文本（LLM 精读的输入）；
                # 仅记录 chunk_id 会让 LLM 拿到空文本。
                content = str(hit.get("content") or "").strip()
                if content and content not in section.text:
                    section.text = (section.text + "\n" + content).strip()
                hit_score = float(hit.get("score") or 0)
                if section.retrieval_score is None or hit_score > section.retrieval_score:
                    section.retrieval_score = hit_score
        self._expand_papers(sources, intents, trace)
        trace.raw_hit_count = all_raw
        trace.filtered_hit_count = all_filtered
        trace.source_count = len(sources)
        return EvidenceCorpusPack(
            corpus_pack_id=stable_id("corpus_pack", task_context_id, task_context_version),
            task_context_id=task_context_id,
            task_context_version=task_context_version,
            task_scope=task_scope,
            retrieval_intents=intents,
            sources=list(sources.values()),
            retrieval_trace=trace,
        )

    def _expand_papers(
        self,
        sources: dict[str, CorpusSource],
        intents: list[RetrievalIntent],
        trace: RetrievalTrace,
    ) -> None:
        """Stage 2：同一论文的 Methods/Results/Tables 等 section 文本补充上下文。"""
        if not sources:
            return
        wanted = sorted(
            {section for intent in intents for section in section_priority_for(intent)}
            | {section for intent in intents for section in context_sections_for(intent)}
        )
        wanted_keys = {key for key, value in _SECTION_TYPE_MAP.items() if value in wanted}
        paper_ids = list(sources)
        try:
            with self.connection() as conn:
                rows = conn.execute(
                    "SELECT paper_id, section_type, page_start, text "
                    "FROM literature_section WHERE paper_id IN ({})".format(
                        ",".join("?" * len(paper_ids))
                    ),
                    paper_ids,
                ).fetchall()
        except Exception as exc:  # noqa: BLE001 - 上下文扩展失败不阻断主流程
            trace.warnings.append(f"in_paper_context_expansion_failed: {exc}")
            return
        by_paper: dict[str, list[Any]] = {}
        for row in rows:
            if str(row["section_type"] or "").strip().lower() in wanted_keys:
                by_paper.setdefault(str(row["paper_id"]), []).append(row)
        for paper_id, sections in by_paper.items():
            source = sources.get(paper_id)
            if source is None:
                continue
            for row in sections[: self.context_sections_per_paper]:
                section_type = _map_section_type(row["section_type"])
                section = self._upsert_section(source, section_type)
                if row["page_start"] is not None:
                    section.page = int(row["page_start"])
                text = str(row["text"] or "").strip()
                if text and text not in section.text:
                    section.text = (section.text + "\n" + text).strip()

    @staticmethod
    def _upsert_section(source: CorpusSource, section_type: str) -> CorpusSection:
        for section in source.sections:
            if section.section_type == section_type:
                return section
        section = CorpusSection(section_type=section_type)  # type: ignore[arg-type]
        source.sections.append(section)
        return section


def _chunk_ids(hit: dict[str, Any]) -> list[str]:
    chunk_id = hit.get("chunk_id")
    return [str(chunk_id)] if chunk_id else []
