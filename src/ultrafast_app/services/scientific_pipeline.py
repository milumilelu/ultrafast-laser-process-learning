"""Scientific Analysis 编排（Composition Root）。

执行链：Map（单 Source 单次 LLM，并发 3~4，可缓存）→ Deterministic Validation
→ Coverage Check → Reduce（只读结构化结果）→ Selective Critic（按需取证）。
LLM 科学精读强制真实 LLM —— 不提供确定性 mock 降级；无 LLM 配置时明确报错。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ultrafast_knowledge.corpus.schemas import EvidenceCorpusPack
from ultrafast_knowledge.scientific.schemas import (
    ScientificKnowledgeCandidate,
    ScientificKnowledgePack,
    ValidationResult,
)
from ultrafast_knowledge.scientific.validator import (
    DeterministicScientificValidator,
    default_source_checker,
)
from ultrafast_knowledge.scientific_analysis.cache import SQLiteSourceAnalysisCache
from ultrafast_knowledge.scientific_analysis.service import (
    PipelineConfig,
    ScientificKnowledgeService,
)
from ultrafast_memory.core.ids import stable_id
from ultrafast_memory.db.session import get_connection
from ultrafast_memory.llm.factory import create_llm_client
from ultrafast_memory.llm.mock import MockLLMClient


class LLMNotConfiguredError(ValueError):
    """LLM 未配置：科学精读不提供 mock 降级。"""


def build_llm_client() -> Any:
    """构建真实 LLM client；未配置时抛 LLMNotConfiguredError（不降级）。"""
    from ultrafast_memory.core.llm_config import get_llm_config, restore_api_key_from_store

    # 服务重启后环境变量丢失：先从 DPAPI 存储恢复 Key
    restore_api_key_from_store()
    config = get_llm_config()
    client = create_llm_client(config)
    if isinstance(client, MockLLMClient):
        raise LLMNotConfiguredError(
            "LLM 未配置或 Key 不可用：科学精读需要真实 LLM（Agent 侧边栏 → 配置 → 保存并测试连接）。"
        )
    return client


class ScientificAnalysisService:
    def __init__(
        self,
        client: Any | None = None,
        connection: Any = None,
        *,
        level: str = "E2P_STRICT",
    ):
        self.connection = connection or get_connection
        self.validator = DeterministicScientificValidator(
            source_checker=default_source_checker(self.connection)
        )
        if client is None:
            client = build_llm_client()
        if isinstance(client, MockLLMClient):
            raise LLMNotConfiguredError(
                "LLM 未配置或 Key 不可用：科学精读需要真实 LLM（Agent 侧边栏 → 配置 → 保存并测试连接）。"
            )
        self.client = client
        self.level = level
        self.pipeline = ScientificKnowledgeService(
            client,
            config=PipelineConfig(level=level),
            cache=SQLiteSourceAnalysisCache(self.connection),
            validator=self.validator,
        )

    def analyze(self, pack: EvidenceCorpusPack) -> dict[str, Any]:
        """完整执行链（Map → Validate → Coverage → Reduce → Selective Critic）。"""
        return self.pipeline.analyze(pack)

    def validate(self, knowledge: ScientificKnowledgePack) -> ValidationResult:
        return self.validator.validate(knowledge)

    def persist(
        self,
        knowledge: ScientificKnowledgePack,
        validation: ValidationResult,
    ) -> dict[str, Any]:
        """candidate 落库（knowledge_candidate）+ 审核任务（knowledge_review_task）。"""
        return self.persist_static(self.connection, knowledge, validation)

    @staticmethod
    def persist_static(
        connection: Any,
        knowledge: ScientificKnowledgePack,
        validation: ValidationResult,
    ) -> dict[str, Any]:
        """静态落库入口（Job worker 使用，不依赖实例构造的 LLM client）。"""
        persisted: list[str] = []
        review_ids: list[str] = []
        with connection() as conn:
            for candidate in knowledge.candidates:
                if candidate.candidate_id in validation.rejected_candidates:
                    continue
                persisted.append(candidate.candidate_id)
                claim = _render_claim_static(candidate)
                source_refs = [
                    {
                        "paper_id": ref.paper_id,
                        "page": ref.page,
                        "chunk_ids": ref.chunk_ids,
                        "knowledge_id": ref.knowledge_id,
                    }
                    for ref in candidate.supporting_sources
                ]
                conn.execute(
                    "INSERT OR IGNORE INTO knowledge_candidate "
                    "(candidate_id, source_id, claim, material, process_type, "
                    "parameter_json, condition_json, evidence_type, confidence, "
                    "status, review_status, risk_level, suggested_action) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        candidate.candidate_id,
                        source_refs[0].get("paper_id") if source_refs else None,
                        claim,
                        (candidate.conditions or {}).get("material_id"),
                        (candidate.conditions or {}).get("process_type"),
                        json.dumps(
                            {
                                "parameter": candidate.parameter,
                                "value": candidate.value,
                                "lower": candidate.lower,
                                "upper": candidate.upper,
                                "unit": candidate.unit,
                                "expression": candidate.expression,
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(candidate.conditions, ensure_ascii=False),
                        f"llm_extraction:{candidate.type.value}",
                        candidate.confidence,
                        "candidate",
                        "pending_review",
                        "medium",
                        json.dumps(
                            {
                                "sources": source_refs,
                                "semantic_role": candidate.semantic_role.value,
                                "llm_extraction": candidate.llm_extraction,
                                "extraction_notes": candidate.extraction_notes,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                review_id = stable_id("review", candidate.candidate_id, uuid.uuid4().hex)
                review_ids.append(review_id)
                conn.execute(
                    "INSERT OR IGNORE INTO knowledge_review_task "
                    "(review_id, candidate_id, review_status, priority, risk_level, "
                    "auto_suggestion) VALUES (?,?,?,?,?,?)",
                    (
                        review_id,
                        candidate.candidate_id,
                        "pending_review",
                        "normal",
                        "medium",
                        "scientific_analyst_extraction",
                    ),
                )
            conn.commit()
        return {
            "persisted_candidate_ids": persisted,
            "review_ids": review_ids,
            "rejected_candidate_ids": validation.rejected_candidates,
        }

    @staticmethod
    def _render_claim(candidate: ScientificKnowledgeCandidate) -> str:
        return _render_claim_static(candidate)


def _render_claim_static(candidate: ScientificKnowledgeCandidate) -> str:
    parts = []
    if candidate.type.value:
        parts.append(f"[{candidate.type.value}]")
    if candidate.parameter:
        parts.append(candidate.parameter)
    value_parts = []
    if candidate.value is not None:
        value_parts.append(str(candidate.value))
    if candidate.lower is not None and candidate.upper is not None:
        value_parts.append(f"{candidate.lower}..{candidate.upper}")
    if value_parts and candidate.unit:
        value_parts[-1] = f"{value_parts[-1]} {candidate.unit}"
    if value_parts:
        parts.append("=" + " ".join(value_parts))
    if candidate.relation:
        parts.append(f"relation:{candidate.relation}")
    return " ".join(parts)
