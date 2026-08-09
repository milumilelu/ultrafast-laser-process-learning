"""One-requirement-per-call scientific extraction and deterministic validation."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Any, Protocol

from ultrafast_knowledge.evidence_pipeline.schemas import (
    EvidenceWindow,
    ExtractionStatus,
    RequirementEvidence,
)
from ultrafast_requirements.schemas import Requirement
from ultrafast_shared.units import normalize_unit

PROMPT_VERSION = "requirement-extraction-v2"

REQUIREMENT_EXTRACTION_PROMPT = """你是严谨的科学证据抽取器。本次只回答一个 Requirement。
不得抽取无关参数，不得用常识补全，不得换算原文单位，不得把引用文献列表当作实验结果。
必须先核对 PAPER_CONTEXT 与 Requirement.conditions：论文材料、激光类型或其他必要条件
不一致时返回 NOT_FOUND。FOUND 的 conditions 必须逐项包含 Requirement.conditions 且值一致。
PAPER_CONTEXT 只用于条件判定；evidence_quote 仍必须逐字来自带 block_id 的原文块。

状态只能是：
- FOUND：证据窗口直接报告该量；
- NOT_FOUND：窗口没有直接证据；
- CONFLICT：至少两个窗口对同一适用条件报告不一致值。

source_block_refs 只能引用输入中给出的 block_id。evidence_quote 必须是原文中的短片段。
conditions 只填写原文明确支持的条件。confidence 是 0 到 1。
输出严格 JSON，不输出解释或 Markdown：
{
  "status": "FOUND|NOT_FOUND|CONFLICT",
  "value": null,
  "lower": null,
  "upper": null,
  "unit": null,
  "conditions": {},
  "semantic_role": null,
  "source_block_refs": [],
  "confidence": 0.0,
  "conflict_values": [{
    "value": null, "lower": null, "upper": null, "unit": null,
    "conditions": {}, "source_block_refs": []
  }],
  "evidence_quote": null
}
"""


class LLMClientLike(Protocol):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]: ...


def _json_object(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError("LLM returned no JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise TypeError("LLM result must be a JSON object")
    return data


def _condition_value(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return value


class RequirementEvidenceValidator:
    """Rules validate numbers, units and provenance; they do not assign semantics."""

    def validate(
        self,
        requirement: Requirement,
        result: RequirementEvidence,
        windows: list[EvidenceWindow],
    ) -> RequirementEvidence:
        errors: list[str] = []
        available_blocks = {
            block.block_id: block
            for window in windows
            for block in window.blocks
        }
        invalid_refs = [ref for ref in result.source_block_refs if ref not in available_blocks]
        if invalid_refs:
            errors.append(f"unknown_source_block_refs:{','.join(invalid_refs)}")
        if result.status == ExtractionStatus.FOUND:
            if not result.source_block_refs:
                errors.append("found_without_source_block_refs")
            if result.value is None and result.lower is None and result.upper is None:
                errors.append("found_without_value_or_range")
            if not result.evidence_quote:
                errors.append("found_without_evidence_quote")
            if requirement.expected_unit and not result.unit:
                errors.append("found_without_unit")
            errors.extend(self._validate_required_conditions(requirement, result, windows))
        if result.status == ExtractionStatus.CONFLICT:
            if len(result.conflict_values) < 2:
                errors.append("conflict_without_two_values")
            errors.extend(
                self._validate_conflict_values(
                    requirement,
                    result.conflict_values,
                    available_blocks,
                )
            )
        if result.status == ExtractionStatus.NOT_FOUND and (
            result.value is not None or result.lower is not None or result.upper is not None
        ):
            errors.append("not_found_contains_value")
        if result.status == ExtractionStatus.INSUFFICIENT:
            errors.append("insufficient_is_reserved_for_cross_paper_reduce")

        cited_text = "\n".join(
            available_blocks[ref].text
            for ref in result.source_block_refs
            if ref in available_blocks
        )
        for value in (result.value, result.lower, result.upper):
            if value is not None and cited_text and not self._number_present(float(value), cited_text):
                errors.append(f"numeric_value_not_in_cited_blocks:{value}")
        if result.evidence_quote and cited_text:
            quote = self._space_normalize(result.evidence_quote)
            if quote not in self._space_normalize(cited_text):
                errors.append("evidence_quote_not_verbatim")
        if result.unit:
            actual, _ = normalize_unit(self._canonical_unit(result.unit))
            expected, _ = normalize_unit(self._canonical_unit(requirement.expected_unit))
            if actual is None:
                errors.append(f"unrecognized_unit:{result.unit}")
            elif expected is not None and actual != expected:
                errors.append(f"unit_dimension_mismatch:{result.unit}:{requirement.expected_unit}")
            if cited_text and not self._unit_present(result.unit, cited_text):
                errors.append(f"unit_not_in_cited_blocks:{result.unit}")
        unique_errors = list(dict.fromkeys(errors))
        return result.model_copy(
            update={
                "validation_errors": unique_errors,
                "validation_state": "rejected" if unique_errors else "validated",
            }
        )

    @staticmethod
    def _validate_required_conditions(
        requirement: Requirement,
        result: RequirementEvidence,
        windows: list[EvidenceWindow],
    ) -> list[str]:
        errors: list[str] = []
        metadata = windows[0].paper_metadata if windows else {}
        for key, expected in requirement.conditions.items():
            if key not in result.conditions:
                errors.append(f"found_missing_required_condition:{key}")
            elif _condition_value(result.conditions[key]) != _condition_value(expected):
                errors.append(f"found_condition_mismatch:{key}")
            if key in metadata and _condition_value(metadata[key]) != _condition_value(expected):
                errors.append(f"paper_context_condition_mismatch:{key}")
        return errors

    def _validate_conflict_values(
        self,
        requirement: Requirement,
        conflicts: list[dict[str, Any]],
        available_blocks: dict[str, Any],
    ) -> list[str]:
        errors: list[str] = []
        for index, conflict in enumerate(conflicts):
            refs = conflict.get("source_block_refs")
            if not isinstance(refs, list) or not refs:
                errors.append(f"conflict_{index}_without_source_block_refs")
                continue
            unknown = [str(ref) for ref in refs if str(ref) not in available_blocks]
            if unknown:
                errors.append(f"conflict_{index}_unknown_refs:{','.join(unknown)}")
                continue
            cited = "\n".join(available_blocks[str(ref)].text for ref in refs)
            values = [conflict.get(name) for name in ("value", "lower", "upper")]
            if all(value is None for value in values):
                errors.append(f"conflict_{index}_without_value_or_range")
            for value in values:
                if value is not None and not self._number_present(float(value), cited):
                    errors.append(f"conflict_{index}_numeric_value_not_cited:{value}")
            unit = conflict.get("unit")
            if requirement.expected_unit and not unit:
                errors.append(f"conflict_{index}_without_unit")
            elif unit:
                actual, _ = normalize_unit(self._canonical_unit(str(unit)))
                expected, _ = normalize_unit(self._canonical_unit(requirement.expected_unit))
                if actual is None or (expected is not None and actual != expected):
                    errors.append(f"conflict_{index}_unit_mismatch:{unit}")
                if not self._unit_present(str(unit), cited):
                    errors.append(f"conflict_{index}_unit_not_cited:{unit}")
        return errors

    @staticmethod
    def _numbers(text: str) -> list[float]:
        values: list[float] = []
        for raw in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?", text):
            try:
                values.append(float(raw.replace(",", ".")))
            except ValueError:
                continue
        return values

    def _number_present(self, expected: float, text: str) -> bool:
        return any(
            math.isclose(expected, candidate, rel_tol=1e-6, abs_tol=1e-12)
            for candidate in self._numbers(text)
        )

    @staticmethod
    def _canonical_unit(unit: str | None) -> str | None:
        if unit is None:
            return None
        return (
            unicodedata.normalize("NFKC", unit)
            .replace("μ", "u")
            .replace("µ", "u")
            .replace("²", "2")
            .replace("^", "")
            .replace("−", "-")
        )

    def _unit_present(self, unit: str, text: str) -> bool:
        expected = re.sub(r"\s+", "", self._canonical_unit(unit) or "").lower()
        actual = re.sub(r"\s+", "", self._canonical_unit(text) or "").lower()
        return expected in actual

    @staticmethod
    def _space_normalize(text: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


class RequirementEvidenceExtractor:
    def __init__(
        self,
        client: LLMClientLike,
        *,
        model: str = "unknown",
        max_windows: int = 8,
        timeout: float = 90.0,
        validator: RequirementEvidenceValidator | None = None,
    ) -> None:
        if not 1 <= max_windows <= 10:
            raise ValueError("max_windows must be between 1 and 10")
        self.client = client
        self.model = model
        self.max_windows = max_windows
        self.timeout = timeout
        self.validator = validator or RequirementEvidenceValidator()

    def extract(
        self,
        requirement: Requirement,
        windows: list[EvidenceWindow],
    ) -> RequirementEvidence:
        selected = windows[: self.max_windows]
        if not selected:
            return RequirementEvidence(
                requirement_id=requirement.requirement_id,
                quantity=requirement.quantity,
                status=ExtractionStatus.NOT_FOUND,
                validation_errors=[],
                validation_state="validated",
            )
        prompt = self._render(requirement, selected)
        response = self.client.chat(
            [
                {"role": "system", "content": REQUIREMENT_EXTRACTION_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            timeout=self.timeout,
            response_format={"type": "json_object"},
        )
        content = str(response.get("content") or response.get("message") or "")
        raw = _json_object(content)
        result = RequirementEvidence(
            requirement_id=requirement.requirement_id,
            quantity=requirement.quantity,
            prompt_version=PROMPT_VERSION,
            **{
                key: value
                for key, value in raw.items()
                if key in RequirementEvidence.model_fields
                and key not in {"requirement_id", "quantity", "prompt_version"}
            },
        )
        return self.validator.validate(requirement, result, selected)

    @staticmethod
    def _render(requirement: Requirement, windows: list[EvidenceWindow]) -> str:
        requirement_json = json.dumps(
            {
                "requirement_id": requirement.requirement_id,
                "quantity": requirement.quantity,
                "role": requirement.role,
                "expected_unit": requirement.expected_unit,
                "conditions": requirement.conditions,
                "resolution_policy": requirement.resolution_policy,
                "query_terms": requirement.query_terms,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        rendered = [f"REQUIREMENT\n{requirement_json}", "EVIDENCE WINDOWS"]
        for window in windows:
            rendered.append(
                f"WINDOW {window.window_id} score={window.score}\n{window.render()}"
            )
        return "\n\n".join(rendered)
