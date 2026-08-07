"""Pass 2: Global Reduce（文档第六节）。

只读结构化的 SourceScientificAnalysis 列表（~6000 tokens），不再读原文：
    同义 Knowledge 合并 / 多文献支持计数 / 条件对齐 / 跨文献冲突发现 /
    机制综合 / Knowledge Gap / 候选优先级。
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from ultrafast_knowledge.scientific.schemas import (
    KnowledgeConflict,
    KnowledgeGap,
    KnowledgeSummary,
    ScientificKnowledgeCandidate,
    ScientificKnowledgePack,
    SourceRef,
)
from ultrafast_knowledge.scientific_analysis.schemas import (
    LocalKnowledgeItem,
    SourceScientificAnalysis,
)

REDUCE_PROMPT = """你是超快激光加工领域的科学知识综合器。输入是多篇文献的【结构化局部分析】
（不是原文）。你的任务：
1. 合并同义知识（同一参数/同一关系/同一数值）；
2. 计数多文献支持（supporting_sources 必须列出所有支持文献）；
3. 对齐条件（material / laser / wavelength / pulse width 等）；
4. 发现跨文献冲突（相同 topic 的不同结论）；
5. 综合机制（跨文献解释）；
6. 识别 Knowledge Gap（缺失的类别：threshold / spot size / thermal property 等）；
7. 给候选标注优先级（"high"/"medium"/"low"，写入 extraction_notes 的 "priority: high"）。

输出严格 JSON（不要输出 JSON 外的内容）：
{
  "candidates": [
    {
      "candidate_id": "KC-...",
      "type": "threshold",
      "property": "ablation_threshold",
      "value": 0.82, "unit": "J/cm2",
      "conditions": {"material_id": "sic", "wavelength_nm": 1030},
      "semantic_role": "property_constant",
      "supporting_sources": [{"paper_id": "P-045", "page": 6, "chunk_ids": ["..."]}],
      "extraction_notes": ["priority: high"]
    },
    {
      "candidate_id": "KC-...",
      "type": "parameter_effect",
      "parameter": "peak_fluence", "target": "depth_um", "relation": "positive",
      "supporting_sources": [{"paper_id": "P01"}, {"paper_id": "P02"}],
      "semantic_role": "observed_relation",
      "extraction_notes": ["priority: medium", "supported_by: 2 sources"]
    }
  ],
  "known": [{"claim": "...", "sources": [{"paper_id": "P01"}]}],
  "unknown": [{"topic": "thermal_diffusivity", "description": "...", "related_conditions": {}}],
  "conflicts": [{"topic": "roughness_fluence_relation", "positions": [{"paper_id": "P03", "claim": "..."}], "description": "..."}]
}

type ∈ parameter_value|parameter_range|parameter_effect|relative_importance|interaction|functional_shape|material_property|optical_property|threshold|formula|mechanism|reported_optimum|experimental_condition|historical_pattern|historical_model
semantic_role ∈ experimental_condition|scanned_range|reported_optimum|observed_relation|reported_result|control_value|property_constant|assumption
数值候选必须带 unit 与 supporting_sources；无法确认来源的不得输出。
"""


class LLMClientLike(Protocol):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict: ...


def render_analyses(analyses: list[SourceScientificAnalysis]) -> str:
    """结构化结果渲染（只读分析 JSON，不读原文）。"""
    blocks = []
    for analysis in analyses:
        blocks.append(
            json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False)[:12000]
        )
    return "\n\n".join(blocks)


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM returned no JSON object")
    return json.loads(match.group(0))


def item_to_ref(item: LocalKnowledgeItem) -> SourceRef:
    return SourceRef(
        paper_id=None,
        page=item.page,
        chunk_ids=item.chunk_ids,
    )


class GlobalSynthesizer:
    """Pass 2 执行器：跨文献综合（只读结构化分析）。"""

    def __init__(
        self,
        client: LLMClientLike,
        *,
        model: str = "unknown",
        temperature: float = 0.1,
        timeout: float = 120.0,
    ):
        self.client = client
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def synthesize(
        self,
        analyses: list[SourceScientificAnalysis],
        task_scope: dict[str, Any],
        corpus_pack_id: str,
    ) -> ScientificKnowledgePack:
        # 空语料/全部分析失败：不调用 LLM（避免对空输入产生不可解析输出）
        if not analyses:
            return ScientificKnowledgePack(
                knowledge_pack_id=f"kp-reduce-{corpus_pack_id[-12:]}",
                source_corpus_pack_id=corpus_pack_id,
                task_scope=task_scope,
                unknown=[
                    KnowledgeGap(
                        topic="no_corpus",
                        description="检索语料为空：当前材料/工艺组合在文献库中无匹配来源，无法提炼科学知识。",
                    )
                ],
                llm_model=self.model,
                prompt_version="global-reduce-v1",
            )
        rendered = render_analyses(analyses)
        try:
            response = self.client.chat(
                [
                    {"role": "system", "content": REDUCE_PROMPT},
                    {"role": "user", "content": rendered},
                ],
                temperature=self.temperature,
                timeout=self.timeout,
            )
            content = str(response.get("content") or response.get("message") or "")
            raw = _extract_json(content)
        except (ValueError, json.JSONDecodeError):
            # LLM 输出不可解析：不伪造知识，返回空包并如实标注
            return ScientificKnowledgePack(
                knowledge_pack_id=f"kp-reduce-{corpus_pack_id[-12:]}",
                source_corpus_pack_id=corpus_pack_id,
                task_scope=task_scope,
                unknown=[
                    KnowledgeGap(
                        topic="reduce_parse_failed",
                        description="全局综合输出无法解析（LLM 返回非 JSON），本次未提炼结构化知识。",
                    )
                ],
                llm_model=self.model,
                prompt_version="global-reduce-v1",
            )
        candidates = []
        for item in raw.get("candidates", []):
            if not isinstance(item, dict):
                continue
            try:
                candidates.append(ScientificKnowledgeCandidate(**item))
            except (TypeError, ValueError):
                continue
        return ScientificKnowledgePack(
            knowledge_pack_id=f"kp-reduce-{corpus_pack_id[-12:]}",
            source_corpus_pack_id=corpus_pack_id,
            task_scope=task_scope,
            candidates=candidates,
            known=[
                KnowledgeSummary(**item)
                for item in raw.get("known", [])
                if isinstance(item, dict)
            ],
            unknown=[
                KnowledgeGap(**item)
                for item in raw.get("unknown", [])
                if isinstance(item, dict)
            ],
            conflicts=[
                KnowledgeConflict(**item)
                for item in raw.get("conflicts", [])
                if isinstance(item, dict)
            ],
            llm_model=self.model,
            prompt_version="global-reduce-v1",
        )
