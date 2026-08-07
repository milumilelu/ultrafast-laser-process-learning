"""LLM 语义角色裁决：candidate mentions → semantic roles。

- 无 LLM / 无 Key：一律 abstain（role=unknown），不做规则猜测；
- LLM 输出经严格解析：非法 role → unknown；未提及的候选 → unknown；
- 返回的 role 只回写匹配的候选（按索引），杜绝凭空新增候选。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from ultrafast_knowledge.literature.extraction.registry import LASER_ALIASES, PROCESS_ALIASES
from ultrafast_knowledge.literature.extraction.schemas import (
    MaterialMention,
    MaterialRole,
    ProcessMention,
    ProcessRole,
)

ROLE_PROMPT = """你是文献元数据抽取器。你的任务是判定给定论文中材料/工艺候选的语义角色，
以及补充激光体制、波长、脉宽、材料牌号、加工对象。严格遵守：

1. 只依据论文原文判定，禁止编造。
2. 不确定、论文未说明 → 一律输出 "unknown"（允许 unknown，禁止猜）。
3. material_roles 的 key 是候选索引（论文在输入中列出），只能使用给定索引，不能新增。
4. 角色枚举（材料）：primary_workpiece(本文主加工工件) / substrate(基体) / coating(涂层)
   / reinforcement(增强相/增强材料) / comparison_material(对比材料) / tool_material(工具材料)
   / background_only(仅背景提及，如参考文献、概述) / unknown
5. 角色枚举（工艺）：primary_process(本文主工艺) / pretreatment(预处理) / postprocess(后处理)
   / comparison_process(对比工艺) / background_only / unknown
6. laser_type: fs / ps / ns / uv / unknown（"ultrafast/超快"不含具体体制时 = unknown）
7. wavelength_nm: 数字或 null；pulse_width: {"value": 数字, "unit": "fs|ps|ns", "evidence": 原文} 或 null
8. material_grade: 材料牌号字典 {"<canonical_material_id>": "牌号原文"}，没有则为空对象 {}
9. geometry: lens / circular_hole / rectangular_groove / single_line / surface_texture /
   wafer / plate / sheet / film / unknown

只输出一个 JSON 对象，不要输出任何其他文字。"""


def _build_input(paper_title: str, sections: list[dict[str, Any]], material_candidates: list[MaterialMention], process_candidates: list[ProcessMention]) -> str:
    parts: list[str] = []
    for index, mention in enumerate(material_candidates):
        parts.append(
            f"材料候选 [{index}]: canonical={mention.canonical_material_id} raw={mention.raw_text!r} "
            f"section={mention.section_type or 'unknown'} page={mention.page or '?'}"
        )
    for index, mention in enumerate(process_candidates):
        parts.append(
            f"工艺候选 [M{index}]: canonical={mention.canonical_process_id} raw={mention.raw_text!r} "
            f"section={mention.section_type or 'unknown'} page={mention.page or '?'}"
        )
    text_parts = []
    for section in sections[:24]:
        snippet = (section.get("text") or "").replace("\n", " ")[:1500]
        text_parts.append(f"[{section.get('section_type') or 'unknown'} p{section.get('page_start')}] {snippet}")
    joined_text = "\n\n".join(text_parts)
    return (
        f"论文标题: {paper_title or 'unknown'}\n\n"
        f"候选列表:\n" + "\n".join(parts) + f"\n\n论文正文（截断）:\n{joined_text}"
    )


def _parse_role_mapping(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[int, str]:
    raw = payload.get(keys[0]) or {}
    mapping: dict[int, str] = {}
    if not isinstance(raw, dict):
        return mapping
    for key, value in raw.items():
        match = re.fullmatch(r"[M]?(\d+)", str(key))
        if match:
            mapping[int(match.group(1))] = str(value).strip().lower()
    return mapping


def apply_llm_roles(
    material_candidates: list[MaterialMention],
    process_candidates: list[ProcessMention],
    payload: dict[str, Any],
) -> dict[str, Any]:
    material_roles = _parse_role_mapping(payload, ("material_roles",))
    for index, mention in enumerate(material_candidates):
        role = material_roles.get(index, "unknown")
        if role == "unknown":
            continue
        if role in {str(item.value) for item in MaterialRole}:
            mention.role = MaterialRole(role)
            mention.extraction_method = "llm"
            mention.confidence = 0.85
    process_roles = _parse_role_mapping(payload, ("process_roles",))
    for index, mention in enumerate(process_candidates):
        role = process_roles.get(index, "unknown")
        if role == "unknown":
            continue
        if role in {str(item.value) for item in ProcessRole}:
            mention.role = ProcessRole(role)
            mention.extraction_method = "llm"
            mention.confidence = 0.85
    return payload


def _normalize_laser(value: Any) -> str:
    if value in (None, "", "unknown"):
        return ""
    return LASER_ALIASES.get(str(value).strip().lower(), "")


def _normalize_process(value: Any) -> str:
    if value in (None, "", "unknown"):
        return ""
    return PROCESS_ALIASES.get(str(value).strip().lower(), "")


def extract_llm_fields(payload: dict[str, Any]) -> dict[str, Any]:
    laser_type = _normalize_laser(payload.get("laser_type"))
    wavelength = payload.get("wavelength_nm")
    pulse_width = payload.get("pulse_width")
    grades = payload.get("material_grade") or {}
    geometry = str(payload.get("geometry") or "").strip().lower()
    fields: dict[str, Any] = {
        "laser_type": laser_type,
        "wavelength_nm": None,
        "pulse_width": None,
        "material_grade": {},
        "geometry": geometry if geometry and geometry != "unknown" else "",
    }
    if isinstance(wavelength, (int, float)) and not isinstance(wavelength, bool) and wavelength > 0:
        fields["wavelength_nm"] = float(wavelength)
    if isinstance(pulse_width, dict) and pulse_width.get("value") not in (None, ""):
        try:
            value = float(pulse_width["value"])
            unit = str(pulse_width.get("unit") or "").lower()
            if value > 0 and unit in {"fs", "ps", "ns"}:
                fields["pulse_width"] = {
                    "value": value,
                    "unit": unit,
                    "raw_evidence": str(pulse_width.get("evidence") or ""),
                }
        except (TypeError, ValueError):
            pass
    if isinstance(grades, dict):
        fields["material_grade"] = {str(k): str(v) for k, v in grades.items() if v}
    return fields


def run_llm_role_extraction(
    client: Any,
    *,
    paper_title: str,
    sections: list[dict[str, Any]],
    material_candidates: list[MaterialMention],
    process_candidates: list[ProcessMention],
    timeout_seconds: int = 90,
    max_attempts: int = 3,
    temperature: float | None = None,
) -> tuple[dict[str, Any], dict[str, int], str]:
    """调用 LLM 裁决角色与字段。

    返回 (payload, usage, error_info)：
    - payload: 通过严格响应校验的 JSON 对象；失败为 {}
    - usage: 所有尝试的 token usage 累计（重试不低估成本）
    - error_info: 最后一次失败原因（异常类型 / unparseable / 校验失败详情）

    瞬时失败（限流/超时/输出截断/契约违反）自动重试 max_attempts 次（指数退避）；
    重试耗尽后 abstain（允许 unknown，禁止猜），绝不使用 mock。
    """
    prompt = _build_input(paper_title, sections, material_candidates, process_candidates)
    last_error = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    chat_kwargs: dict[str, Any] = {"timeout_seconds": timeout_seconds}
    if temperature is not None:
        chat_kwargs["temperature"] = temperature
    for attempt in range(max_attempts):
        try:
            response = client.chat(
                [
                    {"role": "system", "content": ROLE_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                **chat_kwargs,
            )
            content = (response or {}).get("content") or ""
            raw = (response or {}).get("raw") or {}
            if isinstance(raw.get("usage"), dict):
                for key in usage:
                    value = raw["usage"].get(key)
                    if isinstance(value, (int, float)):
                        usage[key] += int(value)
            payload = _parse_json_object(content)
            if isinstance(payload, dict):
                validation_error = _validate_llm_payload(
                    payload,
                    n_materials=len(material_candidates),
                    n_processes=len(process_candidates),
                )
                if validation_error is None:
                    return payload, usage, ""
                last_error = f"schema violation: {validation_error}"
            else:
                last_error = "unparseable response"
        except Exception as exc:  # noqa: BLE001 — 瞬时失败重试；耗尽后 abstain（允许 unknown，禁止猜）
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < max_attempts - 1:
            time.sleep(2 * (attempt + 1))
    return {}, usage, last_error


LLM_RESPONSE_FIELDS = frozenset(
    {"laser_type", "wavelength_nm", "pulse_width", "material_grade", "geometry", "material_roles", "process_roles"}
)
MATERIAL_ROLE_VALUES = frozenset(str(item.value) for item in MaterialRole)
PROCESS_ROLE_VALUES = frozenset(str(item.value) for item in ProcessRole)
LASER_TYPE_VALUES = frozenset({"fs", "ps", "ns", "uv", "unknown"})
GEOMETRY_VALUES = frozenset(
    {"lens", "circular_hole", "rectangular_groove", "single_line", "surface_texture",
     "wafer", "plate", "sheet", "film", "custom", "unknown"}
)


def _validate_llm_payload(payload: dict[str, Any], *, n_materials: int, n_processes: int) -> str | None:
    """严格响应契约校验；返回错误描述或 None（通过）。

    - 顶层字段白名单（禁止未知键）
    - 必需字段存在
    - material_roles / process_roles：key 必须在候选索引范围，value 必须是合法 role 枚举
    - laser_type / geometry：枚举白名单（unknown 允许）
    - wavelength_nm：数字或 null；pulse_width：{value, unit} 形状或 null
    - material_grade：dict[str, str]
    """
    unknown_keys = set(payload) - LLM_RESPONSE_FIELDS
    if unknown_keys:
        return f"unknown top-level keys: {sorted(unknown_keys)}"
    for field in ("laser_type", "wavelength_nm", "pulse_width", "material_grade", "geometry", "material_roles", "process_roles"):
        if field not in payload:
            return f"missing required field: {field}"
    if not isinstance(payload["material_roles"], dict):
        return "material_roles must be an object"
    if not isinstance(payload["process_roles"], dict):
        return "process_roles must be an object"
    for key, value in payload["material_roles"].items():
        if not re.fullmatch(r"\d+", str(key)):
            return f"material_roles key out of range: {key!r}"
        if int(key) >= n_materials:
            return f"material_roles key exceeds candidate count: {key}"
        if str(value).strip().lower() not in MATERIAL_ROLE_VALUES:
            return f"invalid material role value: {value!r}"
    for key, value in payload["process_roles"].items():
        if not re.fullmatch(r"M?\d+", str(key)):
            return f"process_roles key out of range: {key!r}"
        index = int(str(key).lstrip("M"))
        if index >= n_processes:
            return f"process_roles key exceeds candidate count: {key}"
        if str(value).strip().lower() not in PROCESS_ROLE_VALUES:
            return f"invalid process role value: {value!r}"
    if str(payload["laser_type"]).strip().lower() not in LASER_TYPE_VALUES:
        return f"invalid laser_type: {payload['laser_type']!r}"
    wavelength = payload["wavelength_nm"]
    if wavelength is not None and (not isinstance(wavelength, (int, float)) or isinstance(wavelength, bool)):
        return f"wavelength_nm must be number or null: {wavelength!r}"
    pulse = payload["pulse_width"]
    if pulse is not None:
        if not isinstance(pulse, dict) or "value" not in pulse or "unit" not in pulse:
            return f"pulse_width must be {{value, unit}} or null: {pulse!r}"
        try:
            float(pulse["value"])
        except (TypeError, ValueError):
            return f"pulse_width.value must be numeric: {pulse!r}"
        if str(pulse.get("unit", "")).lower() not in {"fs", "ps", "ns"}:
            return f"pulse_width.unit must be fs/ps/ns: {pulse!r}"
    if not isinstance(payload["material_grade"], dict):
        return "material_grade must be an object"
    if str(payload["geometry"]).strip().lower() not in GEOMETRY_VALUES:
        return f"invalid geometry: {payload['geometry']!r}"
    return None


def _parse_json_object(content: str) -> dict[str, Any] | None:
    cleaned = content.strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
