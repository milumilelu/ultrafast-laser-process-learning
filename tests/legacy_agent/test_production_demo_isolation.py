from __future__ import annotations

from fastapi.testclient import TestClient

from ultrafast_app.api.main import create_app


def test_persistent_demo_route_is_not_exposed(memory_root):
    with TestClient(create_app()) as client:
        assert client.post("/demo/tgv/run", json={}).status_code == 404


def test_web_bootstrap_has_no_implicit_mock_source(memory_root):
    with TestClient(create_app()) as client:
        response = client.post(
            "/knowledge/bootstrap-web",
            json={"task_spec": {"material": "SiC"}, "question": "evidence"},
        )
    assert response.status_code == 503
    assert "real search client" in response.text
