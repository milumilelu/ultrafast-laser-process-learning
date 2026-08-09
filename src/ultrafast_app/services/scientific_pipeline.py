"""Composition root for requirement compilation and scientific evidence extraction."""

from __future__ import annotations

from typing import Any

from ultrafast_knowledge.evidence_pipeline import (
    PersistentScientificPaperRepository,
    RequirementEvidenceExtractor,
    RequirementEvidencePipeline,
    ScientificIndexStore,
)
from ultrafast_memory.llm.factory import create_llm_client
from ultrafast_memory.llm.mock import MockLLMClient
from ultrafast_requirements import RequirementCompiler, RequirementSet


class LLMNotConfiguredError(ValueError):
    """A real semantic extractor is mandatory for scientific evidence."""


def build_llm_client() -> Any:
    from ultrafast_memory.core.llm_config import get_llm_config, restore_api_key_from_store

    restore_api_key_from_store()
    client = create_llm_client(get_llm_config())
    if isinstance(client, MockLLMClient):
        raise LLMNotConfiguredError(
            "LLM 未配置或 Key 不可用：按需求的科学证据抽取需要真实 LLM。"
        )
    return client


class ScientificAnalysisService:
    """Task → dependency closure → requirements → evidence windows → EvidenceIR."""

    def __init__(self, client: Any | None = None, *, connection: Any = None) -> None:
        self.client = client or build_llm_client()
        if isinstance(self.client, MockLLMClient):
            raise LLMNotConfiguredError("科学证据抽取不允许 mock 降级。")
        self.compiler = RequirementCompiler()
        store = ScientificIndexStore(connection=connection)
        repository = PersistentScientificPaperRepository(store)
        extractor = RequirementEvidenceExtractor(
            self.client,
            model=str(getattr(self.client, "model", "unknown")),
        )
        self.pipeline = RequirementEvidencePipeline(
            extractor,
            repository=repository,
            store=store,
        )

    def compile_requirements(
        self,
        task_spec: dict[str, Any],
        available_quantities: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> RequirementSet:
        return self.compiler.compile(task_spec, available_quantities)

    def analyze(
        self,
        task_spec: dict[str, Any],
        available_quantities: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        requirements = self.compile_requirements(task_spec, available_quantities)
        evidence = self.pipeline.analyze(requirements)
        return {
            "requirement_set": requirements.model_dump(mode="json"),
            "evidence_run": evidence.model_dump(mode="json"),
        }
