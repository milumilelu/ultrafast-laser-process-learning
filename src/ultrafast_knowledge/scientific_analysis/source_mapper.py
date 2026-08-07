"""Pass 1: Source Map（文档第二节）。

每个 Source 独立、单次 LLM 调用（Extraction + Local Interpretation 合并）：
    输入 = TaskScope + RetrievalIntent + 1 source + 必要章节
    输出 = SourceScientificAnalysis（固定结构 JSON）

并发 3~4（配置化）；单 Source 失败重试（指数退避），不影响其他 Source。
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Protocol

from ultrafast_knowledge.corpus.schemas import CorpusSource, EvidenceCorpusPack
from ultrafast_knowledge.scientific_analysis.schemas import (
    SourceAnalysisStatus,
    SourceScientificAnalysis,
)

SOURCE_MAP_PROMPT = """你是超快激光加工领域的科学文献局部精读器。对【这一篇文献】做局部科学分析，
只做 Extraction + Local Interpretation，不做跨文献综合。

必须回答：
- 发现了什么？（参数/数值/单位/范围/目标）
- 这个数字是什么语义？（experimental_condition / scanned_range / reported_optimum / observed_relation / reported_result / control_value / property_constant / assumption）
- 它对应什么条件？（material / laser / wavelength / pulse width / geometry / process）
- 作者报告了什么关系？（parameter → target，positive/negative/non_monotonic）
- 作者给出的解释是什么？（mechanism，写进 explanation 字段）
- 这篇文献缺少什么？（knowledge_gaps，如 spot size / threshold / thermal property）

输出严格 JSON（不要输出 JSON 外的内容）：
{
  "experimental_conditions": [{"item_id": "P01-cond-1", "type": "experimental_condition", "parameter": "laser_power_W", "value": 20.0, "unit": "W", "conditions": {"material_id": "sic"}, "semantic_role": "experimental_condition", "page": 3, "chunk_ids": ["..."], "extraction_notes": ["..."]}],
  "parameter_values": [],
  "parameter_ranges": [{"item_id": "...", "type": "parameter_range", "parameter": "scan_speed_mm_s", "lower": 50.0, "upper": 500.0, "unit": "mm/s", "semantic_role": "scanned_range", "page": 5}],
  "parameter_effects": [{"item_id": "...", "type": "parameter_effect", "parameter": "scan_speed_mm_s", "target": "depth_um", "relation": "negative", "conditions": {}, "semantic_role": "observed_relation", "page": 7, "explanation": "higher speed reduces energy per length"}],
  "material_properties": [],
  "thresholds": [{"item_id": "...", "type": "threshold", "property": "ablation_threshold", "value": 0.82, "unit": "J/cm2", "conditions": {"material_id": "sic", "wavelength_nm": 1030}, "semantic_role": "property_constant", "page": 6}],
  "formulas": [{"item_id": "...", "type": "formula", "name": "gaussian_peak_fluence", "expression": "F0 = 2*Ep/(pi*w0^2)", "variables": {"Ep": "pulse_energy_J", "w0": "beam_radius_m"}, "assumptions": ["gaussian_spatial_profile"], "page": 4}],
  "mechanisms": [{"item_id": "...", "type": "mechanism", "name": "heat_accumulation", "explanation": "...", "page": 8}],
  "interactions": [],
  "reported_optima": [{"item_id": "...", "type": "reported_optimum", "parameter": "frequency_kHz", "lower": 90.0, "upper": 110.0, "unit": "kHz", "semantic_role": "reported_optimum", "page": 9}],
  "knowledge_gaps": [{"type": "missing_experimental_condition", "field": "spot_radius", "description": "...", "search_hints": ["spot size", "beam waist", "diameter"]}],
  "internal_conflicts": [],
  "source_refs": []
}

type ∈ parameter_value|parameter_range|parameter_effect|relative_importance|interaction|functional_shape|material_property|optical_property|threshold|formula|mechanism|reported_optimum|experimental_condition|historical_pattern|historical_model
单位保留原文单位字符串，禁止换算。数值不明确时 lower/upper 用 null，value 用 null。
"""


class LLMClientLike(Protocol):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict: ...


@dataclass(slots=True)
class MapperConfig:
    concurrency: int = 3
    per_call_timeout: float = 90.0
    max_retries: int = 2
    section_text_limit: int = 1500
    max_sections_per_source: int = 6


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM returned no JSON object")
    return json.loads(match.group(0))


def render_source(
    source: CorpusSource,
    task_scope: dict[str, Any],
    config: MapperConfig,
) -> str:
    """单 Source 渲染（TaskScope + Intent 上下文 + 必要章节，不超 budget）。"""
    parts = [
        (
            f"TASK SCOPE: material={task_scope.get('material')} laser={task_scope.get('laser_type')} "
            f"geometry={task_scope.get('geometry_type') or task_scope.get('process_type')} target={task_scope.get('target')}"
        ),
        f"SOURCE {source.source_id} paper={source.paper_id} title={source.title}",
    ]
    for section in source.sections[: config.max_sections_per_source]:
        text = str(section.text or "")[: config.section_text_limit]
        if not text.strip():
            continue
        parts.append(f"[{section.section_type} p.{section.page}] {text}")
    return "\n\n".join(parts)


class SourceMapper:
    """Pass 1 执行器：并发 Map（单 Source 单次调用）。"""

    def __init__(
        self,
        client: LLMClientLike,
        *,
        config: MapperConfig | None = None,
        model: str = "unknown",
        temperature: float = 0.1,
    ):
        self.client = client
        self.config = config or MapperConfig()
        self.model = model
        self.temperature = temperature

    def map_source(
        self,
        source: CorpusSource,
        task_scope: dict[str, Any],
    ) -> SourceScientificAnalysis:
        """单 Source 分析：一次 LLM 调用 + 指数退避重试。"""
        input_text = render_source(source, task_scope, self.config)
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.client.chat(
                    [
                        {"role": "system", "content": SOURCE_MAP_PROMPT},
                        {"role": "user", "content": input_text},
                    ],
                    temperature=self.temperature,
                    timeout=self.config.per_call_timeout,
                )
                content = str(response.get("content") or response.get("message") or "")
                raw = _extract_json(content)
                analysis = SourceScientificAnalysis(
                    source_id=source.source_id,
                    paper_id=source.paper_id,
                    title=source.title,
                    llm_model=self.model,
                    **{
                        key: value
                        for key, value in raw.items()
                        if key in SourceScientificAnalysis.model_fields
                    },
                )
                return analysis
            except Exception as exc:  # noqa: BLE001 - 单 Source 失败可重试
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(2**attempt * 0.5)
        return SourceScientificAnalysis(
            source_id=source.source_id,
            paper_id=source.paper_id,
            title=source.title,
            status=SourceAnalysisStatus.FAILED,
            error=str(last_error or "unknown error"),
            llm_model=self.model,
        )

    def map_corpus(
        self,
        pack: EvidenceCorpusPack,
        sources: list[CorpusSource] | None = None,
        on_source_done=None,
    ) -> list[SourceScientificAnalysis]:
        """并发 Map 全部（或指定）Source；单 Source 失败不阻断整体。

        on_source_done(current: int, total: int, analysis: SourceScientificAnalysis)
        在每完成一个 Source 时回调（进度事件，供 Job 展示分析摘要）。
        """
        sources = sources if sources is not None else pack.sources
        total = len(sources)
        analyses: list[SourceScientificAnalysis] = []
        completed_count = 0
        with ThreadPoolExecutor(max_workers=max(1, self.config.concurrency)) as executor:
            futures = {
                executor.submit(self.map_source, source, pack.task_scope): source
                for source in sources
            }
            for future in as_completed(futures):
                analysis = future.result()
                analyses.append(analysis)
                completed_count += 1
                if on_source_done is not None:
                    on_source_done(completed_count, total, analysis)
        return analyses
