from __future__ import annotations

from pathlib import Path
from typing import Any

from ultrafast_agent.runtime import ToolContract, ToolRegistry
from ultrafast_domain.process import ParameterValue
from ultrafast_knowledge.governance_bootstrap.service import (
    bootstrap_external_knowledge as bootstrap_service,
)
from ultrafast_knowledge.rag.parameter_recommendation import recommend_from_evidence
from ultrafast_knowledge.rag.query_service import query_rag
from ultrafast_memory.chat.session_state import get_session_state, update_session_state
from ultrafast_memory.core.ids import stable_id
from ultrafast_memory.core.time_utils import utc_now_iso
from ultrafast_memory.equipment.bounds import (
    PARAMETER_UNITS,
    build_machine_bounds,
    safety_bounds_from_equipment,
)
from ultrafast_memory.ingestion.pipeline import ingest_file
from ultrafast_memory.process_memory import ProcessMemorySearchService
from ultrafast_memory.reports.task_report_service import TaskReportService
from ultrafast_memory.topic2_gateway import Topic2ProcessGateway

TOOL_REGISTRY_VERSION = "v33-open-agent-human-governed-memory-1"


FOREGROUND_SAFE_TOOL_NAMES = {
    "get_equipment_context",
    "retrieve_process_memory",
    "search_knowledge",
    "recommend_process_parameters",
    "manage_trial",
    "manage_process",
    "record_process_result",
    "review_knowledge_item",
}
CORE_TOOL_NAMES = tuple(sorted(FOREGROUND_SAFE_TOOL_NAMES))
ON_DEMAND_TOOL_NAMES = ("bootstrap_external_knowledge", "ingest_files", "generate_report")
BASE_TOOL_NAMES = set(FOREGROUND_SAFE_TOOL_NAMES)


def build_main_agent_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    contracts = (
        _contract("get_equipment_context", "Read authoritative fixed equipment conditions and tunable capabilities.", _equipment, default=True, cache="equipment_revision"),
        _contract(
            "retrieve_process_memory",
            "Retrieve structured experiments, approved BO samples, validated rules, reviewed "
            "experience, and optional literature without forcing a fixed workflow.",
            _retrieve_process_memory,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "task_context": {"type": "object"},
                    "sources": {
                        "type": "array",
                        "items": {
                            "enum": [
                                "experiments",
                                "bo_samples",
                                "validated_rules",
                                "reviewed_experience",
                                "literature",
                            ]
                        },
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "purpose": {"type": "string"},
                    "filters": {"type": "object"},
                },
            },
        ),
        _contract(
            "search_knowledge",
            "Search purpose-governed internal evidence with review authority and citations.",
            _search,
            cache="turn",
        ),
        _contract(
            "recommend_process_parameters",
            "Select governed BO and/or reviewed RAG in the requested evidence order; never invent values.",
            _recommend_process_parameters,
            timeout=90_000,
            input_schema={
                "type": "object",
                "required": [
                    "task_context",
                    "process_plan",
                    "variables",
                    "equipment_context",
                ],
                "properties": {
                    "source_strategy": {
                        "enum": [
                            "auto",
                            "bo_only",
                            "rag_only",
                            "bo_first",
                            "rag_first",
                        ]
                    }
                },
            },
        ),
        _contract("recommend_parameters_bo", "Compute provenance-bearing process setpoints from validated matching BO samples.", _recommend_bo, timeout=60_000, required=("equipment_snapshot.tunable_capabilities",)),
        _contract(
            "recommend_parameters_rag",
            "Extract and equipment-check a conservative candidate from reviewed RAG evidence.",
            _recommend_rag,
            input_schema={"type": "object", "required": [
                "task_context", "process_plan", "variables", "equipment_context",
            ]},
        ),
        _contract(
            "manage_trial",
            "Manage the trial lifecycle. create accepts operation, trial_mode, representative_geometry, "
            "measurement_plan, acceptance_criteria, and stop_conditions; numeric parameter candidates "
            "are copied only from the latest allowed_for_trial parameter Tool Observation.",
            _manage_trial,
            side="domain_write",
            input_schema={"type": "object", "required": ["operation"]},
        ),
        _contract(
            "manage_process",
            "Manage formal processing. Formal parameter values come only from an unlocked measured trial; "
            "Planner-supplied parameter values are ignored.",
            _manage_process,
            side="domain_write",
            input_schema={"type": "object", "required": ["operation"]},
        ),
        _contract(
            "record_process_result",
            "Record supplied process facts and create human-review candidates without automatic promotion.",
            _record_result,
            side="domain_write",
            input_schema={
                "type": "object",                "properties": {
                    "result_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "recommendation_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "execution_id": {"type": "string"},
                    "machine_actual_parameters": {"type": "object"},
                    "measurements": {"type": "object"},
                    "measurement_method": {"type": "string"},
                    "quality_decision": {
                        "enum": ["PASS", "FAIL", "NEEDS_REVIEW"]
                    },
                    "validation_status": {"type": "string"},
                    "validated_by": {"type": "string"},
                    "defects": {"type": "array"},
                    "operator_note": {"type": "string"},
                    "attachments": {"type": "array"},
                },
            },
        ),
        _contract("bootstrap_external_knowledge", "Create review candidates from explicit external evidence.", _bootstrap, approval=True),
        _contract("ingest_files", "Ingest explicitly supplied supported files.", _ingest_files, side="artifact_write"),
        _contract("generate_report", "Generate a traceable task report as optional post-processing.", _generate_report, side="report_write"),
        _contract(
            "review_knowledge_item",
            "List pending unreviewed knowledge candidates used in the conversation, and apply "
            "human-confirmed review actions (approve/accept_to_rag/reject/needs_more_evidence/withdraw). "
            "Review actions are only executed after the user explicitly confirms them in the conversation.",
            _review_knowledge_item,
            side="domain_write",
            input_schema={
                "type": "object",
                "required": ["operation"],
                "properties": {
                    "operation": {
                        "enum": [
                            "list_pending",
                            "approve",
                            "accept_to_rag",
                            "reject",
                            "needs_more_evidence",
                            "withdraw",
                        ]
                    },
                    "review_id": {"type": "string"},
                    "reviewer_id": {"type": "string"},
                    "comment": {"type": "string"},
                    "target_level": {"type": "string"},
                },
            },
        ),
    )
    for contract in contracts:
        registry.register(contract)
    return registry


def _contract(name: str, purpose: str, handler: Any, *, timeout: int = 30_000,
              side: str = "none", approval: bool = False, default: bool = False,
              cache: str = "none", required: tuple[str, ...] = (),
              input_schema: dict[str, Any] | None = None) -> ToolContract:
    return ToolContract(
        name=name, purpose=purpose, handler=handler, timeout_ms=timeout,
        side_effect_level=side, requires_human_approval=approval,
        exposed_by_default=default, cache_policy=cache, requires_context=required,
        input_schema=input_schema or {},
    )


def _task(context: dict[str, Any]) -> dict[str, Any]:
    working = context.get("working_context") or {}
    return dict(working.get("task") or context.get("task_spec") or {})


def _legacy_task(
    context: dict[str, Any], task_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = dict(task_override or _task(context))
    material = task.get("material")
    geometry = task.get("geometry") or {}
    workpiece = task.get("workpiece") or {}
    return {
        **task,
        "material": material.get("name") if isinstance(material, dict) else material,
        "process_type": task.get("process_type") or task.get("process_intent")
        or task.get("task_type") or geometry.get("feature_type"),
        "objective": task.get("objective") or task.get("targets") or "process_quality",
        "thickness_mm": task.get("thickness_mm") or workpiece.get("thickness_mm")
        or geometry.get("workpiece_thickness_mm"),
    }


def _equipment(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    equipment = build_machine_bounds()
    return {
        "status": "success",
        "summary": "已分层读取设备固定条件与可调能力；可调范围只作为安全约束。",
        "active": equipment.get("active", False),
        "equipment_id": equipment.get("equipment_profile_id"),
        "equipment_profile_id": equipment.get("equipment_profile_id"),
        "profile_name": equipment.get("profile_name"),
        "revision": equipment.get("revision_id"),
        "revision_id": equipment.get("revision_id"),
        "fixed_conditions": dict(equipment.get("fixed_conditions") or {}),
        "tunable_capabilities": dict(equipment.get("tunable_capabilities") or {}),
        "missing_equipment_fields": list(equipment.get("missing_equipment_fields") or []),
    }


def _retrieve_process_memory(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Search heterogeneous memory while keeping authority levels separate."""
    source_selection = payload.get("sources")
    requested_sources = list(
        [
            "experiments",
            "bo_samples",
            "validated_rules",
            "reviewed_experience",
            "literature",
        ]
        if source_selection is None
        else source_selection
    )
    structured_sources = [name for name in requested_sources if name != "literature"]
    task = dict(payload.get("task_context") or _task(context))
    structured = ProcessMemorySearchService().search(
        task,
        sources=structured_sources,
        query=payload.get("query"),
        limit=int(payload.get("limit") or 5),
    )
    if structured.get("status") == "validation_error":
        return structured
    literature = None
    if "literature" in requested_sources:
        literature = _search(
            {
                "query": payload.get("query"),
                "task_context": task,
                "filters": payload.get("filters") or {},
                "purpose": payload.get("purpose") or "literature_background",
                "top_k": payload.get("top_k") or 8,
                "index_name": payload.get("index_name") or "literature_default",
            },
            context,
        )
    structured_total = sum((structured.get("source_counts") or {}).values())
    literature_total = int((literature or {}).get("hit_count") or 0)
    total = structured_total + literature_total
    return {
        "status": "success" if total else "insufficient_data",
        "summary": (
            f"共检索到 {total} 条历史数据、审核知识或文献证据。"
            if total
            else "未找到匹配记忆；Agent仍可形成明确标注假设的非数值方案。"
        ),
        "requested_sources": requested_sources,
        "structured_memory": structured,
        "literature_memory": literature,
        "authority_note": (
            "实验事实、BO样本、结构化规则和文献证据保持独立来源；"
            "检索命中不自动获得参数或正式加工权限。"
        ),
    }


def _search(
    payload: dict[str, Any], context: dict[str, Any], *, _include_full_hits: bool = False,
) -> dict[str, Any]:
    task = _legacy_task(context, payload.get("task_context"))
    query = str(payload.get("query") or " ".join(
        str(task.get(key) or "") for key in ("material", "process_type", "objective")
    )).strip()
    if not query:
        return {"status": "insufficient_data", "summary": "缺少可检索的任务描述。", "missing": ["query_or_task_context"]}
    purpose = str(payload.get("purpose") or "literature_background")
    filters = dict(payload.get("filters") or {})
    if task.get("material"):
        filters.setdefault("material", task["material"])
    if task.get("process_type"):
        filters.setdefault("process_type", task["process_type"])
    result = query_rag({
        "query": query,
        "top_k": int(payload.get("top_k") or 8),
        "filters": filters,
        "purpose": purpose,
        "index_name": str(payload.get("index_name") or "literature_default"),
        "session_id": context.get("session_id"),
    })
    hits = list(result.get("hits") or [])
    evidence_pack = {key: value for key, value in result.items() if key != "hits"}
    authorities = sorted({str(hit.get("authority_level")) for hit in hits})
    observation_hits = hits if _include_full_hits else [
        {
            key: (
                str(hit.get(key) or "")[:240]
                if key in {"content", "text"}
                else hit.get(key)
            )
            for key in (
                "chunk_id", "paper_id", "title", "section_type", "authority_level",
                "score", "rerank_score", "content", "text",
            )
            if hit.get(key) is not None
        }
        for hit in hits[:3]
        if isinstance(hit, dict)
    ]
    return {"status": "success", "summary": "内部知识检索完成。", "query": query,
            "purpose": purpose, "evidence_pack": evidence_pack,
            "hit_count": len(hits), "hits": observation_hits,
            "provenance": [{"source_type": "rag_evidence", "authority_levels": authorities}]}


def _bootstrap(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return bootstrap_service(task_spec=_legacy_task(context), question=payload.get("question"),
                             query_intent=str(payload.get("query_intent") or "find_literature_prior"),
                             max_sources=int(payload.get("max_sources") or 5))


def _parameter_result(*, status: str, parameters: dict[str, Any], source_type: str,
                      source_refs: list[Any] | None = None, data_support: dict[str, Any] | None = None,
                      uncertainty: dict[str, Any] | None = None, limitations: list[str] | None = None,
                      evidence_level: str = "unknown", equipment: dict[str, Any] | None = None,
                      variables: list[str] | None = None, authority_level: str | None = None,
                      strategy_parameters: dict[str, Any] | None = None,
                      parameter_units: dict[str, str | None] | None = None,
                      parameter_details: dict[str, dict[str, Any]] | None = None,
                      validated: bool = False, allowed_for_trial: bool = True,
                      allowed_for_formal_process: bool = False,
                      allowed_for_bo_training: bool = False) -> dict[str, Any]:
    equipment = equipment or {}
    fixed = dict(equipment.get("fixed_conditions") or {})
    selected = list(dict.fromkeys(variables or list(parameters)))
    refs = [str(item) for item in (source_refs or [])]
    parameter_units = parameter_units or {}
    parameter_details = parameter_details or {}
    process_parameters: dict[str, dict[str, Any]] = {}
    for name in selected:
        if name in fixed or name not in parameters:
            continue
        value = parameters[name]
        if not isinstance(value, (int, float, str)):
            continue
        details = parameter_details.get(name) or {}
        parameter = ParameterValue(
            name=name,
            value=value,
            unit=details.get("unit") or PARAMETER_UNITS.get(name),
            role="process_setpoint",
            source_type=source_type,
            source_refs=[str(item) for item in details.get("source_refs") or refs],
            authority_level=str(
                details.get("authority_level") or authority_level or evidence_level
            ),
            uncertainty=dict(details.get("uncertainty") or uncertainty or {}),
            validated=validated,
            allowed_for_trial=allowed_for_trial,
            allowed_for_formal_process=allowed_for_formal_process,
            allowed_for_bo_training=allowed_for_bo_training,
        )
        process_parameters[name] = parameter.model_dump(mode="json")
    semantic_strategy_parameters: dict[str, dict[str, Any]] = {}
    for name, value in (strategy_parameters or {}).items():
        if not isinstance(value, (int, float, str)):
            continue
        details = parameter_details.get(name) or {}
        parameter = ParameterValue(
            name=name,
            value=value,
            unit=details.get("unit") or parameter_units.get(name) or PARAMETER_UNITS.get(name),
            role="strategy_parameter",
            source_type=source_type,
            source_refs=[str(item) for item in details.get("source_refs") or refs],
            authority_level=str(
                details.get("authority_level") or authority_level or evidence_level
            ),
            uncertainty=dict(details.get("uncertainty") or uncertainty or {}),
            validated=validated,
            allowed_for_trial=allowed_for_trial,
            allowed_for_formal_process=allowed_for_formal_process,
            allowed_for_bo_training=allowed_for_bo_training,
        )
        semantic_strategy_parameters[name] = parameter.model_dump(mode="json")
    return {
        "status": status,
        "fixed_equipment_conditions": fixed,
        "process_parameters": process_parameters,
        "strategy_parameters": semantic_strategy_parameters,
        "derived_metrics": {},
        "source_type": source_type,
        "source_refs": refs, "data_support": data_support or {},
        "evidence_level": evidence_level, "uncertainty": uncertainty or {},
        "authority_level": authority_level or evidence_level,
        "validated": validated,
        "allowed_for_trial": allowed_for_trial,
        "allowed_for_formal_process": allowed_for_formal_process,
        "allowed_for_bo_training": allowed_for_bo_training,
        "limitations": limitations or [],
        "recommended_use": (["trial"] if allowed_for_trial else [])
        + (["formal_process"] if allowed_for_formal_process else []),
        "provenance": [{"source_type": source_type, "source_refs": refs}],
    }


class RecommendationAuthorityPolicy:
    """Translate BO evidence into trial/formal authority without status inflation."""

    @staticmethod
    def assess(raw: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        mode = str(raw.get("model_status") or "blocked")
        readiness = raw.get("readiness_report") or {}
        metrics = readiness.get("validation_metrics") or {}
        matched = int(raw.get("sample_count") or 0)
        effective = int(readiness.get("complete_feature_count") or 0)
        uncertainty_calibrated = bool(readiness.get("uncertainty_calibrated"))
        model_validated = bool(metrics) and uncertainty_calibrated
        support = (
            "supported"
            if mode == "data_driven_bo" and raw.get("bo_invoked") and model_validated
            else "insufficient"
        )
        formal = support == "supported" and _verified_trial_unlocked(context)
        return {
            "support_status": support,
            "model_mode": mode,
            "matched_sample_count": matched,
            "effective_sample_count": effective,
            "context_match_score": 1.0 if matched else 0.0,
            "fidelity": "not_reported",
            "fidelity_level": "not_reported",
            "model_validation": metrics,
            "uncertainty_calibrated": uncertainty_calibrated,
            "validated": support == "supported",
            "allowed_for_trial": support != "insufficient",
            "allowed_for_formal_process": formal,
        }


def _topic2_gateway(context: dict[str, Any]) -> Topic2ProcessGateway:
    injected = context.get("_topic2_gateway")
    return injected if injected is not None else Topic2ProcessGateway()


def _recommend_bo(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    equipment = _normalize_equipment(
        payload.get("equipment_context") or _equipment_snapshot(context)
    )
    request = payload.get("topic2_optimization_request")
    if not isinstance(request, dict):
        return _parameter_result(
            status="insufficient_data",
            parameters={},
            source_type="bo",
            source_refs=[],
            data_support={
                "support_status": "insufficient",
                "model_mode": "topic2_contract_required",
                "validated": False,
            },
            uncertainty={},
            limitations=[
                (
                    "BO 只能由 Topic2 主应用执行；缺少 canonical "
                    "topic2_optimization_request，未调用旧版 sidecar BO。"
                )
            ],
            evidence_level="insufficient",
            authority_level="topic2_process_owner",
            equipment=equipment,
            variables=list(payload.get("variables") or []),
            validated=False,
            allowed_for_trial=False,
            allowed_for_formal_process=False,
        )
    forbidden = {"evidence", "prior_spec", "approved_priors"}.intersection(request)
    if forbidden:
        return {
            "status": "validation_error",
            "summary": "Topic2 BO 请求包含未治理 prior/evidence 字段。",
            "invalid_fields": sorted(forbidden),
            "allowed_for_trial": False,
            "allowed_for_formal_process": False,
        }
    raw = _topic2_gateway(context).recommend(request)
    parameters = dict(raw.get("recommended_parameters") or {})
    authority = {
        "support_status": "supported",
        "model_mode": "topic2_owned_bo",
        "matched_sample_count": None,
        "effective_sample_count": None,
        "context_match_score": 1.0,
        "model_validation": {},
        "uncertainty_calibrated": bool(raw.get("uncertainty")),
        "validated": True,
        "allowed_for_trial": True,
        "allowed_for_formal_process": _verified_trial_unlocked(context),
        "run_id": raw.get("run_id"),
        "recommendation_id": raw.get("recommendation_id"),
    }
    return _parameter_result(
        status="success",
        parameters=parameters, source_type="bo",
        source_refs=[str(raw["run_id"])] if raw.get("run_id") else [],
        data_support=authority,
        uncertainty=raw.get("uncertainty") or {}, limitations=list(raw.get("limitations") or []),
        evidence_level="supported",
        authority_level="topic2_owned_bo",
        equipment=equipment, variables=list(payload.get("variables") or parameters),
        validated=True,
        allowed_for_trial=True,
        allowed_for_formal_process=authority["allowed_for_formal_process"],
    )


def _recommend_process_parameters(
    payload: dict[str, Any], context: dict[str, Any],
) -> dict[str, Any]:
    """The sole foreground entrypoint; the model may choose an evidence strategy."""
    payload, normalization = _normalize_parameter_request(payload, context)
    trace: list[dict[str, Any]] = []
    if normalization:
        trace.append({"step": "request_normalization", **normalization})
    strategy = str(payload.get("source_strategy") or "auto")
    orders = {
        "auto": ("bo", "reviewed_rag"),
        "bo_only": ("bo",),
        "rag_only": ("reviewed_rag",),
        "bo_first": ("bo", "reviewed_rag"),
        "rag_first": ("reviewed_rag", "bo"),
    }
    if strategy not in orders:
        return {
            "status": "validation_error",
            "summary": f"不支持的参数证据策略：{strategy}",
            "supported_source_strategies": sorted(orders),
        }

    for source in orders[strategy]:
        try:
            candidate = (
                _recommend_bo(payload, context)
                if source == "bo"
                else _recommend_rag(payload, context)
            )
        except Exception as exc:  # noqa: BLE001 - another evidence source may remain usable
            trace.append(
                {
                    "step": f"{source}_parameter_recommendation",
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
            )
            continue
        if source == "bo":
            support = str(
                (candidate.get("data_support") or {}).get("support_status")
                or "insufficient"
            )
            trace.append(
                {
                    "step": "bo_parameter_recommendation",
                    "status": support,
                    "model_mode": str(
                        (candidate.get("data_support") or {}).get("model_mode")
                        or "blocked"
                    ),
                }
            )
            usable = support == "supported"
        else:
            usable = candidate.get("status") == "success" and bool(
                candidate.get("process_parameters")
            )
            trace.append(
                {
                    "step": "reviewed_rag_parameter_recommendation",
                    "status": (
                        "supported"
                        if usable
                        else str(candidate.get("status") or "insufficient_data")
                    ),
                }
            )
        if usable:
            result = _with_policy_trace(candidate, trace, source)
            result["source_strategy"] = strategy
            return _persist_parameter_recommendation(result, payload, context)

    return {
        "status": "insufficient_data",
        "summary": "所选 BO/RAG 证据策略未提供有来源的可用候选；未生成任何 LLM 数值。",
        "process_parameters": {},
        "strategy_parameters": {},
        "allowed_for_trial": False,
        "allowed_for_formal_process": False,
        "internal_trace": trace,
        "source_strategy": strategy,
        "policy_version": "bo-rag-no-invented-values-v1",
    }


def _persist_parameter_recommendation(
    result: dict[str, Any], payload: dict[str, Any], context: dict[str, Any],
) -> dict[str, Any]:
    """Expose ownership status without writing an Agent-side process database."""
    support = dict(result.get("data_support") or {})
    if result.get("selected_source") == "bo" and support.get("recommendation_id"):
        return {
            **result,
            "recommendation_id": support["recommendation_id"],
            "recommendation_status": "ready_for_trial",
            "persistence_status": "persisted_by_topic2",
        }
    return {
        **result,
        "persistence_status": "observation_only",
        "persistence_warnings": [
            "Agent 仅保留本轮证据观察；正式推荐只由 Topic2 主应用持久化。"
        ],
    }


def _normalize_parameter_request(
    payload: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Repair request structure only; never infer task-domain meaning."""
    normalized = dict(payload)
    normalized["task_context"] = dict(payload.get("task_context") or _task(context))
    equipment = _normalize_equipment(
        payload.get("equipment_context") or _equipment_snapshot(context)
    )
    normalized["equipment_context"] = equipment
    process_plan = dict(payload.get("process_plan") or {})
    declared = _declared_process_variable_roles(process_plan)
    requested = list(dict.fromkeys(
        str(name) for name in (payload.get("variables") or []) if str(name)
    ))
    tunable = set((equipment.get("tunable_capabilities") or {}).keys())
    dropped: list[str] = []
    injected: list[str] = []
    if declared:
        selected = [name for name in (requested or list(declared)) if name in declared]
        dropped = [name for name in requested if name not in declared]
    else:
        selected = [name for name in requested if name in tunable]
        dropped = [name for name in requested if name not in tunable]
        if selected:
            process_plan["controllable_variables"] = [
                {"name": name, "role": "process_setpoint"} for name in selected
            ]
            injected = list(selected)
    normalized["process_plan"] = process_plan
    normalized["variables"] = selected
    details = {
        "status": "normalized",
        "injected_process_setpoints": injected,
        "dropped_undeclared_variables": dropped,
    }
    return normalized, details if injected or dropped else {}


def _with_policy_trace(
    result: dict[str, Any], trace: list[dict[str, Any]], selected_source: str,
) -> dict[str, Any]:
    return {
        **result,
        "selected_source": selected_source,
        "internal_trace": trace,
        "policy_version": "bo-rag-no-invented-values-v1",
    }


def _verified_trial_unlocked(context: dict[str, Any]) -> bool:
    working = context.get("working_context") or {}
    for item in reversed(list(working.get("observations") or [])):
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict):
            continue
        decision = data.get("formal_process_decision") or {}
        if decision.get("unlocked") is True or data.get("formal_process_unlocked") is True:
            return True
    return False


def _recommend_rag(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    process_plan = payload.get("process_plan") or {}
    variables = list(dict.fromkeys(map(str, payload.get("variables") or [])))
    roles = _declared_process_variable_roles(process_plan)
    invalid = [name for name in variables if name not in roles]
    if not variables or invalid:
        return {
            "status": "validation_error",
            "summary": "variables 必须由当前 ProcessPlan 明确选择。",
            "invalid_variables": invalid,
        }
    equipment = _normalize_equipment(
        payload.get("equipment_context") or _equipment_snapshot(context)
    )
    fixed = set((equipment.get("fixed_conditions") or {}).keys())
    if any(name in fixed for name in variables):
        return {
            "status": "validation_error",
            "summary": "设备固定条件不能作为 RAG 推荐变量。",
            "invalid_variables": [name for name in variables if name in fixed],
        }
    task = payload.get("task_context") or _task(context)
    material = task.get("material") if isinstance(task, dict) else None
    if isinstance(material, dict):
        material = material.get("name")
    process_type = None
    if isinstance(task, dict):
        geometry = task.get("geometry") or {}
        process_type = task.get("process_type") or task.get("process_intent") \
            or task.get("task_type") or geometry.get("feature_type")
    filters = dict(payload.get("filters") or {})
    if material:
        filters.setdefault("material", material)
    if process_type:
        filters.setdefault("process_type", process_type)
    query = str(payload.get("query") or " ".join(
        str(item or "") for item in (material, process_type, *variables)
    )).strip()
    evidence = _search(
        {
            **payload,
            "query": query,
            "filters": filters,
            "purpose": "parameter_recommendation",
        },
        context,
        _include_full_hits=True,
    )
    pack = evidence.get("evidence_pack") if isinstance(evidence.get("evidence_pack"), dict) else {}
    if pack.get("evidence_status") != "sufficient":
        empty_recommendation = {"missing_variables": variables}
        return _parameter_result(
            status="insufficient_data",
            parameters={},
            source_type="reviewed_rag",
            data_support=_rag_parameter_support_summary(evidence, empty_recommendation),
            limitations=[
                "当前 Evidence Pack 未达到参数用途的 sufficient 条件，未抽取或聚合数值。",
                "候选、用途不匹配或条件不匹配的命中不能生成试切参数。",
            ],
            evidence_level=str(pack.get("evidence_status") or "insufficient"),
            authority_level="insufficient_reviewed_evidence",
            equipment=equipment,
            variables=variables,
            allowed_for_trial=False,
        ) | {"missing_variables": variables}
    hits = list(evidence.get("hits") or [])
    recommendation = recommend_from_evidence(
        variables,
        {name: _canonical_parameter_role(roles[name]) for name in variables},
        hits,
        safety_bounds_from_equipment(equipment),
        include_unreviewed_candidates=bool(payload.get("include_unreviewed_candidates")),
    )
    details = recommendation["parameter_details"]
    refs = list(dict.fromkeys(
        str(ref)
        for item in details.values()
        for ref in item.get("source_refs") or []
    ))
    if recommendation["missing_variables"]:
        return _parameter_result(
            status="insufficient_data",
            parameters={},
            source_type="reviewed_rag",
            source_refs=refs,
            data_support=_rag_parameter_support_summary(evidence, recommendation),
            limitations=[
                "审核证据未覆盖全部当前变量，未生成可执行参数候选。",
                "不得用调用者预填值补齐缺失证据。",
            ],
            evidence_level="insufficient_reviewed_evidence",
            authority_level="literature_prior",
            equipment=equipment,
            variables=variables,
            allowed_for_trial=False,
        ) | {"missing_variables": recommendation["missing_variables"]}
    return _parameter_result(
        status="success",
        parameters=recommendation["process_parameters"],
        strategy_parameters=recommendation["strategy_parameters"],
        parameter_details=details,
        source_type="reviewed_rag",
        source_refs=refs,
        data_support=_rag_parameter_support_summary(evidence, recommendation),
        limitations=["��������������飬���������У�������ȫ�����Ż���ʽ���ա�"]
        + (
            ["包含未审核文献候选：仅可作试验参考，需通过对话审核后才能进入正式证据链。"]
            if recommendation.get("unreviewed_candidates_used")
            else []
        ),
        evidence_level=(
            "reviewed_evidence"
            if not recommendation.get("unreviewed_candidates_used")
            else "unreviewed_literature_candidate"
        ),
        authority_level=(
            "literature_prior"
            if not recommendation.get("unreviewed_candidates_used")
            else "literature_candidate"
        ),
        equipment=equipment,
        variables=variables,
        validated=False,
        allowed_for_trial=True,
        allowed_for_formal_process=False,
        allowed_for_bo_training=False,
    )


def _rag_parameter_support_summary(
    evidence: dict[str, Any], recommendation: dict[str, Any],
) -> dict[str, Any]:
    pack = evidence.get("evidence_pack") if isinstance(evidence.get("evidence_pack"), dict) else {}
    hits = list(evidence.get("hits") or [])
    metadata = pack.get("retrieval_metadata") if isinstance(pack.get("retrieval_metadata"), dict) else {}
    return {
        "support_status": pack.get("evidence_status") or "insufficient",
        "hit_count": len(hits),
        "authority_levels": sorted({
            str(hit.get("authority_level") or "unknown")
            for hit in hits if isinstance(hit, dict)
        }),
        "source_refs": sorted({
            str(hit.get("chunk_id")) for hit in hits
            if isinstance(hit, dict) and hit.get("chunk_id")
        }),
        "missing_evidence": list(pack.get("missing_evidence") or []),
        "missing_variables": list(recommendation.get("missing_variables") or []),
        "degraded": bool(metadata.get("degraded")),
        "fallback": metadata.get("fallback"),
    }


def _declared_process_variable_roles(process_plan: dict[str, Any]) -> dict[str, str]:
    """Read explicit declarations without requiring one fixed ProcessPlan layout."""
    found: dict[str, str] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "controllable_variables":
                    items = child if isinstance(child, list) else [child]
                    for item in items:
                        name = item.get("name") if isinstance(item, dict) else item
                        if isinstance(name, str) and name:
                            role = item.get("role") if isinstance(item, dict) else None
                            found[name] = str(role or "process_setpoint")
                else:
                    visit(child)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(process_plan)
    return found


def _canonical_parameter_role(value: str) -> str:
    aliases = {
        "process_setpoint": "process_setpoint",
        "process setpoint": "process_setpoint",
        "工艺设定值": "process_setpoint",
        "工艺参数": "process_setpoint",
        "strategy_parameter": "strategy_parameter",
        "strategy parameter": "strategy_parameter",
        "策略参数": "strategy_parameter",
    }
    return aliases.get(value.strip().lower(), value.strip())


def _equipment_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    return _normalize_equipment(context.get("equipment_snapshot") or build_machine_bounds())


def _normalize_equipment(equipment: dict[str, Any]) -> dict[str, Any]:
    provided_tunable = equipment.get("tunable_capabilities")
    if isinstance(provided_tunable, dict):
        fixed = dict(equipment.get("fixed_conditions") or {})
        normalized_tunable: dict[str, dict[str, Any]] = {}
        for name, capability in provided_tunable.items():
            if not isinstance(capability, dict):
                continue
            normalized_tunable[name] = {
                **capability,
                "unit": capability.get("unit") or PARAMETER_UNITS.get(name),
                "role": capability.get("role") or "equipment_tunable",
            }
        for name in ("wavelength_nm", "spot_diameter_um", "pulse_width_fs"):
            value = equipment.get(name)
            if name not in normalized_tunable and isinstance(value, (int, float)):
                fixed.setdefault(name, value)
        return {
            **equipment,
            "fixed_conditions": fixed,
            "tunable_capabilities": normalized_tunable,
        }
    raw = equipment.get("machine_bounds") or {}
    fixed: dict[str, Any] = {}
    tunable: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            continue
        if value[0] == value[1]:
            fixed[name] = value[0]
        else:
            tunable[name] = {
                "min": value[0], "max": value[1],
                "unit": PARAMETER_UNITS.get(name), "role": "equipment_tunable",
            }
    return {**equipment, "fixed_conditions": fixed, "tunable_capabilities": tunable}


def _manage_trial(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation") or "get")
    task_id = str(payload.get("task_id") or context.get("session_id") or "task")
    gateway = _topic2_gateway(context)
    workflow_id = str(
        payload.get("workflow_id")
        or payload.get("trial_plan_id")
        or stable_id("trial", task_id)
    )
    if operation == "get":
        try:
            result = gateway.workflow(workflow_id)
        except Exception as exc:  # noqa: BLE001 - boundary failure is a safe block
            return {
                "status": "blocked",
                "summary": f"Topic2 试切状态不可用：{type(exc).__name__}",
            }
        return {"status": "success", "summary": "已读取 Topic2 试切状态。", "result": result}

    data = {key: value for key, value in payload.items() if key != "operation"}
    if operation == "create":
        if isinstance(payload.get("trial"), dict):
            return {
                "status": "validation_error",
                "summary": (
                    "manage_trial 不接受嵌套 trial 或未经参数 Tool 审核的自造数值。"
                    "请先通过 recommend_process_parameters 形成 allowed_for_trial 候选。"
                ),
                "invalid_fields": ["trial"],
            }
        approved_candidates = _approved_trial_candidates_from_observations(context)
        if not approved_candidates:
            return {
                "status": "insufficient_data",
                "summary": (
                    "尚无 allowed_for_trial 参数 Observation，未创建空试切计划。"
                    "请补充审核证据或合格历史/实验数据后重新调用 recommend_process_parameters。"
                ),
                "required_observation": "recommend_process_parameters.allowed_for_trial",
            }
        plan_definition = payload.get("plan_definition") \
            if isinstance(payload.get("plan_definition"), dict) else {
                key: payload.get(key)
                for key in (
                    "representative_geometry", "measurement_plan",
                    "acceptance_criteria", "stop_conditions",
                )
                if payload.get(key) is not None
            }
        missing_design = [
            key for key in ("representative_geometry", "measurement_plan")
            if not plan_definition.get(key)
        ]
        if missing_design:
            return {
                "status": "insufficient_data",
                "summary": (
                    "试切语义设计不完整；Tool 不再按工艺关键词套用固定几何或通用检测模板。"
                    "请由 Main LLM 根据当前任务补充代表性几何和测量方案。"
                ),
                "missing": missing_design,
            }
        equipment = _equipment_snapshot(context)
        data.update(
            {
                "trial_mode": payload.get("trial_mode") or "simple_trial_cut",
                "task_spec": _legacy_task(context),
                "machine_bounds": safety_bounds_from_equipment(equipment),
                "approved_parameter_candidates": approved_candidates,
                "plan_definition": plan_definition,
            }
        )
    elif operation == "start":
        if not context.get("human_approved"):
            return {"status": "blocked", "summary": "开始真实试切需要本次明确确认。", "required": "scoped_user_approval"}
        try:
            workflow = gateway.workflow(workflow_id)
        except Exception as exc:  # noqa: BLE001 - missing owner state fails closed
            return {
                "status": "blocked",
                "summary": f"Topic2 试切方案不可用：{type(exc).__name__}",
            }
        history = list((workflow.get("payload") or {}).get("history") or [])
        create_data = next(
            (
                event.get("data") or {}
                for event in history
                if event.get("operation") == "create"
            ),
            {},
        )
        matrix = list(create_data.get("approved_parameter_candidates") or [])
        try:
            candidate_index = int(payload.get("candidate_index") or 0)
            approved_parameters = matrix[candidate_index]
        except (IndexError, TypeError, ValueError):
            return {
                "status": "validation_error",
                "summary": "试切方案中没有对应的已审核参数候选，未启动执行。",
                "invalid_field": "candidate_index",
            }
        data["actual_parameters"] = dict(approved_parameters)
    elif operation not in {"record_result", "evaluate", "close"}:
        return {"status": "validation_error", "summary": f"不支持的试切操作：{operation}"}

    try:
        result = gateway.workflow_command(
            {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "phase": "trial",
                "operation": operation,
                "expected_version": payload.get("expected_version"),
                "human_approved": bool(context.get("human_approved")),
                "data": data,
            }
        )
    except Exception as exc:  # noqa: BLE001 - owner rejection must not be bypassed
        return {
            "status": "blocked",
            "summary": f"Topic2 拒绝试切状态变更：{type(exc).__name__}",
        }
    warnings = list(result.get("warnings") or []) if isinstance(result, dict) else []
    if payload.get("iteration") and payload.get("recommended_budget") and int(payload["iteration"]) >= int(payload["recommended_budget"]):
        warnings.append("已达到建议试切预算；这是规划提示，不会强制终止任务。")
    return {"status": "success", "summary": f"试切操作 {operation} 已由 Topic2 记录。", "result": result, "warnings": warnings}


def _approved_trial_candidates_from_observations(
    context: dict[str, Any],
) -> list[dict[str, float | int | str]]:
    working = context.get("working_context") or {}
    for observation in reversed(list(working.get("observations") or [])):
        if not isinstance(observation, dict):
            continue
        meta = observation.get("meta") if isinstance(observation.get("meta"), dict) else {}
        tool_name = str(observation.get("tool_name") or meta.get("tool_name") or "")
        if tool_name != "recommend_process_parameters":
            continue
        data = observation.get("data") if isinstance(observation.get("data"), dict) else {}
        if data.get("allowed_for_trial") is not True:
            return []
        candidate: dict[str, float | int | str] = {}
        for group in ("process_parameters", "strategy_parameters"):
            parameters = data.get(group) if isinstance(data.get(group), dict) else {}
            for name, parameter in parameters.items():
                value = parameter.get("value") if isinstance(parameter, dict) else parameter
                if isinstance(value, (int, float, str)):
                    candidate[str(name)] = value
        return [candidate] if candidate else []
    return []


def _approved_formal_window_from_observations(
    context: dict[str, Any], trial_result_id: str | None,
) -> dict[str, Any]:
    working = context.get("working_context") or {}
    for observation in reversed(list(working.get("observations") or [])):
        if not isinstance(observation, dict):
            continue
        meta = observation.get("meta") if isinstance(observation.get("meta"), dict) else {}
        tool_name = str(observation.get("tool_name") or meta.get("tool_name") or "")
        data = observation.get("data") if isinstance(observation.get("data"), dict) else {}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        decision = result.get("formal_process_decision") \
            if isinstance(result.get("formal_process_decision"), dict) else {}
        if tool_name != "manage_trial" or decision.get("unlocked") is not True:
            continue
        observed_result_id = str(result.get("result_id") or "")
        if trial_result_id and observed_result_id != trial_result_id:
            continue
        actual = result.get("approved_parameters") or decision.get("approved_parameters")
        return dict(actual) if isinstance(actual, dict) else {}
    return {}


def _manage_process(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation") or "prepare")
    task_id = str(payload.get("task_id") or context.get("session_id") or "task")
    workflow_id = str(
        payload.get("workflow_id")
        or payload.get("plan_id")
        or stable_id("formal", task_id)
    )
    gateway = _topic2_gateway(context)
    data = {key: value for key, value in payload.items() if key != "operation"}
    if operation == "prepare":
        trial_result_id = str(payload.get("trial_result_id") or "")
        approved_window = _approved_formal_window_from_observations(
            context, trial_result_id or None,
        )
        if not approved_window:
            return {
                "status": "insufficient_data",
                "summary": (
                    "没有已通过测量并解锁正式加工的试切参数；未接受 Planner 提供的参数值。"
                ),
                "required_observation": "manage_trial.evaluate.formal_process_decision.unlocked",
            }
        data["approved_window"] = approved_window
    if operation == "start" and not context.get("human_approved"):
        return {"status": "blocked", "summary": "开始真实正式加工需要本次明确确认。", "required": "scoped_user_approval"}
    if operation == "record_result":
        measurements = payload.get("measurements") or {}
        if not isinstance(measurements, dict) or not measurements:
            return {
                "status": "insufficient_data",
                "summary": "正式加工结果缺少测量事实，未记录空结果。",
                "missing": ["measurements"],
            }
    if operation not in {
        "prepare",
        "start",
        "record_checkpoint",
        "record_result",
        "complete",
        "abort",
    }:
        return {"status": "validation_error", "summary": f"不支持的正式加工操作：{operation}"}
    try:
        result = gateway.workflow_command(
            {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "phase": "formal",
                "operation": operation,
                "expected_version": payload.get("expected_version"),
                "human_approved": bool(context.get("human_approved")),
                "data": data,
            }
        )
    except Exception as exc:  # noqa: BLE001 - process owner rejection fails closed
        return {
            "status": "blocked",
            "summary": f"Topic2 拒绝正式加工状态变更：{type(exc).__name__}",
        }
    unsafe = operation == "record_checkpoint" and bool(
        payload.get("unsafe") or payload.get("equipment_alarm")
    )
    return {
        "status": "blocked" if unsafe else "success",
        "summary": (
            "检测到明确安全信号；Topic2 已记录 checkpoint，需人工处置。"
            if unsafe
            else f"正式加工操作 {operation} 已由 Topic2 记录。"
        ),
        "result": result,
    }


def _record_result(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    measurements = payload.get("measurements")
    defects = payload.get("defects") or []
    note = payload.get("operator_note") or payload.get("note")
    attachments = payload.get("attachments") or []
    if not (isinstance(measurements, dict) and measurements) and not defects and not note and not attachments:
        return {
            "status": "insufficient_data",
            "summary": "没有可记录的测量、缺陷、备注或附件；未创建空结果。",
            "missing": ["measurements_or_observations"],
        }
    session_id = str(context["session_id"])
    task_id = str(payload.get("task_id") or session_id)
    now = utc_now_iso()
    facts = {
        key: value
        for key, value in {
            "measurements": measurements or {},
            "defects": defects,
            "operator_note": note,
            "attachments": attachments,
            "actual_parameters": payload.get("actual_parameters") or {},
        }.items()
        if value
    }
    record = {
        "observation_id": str(
            payload.get("observation_id")
            or stable_id("observation", task_id, facts, now)
        ),
        "task_id": task_id,
        "recommendation_id": payload.get("recommendation_id"),
        "run_id": payload.get("run_id"),
        "observation_type": str(payload.get("observation_type") or "process_result"),
        "facts": facts,
        "observed_at": str(payload.get("observed_at") or now),
        "review_status": "pending",
        "source": "agent_sidecar_observation",
    }
    try:
        record = _topic2_gateway(context).save_observation(record)
    except Exception as exc:  # noqa: BLE001 - never fork process truth on gateway failure
        return {
            "status": "blocked",
            "summary": f"Topic2 未接收加工事实：{type(exc).__name__}",
            "recorded": None,
            "automatic_promotions": [],
        }
    warnings: list[str] = []
    count = 0
    try:
        state = get_session_state(session_id)
        observations = list(state.get("agent_observations_json") or [])
        observations.append(record)
        update_session_state(session_id, {"agent_observations_json": observations[-100:]})
        count = len(observations)
    except Exception as exc:  # noqa: BLE001 - front task outranks archival persistence
        warnings.append(f"会话结果投影更新失败：{type(exc).__name__}")
    return {
        "status": "partial" if warnings else "success",
        "summary": (
            "加工事实已由 Topic2 记录；仅形成待审核观察，未自动晋升。"
        ),
        "recorded": record,
        "observation_count": count,
        "bo_data_eligibility": "pending_review",
        "bo_training_candidate": None,
        "knowledge_candidates": [],
        "automatic_promotions": [],
        "warnings": warnings,
    }


def _generate_report(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    task_id = str(payload.get("task_id") or context.get("session_id") or "task")
    return TaskReportService().generate(task_id, {**payload, "task_spec": _legacy_task(context),
                                                   "equipment_snapshot": context.get("equipment_snapshot") or {}},
                                        payload.get("run_id"))


def _ingest_files(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    paths = payload.get("paths") or []
    if not isinstance(paths, list) or not paths:
        return {"status": "insufficient_data", "missing": ["paths"]}
    return {"status": "success", "files": [{"path": str(Path(path)), **ingest_file(path)} for path in paths]}


def _review_knowledge_item(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """知识候选审核：列出当前待审核条目，或执行用户在对话中确认的审核动作。

    未审核条目允许在对话/试验候选中使用（带 pending_review 标记），
    但只有审核动作（accept_to_rag / accept_as_literature_evidence 等）
    执行后才会进入正式证据链（RAG / Prior / BO）。
    """
    from ultrafast_knowledge.governance_review.review_actions import apply_review_action
    from ultrafast_knowledge.governance_review.schemas import ReviewActionRequest
    from ultrafast_knowledge.governance_review.service import list_tasks
    from ultrafast_memory.db.session import get_connection

    operation = str(payload.get("operation") or "list_pending")
    if operation == "list_pending":
        tasks = list_tasks("pending_review")
        with get_connection() as conn:
            items = []
            for task in tasks:
                row = conn.execute(
                    "SELECT candidate_id, extracted_claim, evidence_json, status FROM knowledge_candidate WHERE candidate_id=?",
                    (task["candidate_id"],),
                ).fetchone()
                candidate = dict(row) if row else None
                items.append(
                    {
                        "review_id": task["review_id"],
                        "candidate_id": task["candidate_id"],
                        "risk_level": task.get("risk_level"),
                        "auto_suggestion": task.get("auto_suggestion"),
                        "claim": (candidate or {}).get("extracted_claim"),
                        "evidence": (candidate or {}).get("evidence_json"),
                        "status": (candidate or {}).get("status"),
                    }
                )
        return {
            "status": "success",
            "pending_count": len(items),
            "items": items,
            "instruction": (
                "向用户展示上述未审核条目；用户确认后调用本工具执行 "
                "approve / accept_to_rag / reject / needs_more_evidence。"
            ),
        }
    if operation not in {"approve", "accept_to_rag", "reject", "needs_more_evidence", "withdraw"}:
        return {"status": "error", "message": f"unsupported operation: {operation}"}
    review_id = payload.get("review_id")
    if not review_id:
        return {"status": "insufficient_data", "missing": ["review_id"]}
    action = "accept_as_literature_evidence" if operation == "approve" else operation
    try:
        result = apply_review_action(
            str(review_id),
            ReviewActionRequest(
                action=action,
                reviewer_id=str(payload.get("reviewer_id") or "agent-conversation"),
                comment=str(payload.get("comment") or ""),
                target_level=payload.get("target_level"),
            ),
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "success", "review_id": str(review_id), "action": action, "result": result}
