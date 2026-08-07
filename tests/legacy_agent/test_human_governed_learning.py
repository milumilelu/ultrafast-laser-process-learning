from __future__ import annotations

import pytest

from ultrafast_agent.process_recommendations import BOTrainingApprovalService
from ultrafast_integrations.storage.process_recommendation_repository import (
    ProcessRecommendationRepository,
)
from ultrafast_memory.db.init_db import init_database
from ultrafast_memory.db.session import get_connection
from ultrafast_knowledge.governance_review.review_actions import apply_review_action
from ultrafast_knowledge.governance_review.schemas import ReviewActionRequest
from ultrafast_memory.process_learning import ProcessLearningService
from ultrafast_memory.process_memory import ProcessMemorySearchService


def _context():
    return {
        "session_id": "session-1",
        "working_context": {
            "task": {
                "task_id": "task-1",
                "material": {"name": "SiC", "grade": "4H"},
                "process_type": "surface_texturing",
            },
            "equipment_context": {
                "revision_id": "equipment-revision-1",
                "tunable_capabilities": {
                    "laser_power_W": {"min": 0.5, "max": 5.0},
                    "scan_speed_mm_s": {"min": 10.0, "max": 1000.0},
                },
            },
            "observations": [],
        },
    }


def test_result_recording_never_auto_promotes_candidates(memory_root):
    result = ProcessLearningService().record(
        {
            "measurements": {"Sa_um": 0.5},
            "operator_note": "边缘出现轻微崩裂，需要进一步验证原因。",
        },
        _context(),
    )

    assert result["automatic_promotions"] == []
    assert result["bo_training_candidate"]["status"] == "ineligible"
    assert "run_id_required" in result["bo_training_candidate"]["eligibility"]["blocking_reasons"]
    assert result["knowledge_candidates"][0]["status"] == "pending_review"
    with get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM bo_training_sample").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM knowledge_review_task").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM rag_document").fetchone()[0] == 0


def test_explicit_approval_materializes_an_eligible_bo_sample(memory_root):
    outcome = ProcessLearningService().record(
        {
            "recommendation_id": "recommendation-1",
            "run_id": "run-1",
            "execution_id": "execution-1",
            "machine_actual_parameters": {
                "laser_power_W": {"value": 2.0, "unit": "W"},
                "scan_speed_mm_s": {"value": 200.0, "unit": "mm/s"},
            },
            "measurements": {"Sa_um": {"value": 0.4, "unit": "um"}},
            "measurement_method": "confocal",
            "run_status": "completed",
            "alarms": [],
            "material_batch": "batch-1",
            "quality_decision": "PASS",
            "fidelity_level": "measured",
            "validation_status": "valid",
            "validated_by": "expert-1",
            "cam_applied_parameters": {"laser_power_W": 2.0},
        },
        _context(),
    )
    candidate = outcome["bo_training_candidate"]
    assert candidate["status"] == "eligible_pending_approval"
    assert candidate["training_sample_created"] is False

    with pytest.raises(ValueError, match="unknown or unapproved prior sample ids"):
        BOTrainingApprovalService().approve(
            candidate["candidate_id"], "expert-1", prior_sample_ids=["missing-sample"]
        )
    with get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM bo_training_sample").fetchone()[0] == 0

    approval = BOTrainingApprovalService().approve(
        candidate["candidate_id"], "expert-1"
    )

    assert approval["sample_id"]
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM bo_training_sample WHERE run_id='run-1'"
        ).fetchone()
        assert row is not None
        assert row["valid_for_training"] == 1
    stored = ProcessRecommendationRepository().get_training_candidate(
        candidate["candidate_id"]
    )
    assert stored["status"] == "approved"


def test_reviewed_result_knowledge_becomes_searchable_without_parameter_authority(
    memory_root,
):
    outcome = ProcessLearningService().record(
        {
            "operator_note": "边缘崩裂在当前批次重复出现，应检查焦点漂移。",
            "measurements": {"edge_chipping_count": 3},
        },
        _context(),
    )
    candidate = outcome["knowledge_candidates"][0]

    review = apply_review_action(
        candidate["review_id"],
        ReviewActionRequest(
            action="accept_to_rag",
            reviewer_id="expert-2",
            comment="作为已审核经验供方案分析使用，不作为参数或BO依据。",
        ),
    )

    assert review["status"] == "accepted_to_rag"
    assert review["rag_document"] is not None
    memory = ProcessMemorySearchService().search(
        {"material": "SiC", "process_type": "surface_texturing"},
        sources=["reviewed_experience"],
        query="焦点漂移",
    )
    item = memory["results"]["reviewed_experience"][0]
    assert item["record_type"] == "knowledge_candidate"
    assert "parameter_recommendation" in item["not_usable_for"]
