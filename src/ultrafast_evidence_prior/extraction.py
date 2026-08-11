"""Requirement×paper typed extraction with mechanical provenance validation."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import TypeAdapter, ValidationError

from ultrafast_evidence_prior.schemas import (
    ConditionProvenance,
    ConditionValidationState,
    EvidenceContent,
    EvidenceIRV2,
    ExtractionStatus,
    KnowledgeRequirementV1,
    ParameterEffectContent,
    ParameterRangeContent,
    ParameterValueContent,
    ProcessObservationContent,
    ReportedOptimumContent,
    ValidationState,
)
from ultrafast_knowledge.evidence_pipeline.schemas import EvidenceWindow, PaperCandidate
from ultrafast_shared.units import known_unit_tokens, normalize_unit

PROMPT_VERSION = "typed-evidence-extraction-v2"
EXTRACTION_SCHEMA_VERSION = "evidence-ir-v2"

SYSTEM_PROMPT = """You are a rigorous scientific evidence extractor.
Process exactly one knowledge requirement and one paper version per call.
Use only the supplied evidence windows. Never use general knowledge, never combine
different papers, never infer an unstated numeric value, and never convert units.

Important transfer rule: a paper whose material grade, wavelength, pulse width, or
equipment differs from the task may still contain useful evidence. Do not reject it
for a condition mismatch. Extract the direct claim and record only conditions that
the cited text or PAPER_CONTEXT explicitly supports; downstream E2P assesses transfer.
Every returned condition is mechanically checked against cited blocks or PAPER_CONTEXT.
Unsupported conditions remain unverified and cannot influence downstream applicability.

Every item must cite existing block IDs and include a short verbatim evidence_quote.
Copy evidence_quote character-for-character from the cited blocks. Never insert an
ellipsis or silently join text across blocks. If the quote spans adjacent blocks,
source_block_refs must contain every contributing block ID in reading order.
The content.evidence_type must be one of ALLOWED_EVIDENCE_TYPES. Return multiple items
when the paper directly supports multiple independent claims. Do not turn background
statements or cited-work summaries into this paper's experimental observation.

Return strict JSON only:
{
  "status": "FOUND|NOT_FOUND",
  "items": [
    {
      "content": {"evidence_type": "...", "...": "type-specific fields"},
      "conditions": {},
      "evidence_quote": "verbatim text",
      "source_block_refs": ["block-id"],
      "extraction_confidence": 0.0
    }
  ],
  "reason": null
}

Type-specific content fields:
- PARAMETER_VALUE: parameter, value, unit, statement
- PARAMETER_RANGE: parameter, lower, upper, unit, statement
- PROCESS_OBSERVATION: statement, target_metric|null, measured_value|null, unit|null
- PARAMETER_EFFECT: parameter, target_metric, direction, threshold_value|null,
  lower|null, upper|null, unit|null, statement; direction is
  INCREASES|DECREASES|NON_MONOTONIC|OPTIMUM|THRESHOLD|NO_CLEAR_EFFECT|UNKNOWN
- MECHANISM: mechanism, statement
- PROCESS_METHOD: method, statement
- MATERIAL_IDENTITY: material, material_grade|null, statement
- REPORTED_OPTIMUM: target_metric, statement, parameters; each parameter contains
  parameter, value|null, lower|null, upper|null, unit

Use canonical condition keys when present: material, material_grade, wavelength_nm,
pulse_width_fs, pulse_width_min_fs, pulse_width_max_fs, frequency_kHz,
scan_speed_mm_s, hatch_spacing_um, fluence_J_cm2, average_power_W, passes,
process_type, laser_type, target_metric. Unknown conditions must be omitted.
"""


class LLMClientLike(Protocol):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]: ...


@dataclass
class PaperExtractionOutcome:
    status: ExtractionStatus
    items: list[EvidenceIRV2]
    reason: str | None = None
    llm_call_count: int = 1


class TypedEvidenceExtractor:
    def __init__(
        self,
        client: LLMClientLike,
        *,
        model: str,
        max_windows: int = 8,
        timeout: float = 180.0,
        max_attempts: int = 2,
        max_tokens: int = 3500,
    ) -> None:
        self.client = client
        self.model = model
        self.max_windows = max_windows
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.max_tokens = max_tokens
        self._content_adapter = TypeAdapter(EvidenceContent)

    def extract(
        self,
        requirement: KnowledgeRequirementV1,
        candidate: PaperCandidate,
        windows: list[EvidenceWindow],
    ) -> PaperExtractionOutcome:
        selected = windows[: self.max_windows]
        if not selected:
            return PaperExtractionOutcome(
                status=ExtractionStatus.NOT_FOUND,
                items=[],
                reason="no_evidence_windows",
                llm_call_count=0,
            )
        first = self._extract_once(requirement, candidate, selected)
        if self.max_attempts == 1 or not _retryable(first):
            return first
        retry = self._extract_once(
            requirement,
            candidate,
            selected,
            correction=_retry_correction(first),
        )
        retry.llm_call_count += first.llm_call_count
        if retry.items or retry.status == ExtractionStatus.FOUND:
            return retry
        first.llm_call_count = retry.llm_call_count
        first.reason = "; ".join(
            value for value in (first.reason, f"retry:{retry.reason}") if value
        )
        return first

    def _extract_once(
        self,
        requirement: KnowledgeRequirementV1,
        candidate: PaperCandidate,
        selected: list[EvidenceWindow],
        *,
        correction: str | None = None,
    ) -> PaperExtractionOutcome:
        request_options: dict[str, Any] = {
            "temperature": 0,
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if str(getattr(self.client, "provider", "")).casefold() == "deepseek":
            request_options["thinking"] = {"type": "disabled"}
        response = self.client.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._render(requirement, selected, correction=correction),
                },
            ],
            **request_options,
        )
        content = str(response.get("content") or response.get("message") or "")
        try:
            raw = _json_object(content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return PaperExtractionOutcome(
                status=ExtractionStatus.FAILED,
                items=[],
                reason=f"invalid_llm_json:{exc}",
            )
        status = str(raw.get("status") or "").upper()
        if status == ExtractionStatus.NOT_FOUND.value:
            return PaperExtractionOutcome(
                status=ExtractionStatus.NOT_FOUND,
                items=[],
                reason=str(raw.get("reason") or "not_found"),
            )
        raw_items = raw.get("items")
        if status != ExtractionStatus.FOUND.value or not isinstance(raw_items, list):
            return PaperExtractionOutcome(
                status=ExtractionStatus.FAILED,
                items=[],
                reason="invalid_extraction_envelope",
            )
        items: list[EvidenceIRV2] = []
        parse_errors: list[str] = []
        for index, raw_item in enumerate(raw_items):
            try:
                items.append(
                    self._build_item(
                        requirement,
                        candidate,
                        selected,
                        dict(raw_item),
                    )
                )
            except (TypeError, ValueError, ValidationError) as exc:
                parse_errors.append(f"item_{index}:{exc}")
        if not items:
            return PaperExtractionOutcome(
                status=ExtractionStatus.FAILED,
                items=[],
                reason="; ".join(parse_errors) or "found_without_items",
            )
        reason = "; ".join(parse_errors) if parse_errors else None
        return PaperExtractionOutcome(status=ExtractionStatus.FOUND, items=items, reason=reason)

    def _build_item(
        self,
        requirement: KnowledgeRequirementV1,
        candidate: PaperCandidate,
        windows: list[EvidenceWindow],
        raw: dict[str, Any],
    ) -> EvidenceIRV2:
        evidence_content = self._content_adapter.validate_python(raw.get("content"))
        refs = [str(value) for value in raw.get("source_block_refs") or []]
        quote = str(raw.get("evidence_quote") or "").strip()
        conditions = dict(raw.get("conditions") or {})
        try:
            confidence = float(raw.get("extraction_confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        available = {block.block_id: block for window in windows for block in window.blocks}
        cited = [available[ref] for ref in refs if ref in available]
        paper_metadata = windows[0].paper_metadata if windows else {}
        condition_provenance = _condition_provenance(
            conditions,
            refs,
            available,
            paper_metadata,
        )
        errors = self._validate(
            requirement,
            evidence_content,
            refs,
            quote,
            available,
        )
        payload = {
            "requirement_id": requirement.requirement_id,
            "paper_id": candidate.paper_id,
            "document_version_id": candidate.document_version_id,
            "content": evidence_content.model_dump(mode="json"),
            "conditions": conditions,
            "quote": quote,
            "refs": refs,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:20]
        return EvidenceIRV2(
            evidence_id=f"evidence-{digest}",
            requirement_id=requirement.requirement_id,
            paper_id=candidate.paper_id,
            document_version_id=candidate.document_version_id,
            paper_title=windows[0].paper_title if windows else "",
            paper_metadata=windows[0].paper_metadata if windows else {},
            content=evidence_content,
            conditions=conditions,
            condition_provenance=condition_provenance,
            evidence_quote=quote,
            source_block_refs=refs,
            source_pages=sorted({block.page for block in cited}),
            extraction_confidence=confidence,
            validation_state=(ValidationState.REJECTED if errors else ValidationState.VALIDATED),
            validation_errors=errors,
            governance_status="unreviewed",
            extraction_route="llm_extraction",
            extractor_model=self.model,
            prompt_version=PROMPT_VERSION,
        )

    @staticmethod
    def _validate(
        requirement: KnowledgeRequirementV1,
        content: EvidenceContent,
        refs: list[str],
        quote: str,
        available: dict[str, Any],
    ) -> list[str]:
        errors: list[str] = []
        if content.evidence_type not in requirement.evidence_types:
            errors.append(f"evidence_type_not_allowed:{content.evidence_type}")
        if not refs:
            errors.append("missing_source_block_refs")
        unknown = [ref for ref in refs if ref not in available]
        if unknown:
            errors.append(f"unknown_source_block_refs:{','.join(unknown)}")
        cited_blocks = [available[ref].text for ref in refs if ref in available]
        cited_text = "\n".join(cited_blocks)
        if not quote:
            errors.append("missing_evidence_quote")
        elif not cited_text or _space_normalize(quote) not in _space_normalize(cited_text):
            errors.append("evidence_quote_not_verbatim")
        for value, unit in _numeric_claims(content):
            if not cited_blocks:
                continue
            if unit is None:
                if not any(_number_present(value, text) for text in cited_blocks):
                    errors.append(f"numeric_value_not_in_cited_blocks:{value}")
                continue
            if normalize_unit(unit)[0] is None:
                errors.append(f"unsupported_claim_unit:{unit}")
                continue
            if not any(_numeric_unit_claim_present(value, unit, text) for text in cited_blocks):
                errors.append(f"numeric_unit_not_co_located_or_compatible:{value}:{unit}")
        if isinstance(content, ParameterRangeContent) and content.lower > content.upper:
            errors.append("invalid_parameter_range")
        if isinstance(content, ReportedOptimumContent):
            for setting in content.parameters:
                if (
                    setting.lower is not None
                    and setting.upper is not None
                    and setting.lower > setting.upper
                ):
                    errors.append(f"invalid_optimum_range:{setting.parameter}")
        return list(dict.fromkeys(errors))

    @staticmethod
    def _render(
        requirement: KnowledgeRequirementV1,
        windows: list[EvidenceWindow],
        *,
        correction: str | None = None,
    ) -> str:
        requirement_json = json.dumps(
            requirement.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        rendered = [
            f"KNOWLEDGE_REQUIREMENT\n{requirement_json}",
            "ALLOWED_EVIDENCE_TYPES\n"
            + json.dumps(
                [value.value for value in requirement.evidence_types],
                ensure_ascii=False,
            ),
            "EVIDENCE_WINDOWS",
        ]
        rendered.extend(
            f"WINDOW {window.window_id} score={window.score}\n{window.render()}"
            for window in windows
        )
        if correction:
            rendered.append(f"RETRY_CORRECTION\n{correction}")
        return "\n\n".join(rendered)


def _json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if match is None:
            raise ValueError("LLM returned no JSON object")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise TypeError("LLM result must be a JSON object")
    return value


def _numeric_claims(content: EvidenceContent) -> list[tuple[float, str | None]]:
    if isinstance(content, ParameterValueContent):
        return [(content.value, content.unit)]
    if isinstance(content, ParameterRangeContent):
        return [(content.lower, content.unit), (content.upper, content.unit)]
    if isinstance(content, ProcessObservationContent) and content.measured_value is not None:
        return [(content.measured_value, content.unit)]
    if isinstance(content, ParameterEffectContent):
        values = [
            value
            for value in (content.threshold_value, content.lower, content.upper)
            if value is not None
        ]
        return [(value, content.unit) for value in values]
    if isinstance(content, ReportedOptimumContent):
        values: list[tuple[float, str | None]] = []
        for setting in content.parameters:
            for value in (setting.value, setting.lower, setting.upper):
                if value is not None:
                    values.append((value, setting.unit))
        return values
    return []


_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")
_LOCAL_EXPRESSION_LIMIT = 64
_CLAUSE_BOUNDARY_RE = re.compile(r"[.!?;。！？；]")


def _number_mentions(text: str) -> list[tuple[float, int, int]]:
    values: list[tuple[float, int, int]] = []
    for match in _NUMBER_RE.finditer(_canonical_text(text)):
        try:
            values.append(
                (
                    float(match.group(0).replace(",", ".")),
                    match.start(),
                    match.end(),
                )
            )
        except ValueError:
            continue
    return values


def _numbers(text: str) -> list[float]:
    return [value for value, _start, _end in _number_mentions(text)]


def _number_present(expected: float, text: str) -> bool:
    return any(
        math.isclose(expected, candidate, rel_tol=1e-6, abs_tol=1e-12)
        for candidate in _numbers(text)
    )


def _canonical_text(value: str) -> str:
    return (
        unicodedata.normalize("NFKC", value)
        .replace("μ", "u")
        .replace("µ", "u")
        .replace("²", "2")
        .replace("^", "")
        .replace("−", "-")
    )


def _unit_token_pattern(token: str) -> str:
    parts: list[str] = []
    for character in token:
        if character == "/":
            parts.append(r"\s*/\s*")
        elif character == "2":
            parts.append(r"\s*2")
        else:
            parts.append(re.escape(character))
    return "".join(parts)


_UNIT_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])(?:"
    + "|".join(
        _unit_token_pattern(token)
        for token in known_unit_tokens()
        if token != "1"
    )
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _unit_mentions(text: str) -> list[tuple[str, float, int, int]]:
    normalized_text = _canonical_text(text).casefold()
    output: list[tuple[str, float, int, int]] = []
    for match in _UNIT_TOKEN_RE.finditer(normalized_text):
        normalized, factor = normalize_unit(match.group(0))
        if normalized is not None and factor is not None:
            output.append((normalized, factor, match.start(), match.end()))
    return output


def _unit_present(unit: str, text: str) -> bool:
    expected, _factor = normalize_unit(unit)
    return expected is not None and any(
        normalized == expected for normalized, _value, _start, _end in _unit_mentions(text)
    )


def _numeric_unit_claim_present(expected_value: float, expected_unit: str, text: str) -> bool:
    expected_dimension, expected_factor = normalize_unit(expected_unit)
    if expected_dimension is None or expected_factor is None:
        return False
    expected_canonical = float(expected_value) * expected_factor
    normalized_text = _canonical_text(text)
    for candidate, number_start, number_end in _number_mentions(text):
        for dimension, factor, unit_start, unit_end in _unit_mentions(text):
            if dimension != expected_dimension:
                continue
            candidate_canonical = candidate * factor
            if not math.isclose(
                expected_canonical,
                candidate_canonical,
                rel_tol=1e-6,
                abs_tol=1e-12,
            ):
                continue
            gap_start = min(number_end, unit_end)
            gap_end = max(number_start, unit_start)
            gap = normalized_text[gap_start:gap_end]
            if len(gap) <= _LOCAL_EXPRESSION_LIMIT and not _CLAUSE_BOUNDARY_RE.search(gap):
                return True
    return False


def _space_normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).translate(
        str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
    )
    normalized = re.sub(r"(?<=[0-9A-Za-z])-\s+(?=[0-9A-Za-z])", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _retryable(outcome: PaperExtractionOutcome) -> bool:
    if outcome.status == ExtractionStatus.FAILED:
        return True
    return bool(outcome.items) and not any(
        item.validation_state == ValidationState.VALIDATED for item in outcome.items
    )


def _retry_correction(outcome: PaperExtractionOutcome) -> str:
    errors = list(
        dict.fromkeys(error for item in outcome.items for error in item.validation_errors)
    )
    failure = outcome.reason or ", ".join(errors) or "mechanical_validation_failed"
    return (
        f"The previous attempt failed: {failure}. Produce a fresh strict JSON response. "
        "For each item, copy one short evidence_quote exactly from the rendered block text; "
        "do not paraphrase or use ellipses. Cite every block contributing text to that quote. "
        "If no mechanically groundable item exists, return NOT_FOUND."
    )


_CONDITION_UNITS = {
    "wavelength_nm": "nm",
    "laser_wavelength_nm": "nm",
    "pulse_width_fs": "fs",
    "pulse_duration_fs": "fs",
    "pulse_width_min_fs": "fs",
    "pulse_width_max_fs": "fs",
    "frequency_kHz": "kHz",
    "repetition_rate_kHz": "kHz",
    "scan_speed_mm_s": "mm/s",
    "hatch_spacing_um": "um",
    "fluence_J_cm2": "J/cm2",
    "average_power_W": "W",
}


def _condition_provenance(
    conditions: dict[str, Any],
    refs: list[str],
    available: dict[str, Any],
    paper_metadata: dict[str, Any],
) -> dict[str, ConditionProvenance]:
    cited_text = "\n".join(available[ref].text for ref in refs if ref in available)
    output: dict[str, ConditionProvenance] = {}
    for key, value in conditions.items():
        if cited_text and _condition_supported_in_text(key, value, cited_text):
            output[key] = ConditionProvenance(
                source="BLOCK",
                source_block_refs=[ref for ref in refs if ref in available],
                validation_state=ConditionValidationState.VALIDATED,
                reason_codes=["condition_value_present_in_cited_blocks"],
            )
            continue
        if key in paper_metadata and _condition_values_equal(value, paper_metadata[key]):
            output[key] = ConditionProvenance(
                source="PAPER_METADATA",
                validation_state=ConditionValidationState.VALIDATED,
                reason_codes=["condition_matches_paper_metadata"],
            )
            continue
        output[key] = ConditionProvenance(
            source="UNRESOLVED",
            validation_state=ConditionValidationState.UNVERIFIED,
            reason_codes=["condition_not_grounded_in_cited_blocks_or_metadata"],
        )
    return output


def _condition_supported_in_text(key: str, value: Any, text: str) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        unit = _CONDITION_UNITS.get(key)
        if unit is not None:
            return _numeric_unit_claim_present(float(value), unit, text)
        return _number_present(float(value), text)
    if isinstance(value, dict):
        numeric_values = [
            item
            for item in value.values()
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        ]
        return bool(numeric_values) and all(
            _condition_supported_in_text(key, item, text) for item in numeric_values
        )
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_condition_supported_in_text(key, item, text) for item in value)
    expected = _semantic_normalize(str(value))
    actual = _semantic_normalize(text)
    aliases = {expected}
    if key in {"target_metric", "target"}:
        aliases.update(
            {
                "depth" if expected in {"depth um", "depth"} else expected,
                "roughness" if expected in {"roughness um", "roughness"} else expected,
            }
        )
    if key in {"laser_type", "pulse_regime"}:
        if expected == "fs":
            aliases.add("femtosecond")
        elif expected == "ps":
            aliases.add("picosecond")
    return any(alias and alias in actual for alias in aliases)


def _condition_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=1e-6, abs_tol=1e-12)
    return _semantic_normalize(str(left)) == _semantic_normalize(str(right))


def _semantic_normalize(value: str) -> str:
    canonical = _canonical_text(value).casefold().replace("_", " ")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", canonical).strip()
