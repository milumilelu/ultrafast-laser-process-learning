"""Agent 对话驱动的知识审核闭环 + 未审核候选可用但标记（测试）。"""

from __future__ import annotations

from ultrafast_knowledge.rag.parameter_recommendation import recommend_from_evidence
from ultrafast_memory.agent_runtime.tool_registry import (
    FOREGROUND_SAFE_TOOL_NAMES,
    _review_knowledge_item,
    build_main_agent_tool_registry,
)


def _hit(review_status: str, chunk_id: str = "C-1", evidence_level: str | None = None) -> dict:
    return {
        "chunk_id": chunk_id,
        "paper_id": "P-1",
        "page_start": 3,
        "content": "扫描速度 50 mm/s，频率 20 kHz",
        "review_status": review_status,
        "evidence_level": evidence_level,
        "metadata": {"material": "SiC", "review_status": review_status},
    }


BOUNDS = {"scan_speed_mm_s": (1.0, 200.0), "frequency_kHz": (1.0, 500.0)}


def test_review_tool_is_registered_as_foreground_safe() -> None:
    names = {item.name for item in build_main_agent_tool_registry().list_contracts()}
    assert "review_knowledge_item" in names
    assert "review_knowledge_item" in FOREGROUND_SAFE_TOOL_NAMES


def test_list_pending_returns_review_queue(memory_root) -> None:
    result = _review_knowledge_item({"operation": "list_pending"}, {"session_id": "s1"})
    assert result["status"] == "success"
    assert "pending_count" in result
    assert isinstance(result["items"], list)


def test_recommendation_excludes_unreviewed_by_default() -> None:
    result = recommend_from_evidence(
        ["scan_speed_mm_s", "frequency_kHz"],
        {"scan_speed_mm_s": "process_setpoint", "frequency_kHz": "process_setpoint"},
        [_hit("pending_review")],
        BOUNDS,
    )
    assert result["process_parameters"] == {}
    assert result["unreviewed_candidates_used"] is False


def test_recommendation_marks_unreviewed_candidates_when_enabled() -> None:
    result = recommend_from_evidence(
        ["scan_speed_mm_s", "frequency_kHz"],
        {"scan_speed_mm_s": "process_setpoint", "frequency_kHz": "process_setpoint"},
        [_hit("pending_review")],
        BOUNDS,
        include_unreviewed_candidates=True,
    )
    assert result["unreviewed_candidates_used"] is True
    assert result["unreviewed_source_refs"]
    detail = result["parameter_details"]["scan_speed_mm_s"]
    assert detail["authority_level"] == "literature_candidate"
    assert detail["review_status"] == "pending_review"
    assert detail["allowed_for_trial"] is True
    assert detail["allowed_for_formal_process"] is False


def test_recommendation_keeps_reviewed_authority() -> None:
    result = recommend_from_evidence(
        ["scan_speed_mm_s"],
        {"scan_speed_mm_s": "process_setpoint"},
        [_hit("accepted", evidence_level="literature_evidence")],
        BOUNDS,
        include_unreviewed_candidates=True,
    )
    detail = result["parameter_details"]["scan_speed_mm_s"]
    assert detail["authority_level"] == "literature_prior"
    assert detail["review_status"] == "reviewed"
    assert detail["allowed_for_formal_process"] is True


def test_recommendation_ignores_rejected_hits() -> None:
    result = recommend_from_evidence(
        ["scan_speed_mm_s"],
        {"scan_speed_mm_s": "process_setpoint"},
        [_hit("rejected")],
        BOUNDS,
        include_unreviewed_candidates=True,
    )
    assert result["process_parameters"] == {}
    assert result["unreviewed_candidates_used"] is False
