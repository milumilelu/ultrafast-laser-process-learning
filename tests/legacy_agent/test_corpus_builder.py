"""批次2 回归：Scientific Retrieval Planner + CorpusBuilder（文档 F1、§5/§7/§8）。"""

from __future__ import annotations

from ultrafast_knowledge.corpus.planner import (
    build_queries,
    context_sections_for,
    default_intents,
    section_priority_for,
)
from ultrafast_knowledge.corpus.schemas import CorpusSection, CorpusSource, RetrievalIntent
from ultrafast_knowledge.rag.reranker import INTENT_SECTION_BONUS, rerank_hits


def test_default_intents_cover_document_example() -> None:
    """文档 §5.1：SiC/fs/矩形槽 应生成 A-E 全部检索域。"""
    scope = {
        "material": "SiC",
        "laser_type": "fs",
        "process_type": "rectangular_groove",
        "target": "depth_um",
    }
    intents = default_intents(scope)
    values = {intent.value for intent in intents}
    assert "parameter_effect" in values
    assert "material_property" in values
    assert "threshold" in values
    assert "mechanism" in values
    assert "formula" in values
    assert "reported_optimum" in values


def test_queries_inject_laser_and_parameter_terms() -> None:
    scope = {"material": "SiC", "laser_type": "fs", "process_type": "rectangular_groove", "target": "depth_um"}
    queries = build_queries(scope, [RetrievalIntent.FORMULA])
    query = queries[RetrievalIntent.FORMULA].lower()
    assert "sic" in query
    assert "femtosecond" in query
    assert "fluence" in query


def test_section_priority_matches_document() -> None:
    # 文档 §8：PARAMETER_CONDITION 优先 Methods/Setup/Tables；FORMULA 优先 Methods
    assert section_priority_for(RetrievalIntent.PARAMETER_CONDITION)[0] == "methods"
    assert "experimental_setup" in section_priority_for(RetrievalIntent.PARAMETER_CONDITION)
    assert section_priority_for(RetrievalIntent.FORMULA)[0] == "methods"
    assert "results" in section_priority_for(RetrievalIntent.REPORTED_OPTIMUM)
    assert "results" in section_priority_for(RetrievalIntent.PARAMETER_EFFECT)


def test_context_sections_include_tables_for_conditions() -> None:
    assert "table" in context_sections_for(RetrievalIntent.PARAMETER_CONDITION)


def _hit(section_type: str, score: float, paper: str = "P-1") -> dict:
    return {
        "paper_id": paper,
        "chunk_id": f"C-{paper}-{section_type}",
        "section_type": section_type,
        "score": score,
        "review_status": "approved",
        "metadata": {"evidence_level": "literature_evidence", "target_level": "LEVEL_2_LITERATURE_EVIDENCE"},
    }


def test_intent_aware_rerank_prefers_priority_sections() -> None:
    hits = [
        _hit("results", 0.5),
        _hit("methods", 0.49),
        _hit("table", 0.48),
    ]
    # PARAMETER_CONDITION：methods/table 应提升
    ranked = rerank_hits(hits, top_k=3, purpose="parameter_recommendation", intent="parameter_condition")
    assert ranked[0]["section_type"] == "methods"
    assert ranked[1]["section_type"] == "table"
    # PARAMETER_EFFECT：results 优先
    ranked2 = rerank_hits(hits, top_k=3, purpose="parameter_recommendation", intent="parameter_effect")
    assert ranked2[0]["section_type"] == "results"


def test_intent_bonus_applied_only_to_priority_sections() -> None:
    hits = [_hit("results", 0.5), _hit("introduction", 0.5)]
    ranked = rerank_hits(hits, top_k=3, purpose="parameter_recommendation", intent="parameter_effect")
    assert ranked[0]["section_type"] == "results"
    assert ranked[0]["score"] - ranked[1]["score"] >= INTENT_SECTION_BONUS - 1e-9


def test_corpus_source_schema_groups_sections() -> None:
    source = CorpusSource(
        source_id="src-1",
        source_type="literature",
        paper_id="P-018",
        sections=[
            CorpusSection(section_type="methods", page=3, chunk_ids=["C-1"], text="setup"),
            CorpusSection(section_type="results", page=7, chunk_ids=["C-2"], text="depth trend"),
        ],
    )
    assert len(source.sections) == 2
    assert source.sections[1].section_type == "results"


def test_builder_builds_real_corpus_for_sic() -> None:
    """集成：真实 RAG + 真实 literature_section 库（语料存在时）。"""
    from ultrafast_knowledge.corpus.builder import ScientificCorpusBuilder

    scope = {
        "material": "SiC",
        "laser_type": "fs",
        "process_type": "rectangular_groove",
        "target": "depth_um",
    }
    pack = ScientificCorpusBuilder().build(scope, task_context_id="TASK-TEST-1")
    assert pack.corpus_pack_id
    assert pack.retrieval_trace.raw_hit_count > 0
    assert pack.source_count() > 0
    # 同一论文可组合多 section（文档 F1 验收：Methods + Results + Table 可组合）
    assert pack.section_count() >= pack.source_count()
    assert pack.retrieval_trace.intents
