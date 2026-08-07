"""LLM 配置接口：保存配置 / DPAPI 加密保存 Key / 测试连接（不泄漏明文）。"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from ultrafast_app.api.main import create_app


def test_llm_config_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ULTRAFAST_MEMORY_ROOT", str(tmp_path))
    from ultrafast_shared.config import loader

    loader._load_revision_cached.cache_clear()
    try:
        app = create_app()
    finally:
        loader._load_revision_cached.cache_clear()
    client = TestClient(app)

    saved = client.post("/llm/config", json={"provider": "deepseek", "model": "deepseek-v4-flash"})
    assert saved.status_code == 200
    assert saved.json()["provider"] == "deepseek"

    config = client.get("/llm/config").json()
    assert config["provider"] == "deepseek"
    assert config["model"] == "deepseek-v4-flash"
    assert config["api_key_env"] == "DEEPSEEK_API_KEY"

    providers = client.get("/llm/providers").json()
    names = {item["name"] for item in providers["providers"]}
    assert "deepseek" in names
    deepseek = next(item for item in providers["providers"] if item["name"] == "deepseek")
    assert "deepseek-v4-flash" in deepseek["models"]


def test_llm_api_key_is_encrypted_stored_and_injected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ULTRAFAST_MEMORY_ROOT", str(tmp_path))
    from ultrafast_shared.config import loader

    loader._load_revision_cached.cache_clear()
    try:
        app = create_app()
    finally:
        loader._load_revision_cached.cache_clear()
    client = TestClient(app)

    client.post("/llm/config", json={"provider": "deepseek", "model": "deepseek-v4-flash"})
    response = client.post("/llm/api-key", json={"api_key": "sk-secret-dummy"})
    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["api_key_available"] is True
    # 响应绝不包含明文 key
    assert "sk-secret-dummy" not in response.text
    # 明文不落盘：存储文件不得包含原文
    store = tmp_path / "configs" / "secrets" / "llm_api_key.bin"
    assert store.exists()
    assert b"sk-secret-dummy" not in store.read_bytes()
    # 注入进程环境变量后可用
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-secret-dummy"
    config = client.get("/llm/config").json()
    assert config["api_key_available"] is True


def test_llm_test_reports_configuration_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ULTRAFAST_MEMORY_ROOT", str(tmp_path))
    from ultrafast_shared.config import loader

    loader._load_revision_cached.cache_clear()
    try:
        app = create_app()
    finally:
        loader._load_revision_cached.cache_clear()
    client = TestClient(app)

    result = client.post("/llm/test").json()
    assert "configured" in result
    assert "external_call_performed" in result
    assert "message" in result
