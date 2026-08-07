"""Knowledge Utilization Funnel 统计（文档 §45）。

retrieved_chunk_count → ... → actually_used_knowledge_count 逐级统计，
仅作为工程诊断指标，不作为正式科研验收指标。
"""

from __future__ import annotations

from typing import Any


def funnel_report(
    *,
    retrieved_chunk_count: int,
    retrieved_source_count: int,
    relevant_source_count: int,
    knowledge_candidate_count: int,
    validated_candidate_count: int,
    approved_candidate_count: int,
    applicable_knowledge_count: int,
    feature_spec_count: int,
    prior_spec_count: int,
    constraint_spec_count: int,
    actually_used_knowledge_count: int,
) -> dict[str, Any]:
    report = {
        "retrieved_chunk_count": retrieved_chunk_count,
        "retrieved_source_count": retrieved_source_count,
        "relevant_source_count": relevant_source_count,
        "knowledge_candidate_count": knowledge_candidate_count,
        "validated_candidate_count": validated_candidate_count,
        "approved_candidate_count": approved_candidate_count,
        "applicable_knowledge_count": applicable_knowledge_count,
        "feature_spec_count": feature_spec_count,
        "prior_spec_count": prior_spec_count,
        "constraint_spec_count": constraint_spec_count,
        "actually_used_knowledge_count": actually_used_knowledge_count,
    }
    report["knowledge_utilization_rate"] = (
        round(
            actually_used_knowledge_count / applicable_knowledge_count, 4
        )
        if applicable_knowledge_count
        else 0.0
    )
    return report


def funnel_from_run(records: dict[str, Any]) -> dict[str, Any]:
    """从一次完整 run 的追溯记录组装 funnel（字段缺失按 0 计）。"""
    return funnel_report(
        retrieved_chunk_count=int(records.get("retrieved_chunk_count") or 0),
        retrieved_source_count=int(records.get("retrieved_source_count") or 0),
        relevant_source_count=int(records.get("relevant_source_count") or 0),
        knowledge_candidate_count=int(records.get("knowledge_candidate_count") or 0),
        validated_candidate_count=int(records.get("validated_candidate_count") or 0),
        approved_candidate_count=int(records.get("approved_candidate_count") or 0),
        applicable_knowledge_count=int(records.get("applicable_knowledge_count") or 0),
        feature_spec_count=int(records.get("feature_spec_count") or 0),
        prior_spec_count=int(records.get("prior_spec_count") or 0),
        constraint_spec_count=int(records.get("constraint_spec_count") or 0),
        actually_used_knowledge_count=int(records.get("actually_used_knowledge_count") or 0),
    )
