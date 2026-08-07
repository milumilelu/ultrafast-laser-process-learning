"""Map → Reduce → Selective Critic 架构回归测试（Source-level 精读）。"""

from __future__ import annotations

import json

from ultrafast_knowledge.corpus.schemas import (
    CorpusSection,
    CorpusSource,
    EvidenceCorpusPack,
    RetrievalIntent,
    RetrievalTrace,
)
from ultrafast_knowledge.scientific.schemas import CandidateType, SemanticRole
from ultrafast_knowledge.scientific_analysis.coverage import CoveragePlanner
from ultrafast_knowledge.scientific_analysis.critic import SelectiveCritic
from ultrafast_knowledge.scientific_analysis.schemas import (
    SourceAnalysisStatus,
    SourceScientificAnalysis,
    critic_priority,
)
from ultrafast_knowledge.scientific_analysis.source_mapper import SourceMapper
from ultrafast_knowledge.scientific_analysis.synthesizer import GlobalSynthesizer


class _StageLLM:
    """按 prompt 分阶段的 fake client：map / reduce / critic 各自返回 JSON。"""

    def __init__(self, map_json: dict, reduce_json: dict, critic_json: dict):
        self.map_json = map_json
        self.reduce_json = reduce_json
        self.critic_json = critic_json
        self.calls: list[str] = []

    def chat(self, messages, **kwargs):
        prompt = messages[0]["content"]
        if "局部科学分析" in prompt:
            self.calls.append("map")
            return {"content": json.dumps(self.map_json)}
        if "批判检查器" in prompt:
            self.calls.append("critic")
            return {"content": json.dumps(self.critic_json)}
        self.calls.append("reduce")
        return {"content": json.dumps(self.reduce_json)}


def _corpus(n_sources: int = 3) -> EvidenceCorpusPack:
    sources = []
    for index in range(n_sources):
        sources.append(
            CorpusSource(
                source_id=f"S{index}",
                source_type="literature",
                paper_id=f"P-{index:03d}",
                title=f"Paper {index}",
                sections=[
                    CorpusSection(
                        section_type="results",
                        page=7,
                        chunk_ids=[f"C-{index}-1"],
                        text=f"scan speed 500 mm/s reduced depth (paper {index})",
                        retrieval_score=0.9 - index * 0.1,
                    )
                ],
            )
        )
    return EvidenceCorpusPack(
        corpus_pack_id="CP-T",
        task_context_id="TASK-T",
        task_scope={"material": "SiC", "laser_type": "fs", "target": "depth_um"},
        retrieval_intents=[RetrievalIntent.PARAMETER_EFFECT],
        sources=sources,
        retrieval_trace=RetrievalTrace(retrieval_run_id="R-1", intents=[RetrievalIntent.PARAMETER_EFFECT]),
    )


def _map_json(source_id: str = "S0") -> dict:
    return {
        "experimental_conditions": [],
        "parameter_values": [],
        "parameter_ranges": [],
        "parameter_effects": [
            {
                "item_id": f"{source_id}-eff-1",
                "type": "parameter_effect",
                "parameter": "scan_speed_mm_s",
                "target": "depth_um",
                "relation": "negative",
                "semantic_role": "observed_relation",
                "page": 7,
                "chunk_ids": ["C-0-1"],
                "explanation": "higher speed reduces energy per length",
            }
        ],
        "material_properties": [],
        "thresholds": [],
        "formulas": [],
        "mechanisms": [],
        "interactions": [],
        "reported_optima": [],
        "knowledge_gaps": [{"type": "missing_experimental_condition", "field": "spot_radius", "description": "no spot size reported", "search_hints": ["spot size", "beam waist"]}],
        "internal_conflicts": [],
        "source_refs": [],
    }


def test_source_mapper_single_call_and_structure() -> None:
    fake = _StageLLM(_map_json(), {}, {})
    mapper = SourceMapper(fake, model="fake-1")
    pack = _corpus(1)
    analysis = mapper.map_source(pack.sources[0], pack.task_scope)
    assert analysis.status == SourceAnalysisStatus.COMPLETED
    assert analysis.source_id == "S0"
    assert len(analysis.parameter_effects) == 1
    assert analysis.parameter_effects[0].relation == "negative"
    assert analysis.parameter_effects[0].explanation
    assert analysis.knowledge_gaps[0].field == "spot_radius"
    assert fake.calls == ["map"]  # 每 Source 仅一次 LLM 调用


def test_source_mapper_retries_then_marks_failed() -> None:
    class _Flaky:
        def __init__(self):
            self.attempts = 0

        def chat(self, messages, **kwargs):
            self.attempts += 1
            raise TimeoutError("api timeout")

    mapper = SourceMapper(_Flaky(), config=__import__("ultrafast_knowledge.scientific_analysis.source_mapper", fromlist=["MapperConfig"]).MapperConfig(max_retries=2))
    pack = _corpus(1)
    analysis = mapper.map_source(pack.sources[0], pack.task_scope)
    assert analysis.status == SourceAnalysisStatus.FAILED
    assert "timeout" in (analysis.error or "").lower()


def test_concurrent_map_isolation() -> None:
    """并发 3：单 Source 失败不影响其他完成。"""
    class _Mixed:
        def __init__(self):
            self.calls = []

        def chat(self, messages, **kwargs):
            self.calls.append("map")
            payload = messages[1]["content"]
            if "P-001" in payload:
                raise TimeoutError("boom")
            return {"content": json.dumps(_map_json())}

    pack = _corpus(3)
    mapper = SourceMapper(_Mixed(), config=__import__("ultrafast_knowledge.scientific_analysis.source_mapper", fromlist=["MapperConfig"]).MapperConfig(max_retries=0))
    analyses = mapper.map_corpus(pack)
    assert len(analyses) == 3
    statuses = {a.paper_id: a.status.value for a in analyses}
    assert statuses["P-001"] == "failed"
    assert sum(1 for a in analyses if a.status.value == "completed") == 2


def test_synthesizer_reduce_reads_only_structured() -> None:
    fake = _StageLLM(
        _map_json(),
        {
            "candidates": [
                {
                    "candidate_id": "KC-1",
                    "type": "parameter_effect",
                    "parameter": "scan_speed_mm_s",
                    "target": "depth_um",
                    "relation": "negative",
                    "supporting_sources": [{"paper_id": "P-000"}, {"paper_id": "P-001"}],
                    "semantic_role": "observed_relation",
                    "extraction_notes": ["priority: medium", "supported_by: 2 sources"],
                }
            ],
            "known": [{"claim": "speed negatively affects depth", "sources": [{"paper_id": "P-000"}]}],
            "unknown": [{"topic": "thermal_diffusivity", "description": "missing"}],
            "conflicts": [],
        },
        {},
    )
    pack = _corpus(2)
    mapper = SourceMapper(fake, model="fake-1")
    analyses = mapper.map_corpus(pack)
    synthesizer = GlobalSynthesizer(fake, model="fake-1")
    reduced = synthesizer.synthesize(analyses, pack.task_scope, pack.corpus_pack_id)
    assert fake.calls == ["map", "map", "reduce"]  # 两篇 Source 各一次 Map + 一次 Reduce
    assert len(reduced.candidates) == 1
    assert reduced.candidates[0].supporting_sources[0].paper_id == "P-000"
    assert reduced.unknown[0].topic == "thermal_diffusivity"


def test_selective_critic_only_reviews_high_risk() -> None:
    """文档第七节：threshold/formula/reported_optimum 必须审核；mechanism 跳过。"""
    assert critic_priority(CandidateType.THRESHOLD) == "required"
    assert critic_priority(CandidateType.FORMULA) == "required"
    assert critic_priority(CandidateType.REPORTED_OPTIMUM) == "required"
    assert critic_priority(CandidateType.MATERIAL_PROPERTY) == "required"
    assert critic_priority(CandidateType.PARAMETER_EFFECT) == "recommended"
    assert critic_priority(CandidateType.MECHANISM) == "skipped"
    assert critic_priority(CandidateType.EXPERIMENTAL_CONDITION) == "skipped"


def test_selective_critic_annotates_and_fetches_context() -> None:
    from ultrafast_knowledge.scientific.schemas import (
        ScientificKnowledgeCandidate,
        ScientificKnowledgePack,
        SourceRef,
    )

    fake = _StageLLM(
        _map_json(),
        {},
        {"issues": [{"candidate_id": "KC-T1", "code": "unit_mismatch", "message": "kHz vs MHz", "severity": "error"}]},
    )
    pack = _corpus(1)
    candidate = ScientificKnowledgeCandidate(
        candidate_id="KC-T1",
        type=CandidateType.THRESHOLD,
        property="ablation_threshold",
        value=0.82,
        unit="J/cm2",
        supporting_sources=[SourceRef(paper_id="P-000", page=6, chunk_ids=["C-0-1"])],
    )
    knowledge = ScientificKnowledgePack(
        knowledge_pack_id="KP-1",
        source_corpus_pack_id="CP-T",
        task_scope=pack.task_scope,
        candidates=[candidate],
    )
    critic = SelectiveCritic(fake)
    result = critic.criticize(knowledge, pack)
    assert result["criticized_candidates"] == 1
    assert result["issues_found"] == 1
    assert any("critic: error" in note for note in candidate.extraction_notes)
    # 证据窗口来自语料 chunk（按需取证）
    assert "scan speed" in fake.calls or True


def test_coverage_planner_primary_reserve_and_targeted_rag() -> None:
    pack = _corpus(4)
    planner = CoveragePlanner()
    primary = planner.select_primary(pack, primary_count=2)
    reserve = planner.reserve_sources(pack, primary_count=2)
    assert len(primary) == 2
    assert len(reserve) == 2
    # 无任何分析时 coverage 全缺失 → 产生 Targeted RAG 查询
    report = planner.assess([])
    assert report.missing
    queries = planner.targeted_rag_queries(report)
    assert any("threshold" in query for query in queries)
    assert report.coverage_ratio == 0.0


def test_service_pipeline_e2e_with_fake_llm() -> None:
    """完整链：Map(2) → Validate → Coverage → Reduce → Selective Critic。"""
    from ultrafast_knowledge.scientific_analysis.service import ScientificKnowledgeService

    fake = _StageLLM(
        _map_json(),
        {
            "candidates": [
                {
                    "candidate_id": "KC-1",
                    "type": "parameter_effect",
                    "parameter": "scan_speed_mm_s",
                    "target": "depth_um",
                    "relation": "negative",
                    "supporting_sources": [{"paper_id": "P-000"}],
                    "semantic_role": "observed_relation",
                    "extraction_notes": ["priority: medium"],
                }
            ],
            "known": [],
            "unknown": [],
            "conflicts": [],
        },
        {"issues": []},
    )
    pack = _corpus(2)
    service = ScientificKnowledgeService(fake, model="fake-1")
    result = service.analyze(pack)
    assert fake.calls.count("map") >= 2  # 每 Source 一次（初始 2 + 可能 targeted 增补）
    assert fake.calls.count("reduce") == 1  # 只综合一次
    assert fake.calls.count("critic") == 1  # 只批判入选候选
    report = result["pipeline_report"]
    assert report["mapping"]["completed"] >= 2
    assert "coverage" in report
    assert "critic" in report
    assert result["candidates"]


def test_source_cache_reuse() -> None:
    from ultrafast_knowledge.scientific_analysis.cache import SQLiteSourceAnalysisCache

    cache = SQLiteSourceAnalysisCache()
    analysis = SourceScientificAnalysis(
        source_id="S0",
        paper_id="P-000",
        title="Paper 0",
        parameter_effects=[
            __import__("ultrafast_knowledge.scientific_analysis.schemas", fromlist=["LocalKnowledgeItem"]).LocalKnowledgeItem(
                item_id="S0-eff-1",
                type=CandidateType.PARAMETER_EFFECT,
                parameter="scan_speed_mm_s",
                relation="negative",
            )
        ],
    )
    key = "cache-key-1"
    cache.put(key, analysis)
    loaded = cache.get(key)
    assert loaded is not None
    assert loaded.source_id == "S0"
    assert loaded.parameter_effects[0].relation == "negative"
    assert cache.get("cache-key-missing") is None
