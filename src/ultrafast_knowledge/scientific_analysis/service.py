"""ScientificKnowledgeService：Map → Validate → Coverage → Reduce → Selective Critic 编排。

执行链（文档第十九节）：
    CorpusPack
      → Primary Sources
      → MAP（每 Source 单次 LLM，并发 3~4，可缓存，单失败重试）
      → Deterministic Validation
      → Coverage Check（缺失 → Targeted RAG 提示 / Reserve 增补）
      → REDUCE（只读结构化结果）
      → Critical Knowledge Selector
      → SELECTIVE CRITIC（按需取证）
      → ScientificKnowledgePack

LLM 等级（文档第十五节）：
    FAST        → 仅 Map（背景/快速摘要）
    STANDARD    → Map + Validate + Reduce
    E2P_STRICT  → Map + Validate + Reduce + Selective Critic（默认）
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ultrafast_knowledge.corpus.schemas import CorpusSource, EvidenceCorpusPack
from ultrafast_knowledge.rag.metadata_filter import enforce_purpose
from ultrafast_knowledge.rag.relaxed_query import query_rag_relaxed
from ultrafast_knowledge.scientific.schemas import ScientificKnowledgePack
from ultrafast_knowledge.scientific.validator import DeterministicScientificValidator
from ultrafast_knowledge.scientific_analysis.coverage import CoveragePlanner
from ultrafast_knowledge.scientific_analysis.critic import SelectiveCritic
from ultrafast_knowledge.scientific_analysis.schemas import SourceScientificAnalysis
from ultrafast_knowledge.scientific_analysis.source_mapper import MapperConfig, SourceMapper
from ultrafast_knowledge.scientific_analysis.synthesizer import GlobalSynthesizer

AnalysisLevel = Literal["FAST", "STANDARD", "E2P_STRICT"]

MAP_PROMPT_VERSION = "source-map-v1"
REDUCE_PROMPT_VERSION = "global-reduce-v1"
CRITIC_PROMPT_VERSION = "selective-critic-v1"


class LLMClientLike(Protocol):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict: ...


class SourceAnalysisCache(Protocol):
    def get(self, key: str) -> SourceScientificAnalysis | None: ...
    def put(self, key: str, analysis: SourceScientificAnalysis) -> None: ...


@dataclass(slots=True)
class PipelineConfig:
    mapper: MapperConfig = None  # type: ignore[assignment]
    primary_count: int = 6
    coverage_threshold: float = 0.6
    use_reserve_on_gap: bool = True
    level: AnalysisLevel = "E2P_STRICT"

    def __post_init__(self) -> None:
        if self.mapper is None:
            self.mapper = MapperConfig()


class ScientificKnowledgeService:
    """核心科学提炼服务（不依赖聊天 Agent，可离线批处理）。"""

    def __init__(
        self,
        client: LLMClientLike,
        *,
        model: str = "unknown",
        config: PipelineConfig | None = None,
        cache: SourceAnalysisCache | None = None,
        validator: DeterministicScientificValidator | None = None,
    ):
        self.client = client
        self.model = model
        self.config = config or PipelineConfig()
        self.cache = cache
        self.validator = validator or DeterministicScientificValidator()
        self.mapper = SourceMapper(client, config=self.config.mapper, model=model)
        self.synthesizer = GlobalSynthesizer(client, model=model)
        self.critic = SelectiveCritic(client, model=model)
        self.coverage = CoveragePlanner(
            sufficient_threshold=self.config.coverage_threshold
        )

    # ------------------------------------------------------------ pipeline
    def analyze(
        self,
        pack: EvidenceCorpusPack,
        *,
        level: AnalysisLevel | None = None,
        sources: list[CorpusSource] | None = None,
        progress_callback=None,
    ) -> dict[str, Any]:
        """完整执行链；返回 KnowledgePack + 过程报告（coverage/mapping/critic）。

        progress_callback(stage: str, detail: dict) 在各阶段推进时回调，
        供 Job/前端实时展示（retrieving 由调用方负责；本方法回调
        mapping/validating/coverage/reducing/criticizing）。
        """
        level = level or self.config.level

        def emit(stage: str, detail: dict[str, Any] | None = None) -> None:
            if progress_callback is not None:
                progress_callback(stage, detail or {})

        emit("mapping", {"current": 0, "total": 0})
        analyses, mapping_report = self._map_phase(pack, sources, emit)
        report: dict[str, Any] = {"mapping": mapping_report, "level": level}

        if level == "FAST":
            return {
                **self._pack_from_analyses(analyses, pack),
                "pipeline_report": report,
            }

        # 确定性验证：只让 validated 候选进入 Reduce（文档第五节）
        emit("validating", {"current": 0, "total": len(analyses)})
        knowledge = self._pack_from_analyses(analyses, pack)
        validation = self.validator.validate(knowledge)
        report["validation"] = {
            "validated": len(validation.validated_candidates),
            "rejected": len(validation.rejected_candidates),
        }
        emit("validating", {"current": 1, "total": 1, "validated": len(validation.validated_candidates), "rejected": len(validation.rejected_candidates)})

        # Coverage Check（文档第九节）：缺失 → Targeted RAG 提示 / Reserve 增补
        coverage = self.coverage.assess(analyses)
        report["coverage"] = coverage.to_dict()
        if (
            self.config.use_reserve_on_gap
            and not coverage.sufficient()
            and sources is None
        ):
            reserve = self.coverage.reserve_sources(pack, self.config.primary_count)
            if reserve:
                emit("mapping", {"current": 0, "total": len(reserve), "reserve": True})
                reserve_analyses, _reserve_report = self._map_phase(
                    pack, sources=reserve, emit=emit
                )
                analyses = [*analyses, *reserve_analyses]
                coverage = self.coverage.assess(analyses)
                report["coverage"] = coverage.to_dict()
                report["reserve_mapped"] = len(reserve_analyses)
        report["targeted_rag_queries"] = self.coverage.targeted_rag_queries(coverage)
        emit("coverage", {"covered": coverage.coverage_ratio, "missing": len(coverage.missing)})

        # Coverage 闭环（审阅 §4）：缺失类别 → 主动 Targeted RAG 检索 → 增量 Map，
        # 而不是只输出提示。
        if not coverage.sufficient() and sources is None:
            targeted = self._targeted_retrieval(pack.task_scope, coverage.missing[:2])
            if targeted:
                emit("mapping", {"current": 0, "total": len(targeted), "targeted": True})
                targeted_analyses, _targeted_report = self._map_phase(
                    pack, sources=targeted, emit=emit
                )
                analyses = [*analyses, *targeted_analyses]
                coverage = self.coverage.assess(analyses)
                report["coverage"] = coverage.to_dict()
                report["targeted_mapped"] = len(targeted_analyses)
                report["targeted_sources"] = [t.source_id for t in targeted]
                emit("coverage", {"covered": coverage.coverage_ratio, "missing": len(coverage.missing), "targeted": True})

        if level == "STANDARD":
            return {
                **self._pack_from_analyses(analyses, pack),
                "pipeline_report": report,
            }

        # REDUCE：只读结构化结果（文档第六节）
        emit("reducing", {})
        reduced = self.synthesizer.synthesize(analyses, pack.task_scope, pack.corpus_pack_id)
        report["reduce"] = {
            "candidates": len(reduced.candidates),
            "known": len(reduced.known),
            "unknown": len(reduced.unknown),
            "conflicts": len(reduced.conflicts),
        }
        emit("reducing", {"candidates": len(reduced.candidates), "known": len(reduced.known)})

        # SELECTIVE CRITIC：只审核高风险候选，按需取证（文档第七、八节）
        selected = self.critic.select_candidates(reduced)
        emit("criticizing", {"current": 0, "total": len(selected)})
        critic_result = self.critic.criticize(reduced, pack, emit=emit)
        report["critic"] = critic_result
        emit("criticizing", {"current": len(selected), "total": len(selected)})
        return {**reduced.model_dump(mode="json"), "pipeline_report": report}
        reduced = self.synthesizer.synthesize(analyses, pack.task_scope, pack.corpus_pack_id)
        report["reduce"] = {
            "candidates": len(reduced.candidates),
            "known": len(reduced.known),
            "unknown": len(reduced.unknown),
            "conflicts": len(reduced.conflicts),
        }

        # SELECTIVE CRITIC：只审核高风险候选，按需取证（文档第七、八节）
        critic_result = self.critic.criticize(reduced, pack)
        report["critic"] = critic_result
        return {**reduced.model_dump(mode="json"), "pipeline_report": report}

    # ------------------------------------------------------------- helpers
    def _targeted_retrieval(
        self,
        task_scope: dict[str, Any],
        missing_categories: list[str],
    ) -> list[CorpusSource]:
        """缺失类别 → Targeted RAG 检索 → 新 CorpusSource（增量 Map 输入）。

        用类别检索词（而非泛搜）在语料库中精确检索，返回未出现在原语料包
        中的来源。检索失败返回空列表（不阻断主流程）。
        """
        from ultrafast_knowledge.corpus.schemas import CorpusSection, CorpusSource
        from ultrafast_knowledge.scientific_analysis.coverage import CATEGORY_SEARCH_HINTS

        sources: list[CorpusSource] = []
        seen_papers: set[str] = set()
        filters = {"material": task_scope["material"]} if task_scope.get("material") else {}
        laser = {"fs": "femtosecond", "ps": "picosecond"}.get(
            str(task_scope.get("laser_type") or "").lower(), ""
        )
        for category in missing_categories:
            hints = CATEGORY_SEARCH_HINTS.get(category, ())
            if not hints:
                continue
            query = " ".join(
                str(item) for item in (task_scope.get("material"), laser, *hints) if item
            )
            try:
                pack = query_rag_relaxed(
                    {
                        "query": query,
                        "filters": filters,
                        "top_k": 3,
                        "purpose": "parameter_recommendation",
                        "index_name": "literature_default",
                    }
                )
            except Exception:  # noqa: BLE001,S112 - 补缺检索失败不阻断主流程
                continue
            for hit in pack.get("hits") or []:
                if not enforce_purpose(hit, "parameter_recommendation"):
                    continue
                paper_id = str(hit.get("paper_id") or "unknown")
                if paper_id in seen_papers:
                    continue
                seen_papers.add(paper_id)
                sources.append(
                    CorpusSource(
                        source_id=f"tg-{paper_id[-8:]}",
                        source_type="literature",
                        paper_id=paper_id,
                        title=str(hit.get("title") or ""),
                        sections=[
                            CorpusSection(
                                section_type="other",
                                page=hit.get("page_start"),
                                chunk_ids=[str(hit["chunk_id"])] if hit.get("chunk_id") else [],
                                text=str(hit.get("content") or ""),
                            )
                        ],
                    )
                )
        return sources

    def _map_phase(
        self,
        pack: EvidenceCorpusPack,
        sources: list[CorpusSource] | None,
        emit=None,
    ) -> tuple[list[SourceScientificAnalysis], dict[str, Any]]:
        """MAP：Primary（或指定）Source 并发分析；命中缓存直接复用。

        emit(stage, detail) 在每完成一个 Source 时回调进度。
        """
        if sources is None:
            sources = self.coverage.select_primary(pack, self.config.primary_count)
        total = len(sources)
        analyses: list[SourceScientificAnalysis] = []
        from_cache = 0
        todo: list[CorpusSource] = []
        for source in sources:
            key = self._cache_key(source, pack.task_scope)
            cached = self.cache.get(key) if self.cache else None
            if cached is not None:
                analyses.append(cached)
                from_cache += 1
            else:
                todo.append(source)
        done = len(analyses)

        def on_source_done(current: int, _total: int, analysis: SourceScientificAnalysis) -> None:
            nonlocal done
            done = from_cache + current
            if emit is not None:
                emit(
                    "mapping",
                    {
                        "current": done,
                        "total": total,
                        "source_id": analysis.source_id,
                        "paper_id": analysis.paper_id,
                        "title": analysis.title,
                        "items": analysis.item_count(),
                        "types": sorted(
                            {item.type.value for item in analysis.all_items()}
                        ),
                        "gaps": len(analysis.knowledge_gaps),
                        "status": analysis.status.value,
                        "cached": False,
                    },
                )

        if todo:
            fresh = self.mapper.map_corpus(pack, todo, on_source_done=on_source_done)
            if self.cache:
                for source, analysis in zip(todo, fresh, strict=True):
                    if analysis.status.value == "completed":
                        self.cache.put(self._cache_key(source, pack.task_scope), analysis)
            analyses.extend(fresh)
        else:
            if emit is not None:
                for cached in analyses:
                    emit(
                        "mapping",
                        {
                            "current": done,
                            "total": total,
                            "source_id": cached.source_id,
                            "paper_id": cached.paper_id,
                            "title": cached.title,
                            "items": cached.item_count(),
                            "types": sorted({item.type.value for item in cached.all_items()}),
                            "gaps": len(cached.knowledge_gaps),
                            "status": cached.status.value,
                            "cached": True,
                        },
                    )
        return analyses, {
            "sources": len(sources),
            "completed": sum(a.status.value == "completed" for a in analyses),
            "partial": sum(a.status.value == "partial" for a in analyses),
            "failed": sum(a.status.value == "failed" for a in analyses),
            "from_cache": from_cache,
        }

    def _pack_from_analyses(
        self,
        analyses: list[SourceScientificAnalysis],
        pack: EvidenceCorpusPack,
    ) -> ScientificKnowledgePack:
        """FAST/STANDARD 中间产物：Source 分析 → 候选池（未综合）。"""
        candidates = []
        for analysis in analyses:
            for item in analysis.all_items():
                candidates.append(
                    {
                        "candidate_id": item.item_id,
                        "type": item.type,
                        "parameter": item.parameter,
                        "target": item.target,
                        "value": item.value,
                        "lower": item.lower,
                        "upper": item.upper,
                        "unit": item.unit,
                        "relation": item.relation,
                        "property": item.property,
                        "name": item.name,
                        "expression": item.expression,
                        "variables": item.variables,
                        "assumptions": item.assumptions,
                        "conditions": item.conditions,
                        "semantic_role": item.semantic_role,
                        "supporting_sources": [
                            {
                                "paper_id": analysis.paper_id,
                                "page": item.page,
                                "chunk_ids": item.chunk_ids,
                            }
                        ],
                        "extraction_notes": item.extraction_notes,
                    }
                )
        from ultrafast_knowledge.scientific.schemas import ScientificKnowledgeCandidate

        parsed = []
        for raw in candidates:
            try:
                parsed.append(ScientificKnowledgeCandidate(**raw))
            except (TypeError, ValueError):
                continue
        unknown = []
        for analysis in analyses:
            for gap in analysis.knowledge_gaps:
                unknown.append(
                    {
                        "topic": gap.field or gap.type,
                        "description": gap.description,
                        "related_conditions": {},
                    }
                )
        return ScientificKnowledgePack(
            knowledge_pack_id=f"kp-map-{uuid.uuid4().hex[:8]}",
            source_corpus_pack_id=pack.corpus_pack_id,
            task_scope=pack.task_scope,
            candidates=parsed,
            unknown=unknown,
            llm_model=self.model,
            prompt_version=MAP_PROMPT_VERSION,
        )

    def _cache_key(self, source: CorpusSource, task_scope: dict[str, Any]) -> str:
        source_hash = hashlib.sha256(
            json.dumps(
                {
                    "sections": [
                        {
                            "section_type": section.section_type,
                            "page": section.page,
                            "chunk_ids": section.chunk_ids,
                            "text": section.text[:2000],
                        }
                        for section in source.sections
                    ],
                    "title": source.title,
                    "paper_id": source.paper_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        scope_hash = hashlib.sha256(
            json.dumps(task_scope, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:12]
        return f"{source.source_id}:{source_hash[:16]}:{scope_hash}:{MAP_PROMPT_VERSION}:{self.model}"
