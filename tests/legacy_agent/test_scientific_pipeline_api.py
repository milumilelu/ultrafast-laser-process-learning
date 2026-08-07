"""收尾回归：scientific pipeline API + funnel 统计（文档 §42、§45）。"""

from __future__ import annotations

from ultrafast_knowledge.scientific.funnel import funnel_report


def test_funnel_statistics_and_utilization_rate() -> None:
    report = funnel_report(
        retrieved_chunk_count=40,
        retrieved_source_count=8,
        relevant_source_count=6,
        knowledge_candidate_count=14,
        validated_candidate_count=11,
        approved_candidate_count=9,
        applicable_knowledge_count=8,
        feature_spec_count=4,
        prior_spec_count=2,
        constraint_spec_count=1,
        actually_used_knowledge_count=6,
    )
    assert report["retrieved_chunk_count"] == 40
    assert report["applicable_knowledge_count"] == 8
    assert report["knowledge_utilization_rate"] == 0.75


def test_funnel_zero_safe() -> None:
    report = funnel_report(
        retrieved_chunk_count=0, retrieved_source_count=0, relevant_source_count=0,
        knowledge_candidate_count=0, validated_candidate_count=0, approved_candidate_count=0,
        applicable_knowledge_count=0, feature_spec_count=0, prior_spec_count=0,
        constraint_spec_count=0, actually_used_knowledge_count=0,
    )
    assert report["knowledge_utilization_rate"] == 0.0


def test_build_corpus_api_endpoint() -> None:
    from fastapi.testclient import TestClient

    from ultrafast_app.api.main import create_app

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/scientific-retrieval/build-corpus",
        json={
            "task_scope": {
                "material": "SiC",
                "laser_type": "fs",
                "process_type": "rectangular_groove",
                "target": "depth_um",
            },
            "task_context_id": "TASK-API-1",
            "retrieval_intents": ["parameter_effect", "formula"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["corpus_pack_id"]
    assert data["task_context_id"] == "TASK-API-1"
    assert data["retrieval_trace"]["raw_hit_count"] > 0
    assert data["sources"]


def test_analyze_api_requires_real_llm_configuration() -> None:
    """无 mock 降级：analyze 在无真实 LLM 配置时返回 503（不静默降级）。"""
    from fastapi.testclient import TestClient

    import ultrafast_app.services.scientific_pipeline as service_module
    from ultrafast_knowledge.corpus.schemas import EvidenceCorpusPack
    from ultrafast_memory.llm.mock import MockLLMClient

    original = service_module.build_llm_client

    def _mock_client() -> MockLLMClient:
        return MockLLMClient()

    service_module.build_llm_client = _mock_client
    try:
        from ultrafast_app.api.main import create_app

        client = TestClient(create_app())
        build = client.post(
            "/api/v1/scientific-retrieval/build-corpus",
            json={
                "task_scope": {"material": "SiC", "laser_type": "fs", "target": "depth_um"},
                "task_context_id": "TASK-API-2",
            },
        ).json()
        pack = EvidenceCorpusPack.model_validate(build)
        response = client.post(
            "/api/v1/scientific-analysis/analyze",
            json={"corpus_pack": pack.model_dump(mode="json")},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "llm_not_configured"
    finally:
        service_module.build_llm_client = original


def test_validate_api_endpoint_rejects_bad_candidate() -> None:
    from fastapi.testclient import TestClient

    from ultrafast_app.api.main import create_app

    client = TestClient(create_app())
    pack = {
        "knowledge_pack_id": "KP-API-1",
        "source_corpus_pack_id": "CP-1",
        "task_scope": {"material": "SiC"},
        "candidates": [
            {
                "candidate_id": "KC-BAD-API",
                "type": "parameter_value",
                "parameter": "laser_power_W",
                "value": 20.0,
                "unit": "W",
            }
        ],
    }
    response = client.post("/api/v1/scientific-analysis/validate", json={"knowledge_pack": pack})
    assert response.status_code == 200
    data = response.json()
    assert data["rejected_candidates"] == ["KC-BAD-API"]
    assert any(issue["code"] == "missing_source" for issue in data["issues"])


def test_analysis_job_endpoints_and_progress_mechanism() -> None:
    """Job 端点：创建返回 run_id；未知 job 404；进度记录机制可用。"""
    from ultrafast_app.services.scientific_jobs import AnalysisJob
    from ultrafast_app.services.scientific_jobs import get_job_service

    service = get_job_service()
    job = AnalysisJob(job_id="sa-test-1")
    job.stage = "mapping"
    job.progress = {"current": 3, "total": 6}
    job.detail.append({"stage": "retrieving", "sources": 6})
    service._jobs["sa-test-1"] = job
    data = job.to_dict()
    assert data["status"] == "queued"
    assert data["stage"] == "mapping"
    assert data["progress"]["current"] == 3
    assert data["detail"][0]["stage"] == "retrieving"

    from fastapi.testclient import TestClient

    from ultrafast_app.api.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/scientific-analysis/jobs/sa-test-1")
    assert response.status_code == 200
    assert response.json()["analysis_run_id"] == "sa-test-1"
    not_found = client.get("/api/v1/scientific-analysis/jobs/sa-missing")
    assert not_found.status_code == 404
    from fastapi.testclient import TestClient

    from ultrafast_app.api.main import create_app

    client = TestClient(create_app())
    rows = []
    for index in range(30):
        rows.append(
            {
                "laser_power_W": 5.0 + index,
                "frequency_kHz": 100.0 + index,
                "scan_speed_mm_s": 100.0 + index,
                "hatch_spacing_um": 50.0,
                "passes": 2,
                "pulse_width_fs": 500.0,
                "depth_um": 20.0 + 0.2 * index,
                "parameter_combination_id": f"d{index % 20}",
            }
        )
    response = client.post(
        "/api/v1/scientific/identification-v2",
        json={"rows": rows, "target": "depth_um", "mode": "raw"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "raw"
    assert data["cv_strategy"] == "GroupKFold"
    assert data["controllable_ranking"]
    assert "feature_build" not in data


def test_identification_v2_physics_mode_reports_missing_spot_radius() -> None:
    """文档 §29/§30：缺 spot radius → 物理特征 unavailable 且原因可解释。"""
    from fastapi.testclient import TestClient

    from ultrafast_app.api.main import create_app

    client = TestClient(create_app())
    rows = []
    for index in range(30):
        rows.append(
            {
                "laser_power_W": 5.0 + index,
                "frequency_kHz": 100.0 + index,
                "scan_speed_mm_s": 100.0 + index,
                "hatch_spacing_um": 50.0,
                "passes": 2,
                "pulse_width_fs": 500.0,
                "depth_um": 20.0 + 0.2 * index,
                "parameter_combination_id": f"d{index % 20}",
            }
        )
    response = client.post(
        "/api/v1/scientific/identification-v2",
        json={"rows": rows, "target": "depth_um", "mode": "physics", "device_properties": {}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["feature_build"]["missing_device_properties"] == ["spot_radius_um"]
    assert "peak_fluence" in data["feature_build"]["unavailable_features"]
    assert data["mechanism_ranking"] == []
