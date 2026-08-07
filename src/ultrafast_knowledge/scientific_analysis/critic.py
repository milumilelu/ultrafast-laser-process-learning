"""Pass 3: Selective Critic（文档第七、八节）。

- 只审核"后续科学影响"大的候选（threshold / formula / reported optimum /
  material property 必须；parameter effect/value 建议；background 跳过）；
- 按需回原文取证：Candidate + source_refs → 取回小块证据窗口（不读全语料）。

Critic 判定写回候选 extraction_notes（critic: pass / critic: issue: ...），
不自动拒绝（最终由确定性 Validator 与治理层决定）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from ultrafast_knowledge.corpus.schemas import EvidenceCorpusPack
from ultrafast_knowledge.scientific.schemas import (
    ScientificKnowledgeCandidate,
    ScientificKnowledgePack,
)
from ultrafast_knowledge.scientific_analysis.schemas import critic_priority

CRITIC_PROMPT = """你是超快激光加工领域的科学批判检查器。逐条检查以下知识候选是否可信。
每条候选附带【原文证据窗口】（对应来源的小块文本）。检查：
1. 数值是否与原文一致（单位、量级、fs/ps、kHz/MHz、radius/diameter）；
2. 实验扫描范围是否被误判为最优范围；
3. 条件（材料/激光/波长/脉宽）是否与任务匹配；
4. 跨材料是否错误迁移；
5. citation 是否真的支持 claim；
6. 是否缺少关键实验条件（如 spot size）。

输出严格 JSON（不要输出 JSON 外的内容）：
{"issues": [{"candidate_id": "...", "code": "fs_ps_confusion|unit_mismatch|range_vs_optimum|scope_mismatch|citation_mismatch|missing_condition", "message": "...", "severity": "error"|"warning"}]}
没有问题的候选不输出。
"""


class LLMClientLike(Protocol):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict: ...


@dataclass(slots=True)
class CriticConfig:
    timeout: float = 90.0
    context_chars_per_ref: int = 1200
    max_refs_per_candidate: int = 2


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM returned no JSON object")
    return json.loads(match.group(0))


def _evidence_window(
    candidate: ScientificKnowledgeCandidate,
    pack: EvidenceCorpusPack,
    config: CriticConfig,
) -> str:
    """按需取证：candidate.source_refs → 语料中对应 chunk 的小块证据窗口。"""
    windows: list[str] = []
    refs = candidate.supporting_sources[: config.max_refs_per_candidate]
    for ref in refs:
        chunk_ids = set(ref.chunk_ids or [])
        for source in pack.sources:
            for section in source.sections:
                if not (chunk_ids & set(section.chunk_ids)):
                    continue
                text = str(section.text or "")[: config.context_chars_per_ref]
                if text:
                    windows.append(
                        f"[paper={ref.paper_id or source.paper_id} p.{ref.page or section.page}] {text}"
                    )
                break
    return "\n".join(windows) if windows else "(no evidence window found in corpus)"


class SelectiveCritic:
    """Pass 3 执行器：只审核高风险候选，按需取证。"""

    def __init__(
        self,
        client: LLMClientLike,
        *,
        model: str = "unknown",
        temperature: float = 0.0,
        config: CriticConfig | None = None,
    ):
        self.client = client
        self.model = model
        self.temperature = temperature
        self.config = config or CriticConfig()

    def select_candidates(
        self, pack: ScientificKnowledgePack
    ) -> list[ScientificKnowledgeCandidate]:
        """按类型分级选择（required / recommended 入选；skipped 跳过）。"""
        return [
            candidate
            for candidate in pack.candidates
            if critic_priority(candidate.type) != "skipped"
        ]

    def criticize(
        self,
        pack: ScientificKnowledgePack,
        corpus: EvidenceCorpusPack,
        emit=None,
    ) -> dict[str, int]:
        """对入选候选执行批判；issue 写回 extraction_notes。

        emit(stage, detail) 每审核一个候选回调一次进度。
        """
        selected = self.select_candidates(pack)
        reviewed = 0
        issues_total = 0
        for candidate in selected:
            window = _evidence_window(candidate, corpus, self.config)
            payload = {
                "candidate": candidate.model_dump(mode="json"),
                "evidence_window": window,
            }
            try:
                response = self.client.chat(
                    [
                        {"role": "system", "content": CRITIC_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=self.temperature,
                    timeout=self.config.timeout,
                )
                content = str(response.get("content") or response.get("message") or "")
                raw = _extract_json(content)
                issues = [item for item in raw.get("issues", []) if isinstance(item, dict)]
            except (ValueError, json.JSONDecodeError):
                issues = []
            reviewed += 1
            if not issues:
                candidate.extraction_notes.append("critic: pass")
            else:
                issues_total += len(issues)
                for issue in issues:
                    candidate.extraction_notes.append(
                        f"critic: {issue.get('severity', 'warning')}: {issue.get('message') or issue.get('code')}"
                    )
            if emit is not None:
                emit("criticizing", {"current": reviewed, "total": len(selected), "candidate_id": candidate.candidate_id})
        return {"criticized_candidates": reviewed, "issues_found": issues_total}
