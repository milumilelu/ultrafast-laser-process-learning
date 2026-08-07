from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["health"])


class LlmConfigSaveRequest(BaseModel):
    provider: str = "deepseek"
    model: str
    api_base: str | None = None
    api_key_env: str | None = None


class LlmApiKeySaveRequest(BaseModel):
    api_key: str = Field(min_length=1)


@router.get("/health")
def health() -> dict:
    from ultrafast_memory.core.runtime_identity import runtime_identity

    return {
        "status": "ok",
        "api_version": "0.3.0",
        "workflow_contract": "main-agent-working-context-v1",
        "agent_capability_contract": "skill-discovery-v2",
        "runtime_identity": runtime_identity(),
    }


@router.get("/llm/config")
def llm_config() -> dict:
    from ultrafast_memory.core.llm_config import get_llm_config

    return get_llm_config()


@router.get("/llm/providers")
def llm_providers() -> dict:
    from ultrafast_memory.core.llm_config import PROVIDER_BASE_URL, PROVIDER_MODELS

    return {
        "providers": [
            {"name": name, "models": PROVIDER_MODELS[name], "api_base": base}
            for name, base in PROVIDER_BASE_URL.items()
        ]
    }


@router.post("/llm/config")
def llm_config_save(request: LlmConfigSaveRequest) -> dict:
    from ultrafast_memory.core.llm_config import save_llm_config

    try:
        saved = save_llm_config(
            request.provider, request.model, request.api_base, request.api_key_env
        )
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "invalid_provider", "message": str(exc)}) from exc
    return {"saved": True, **saved}


@router.post("/llm/api-key")
def llm_api_key_save(request: LlmApiKeySaveRequest) -> dict:
    """DPAPI 加密保存 API Key 并注入进程环境变量（明文 Key 永不落盘/返回）。"""
    import os

    from ultrafast_memory.core.llm_config import (
        PROVIDER_KEY_ENV,
        get_llm_config,
        save_api_key,
        save_llm_config,
    )

    config = get_llm_config()
    provider = config.get("provider") or "deepseek"
    key_env = config.get("api_key_env") or PROVIDER_KEY_ENV.get(provider)
    try:
        result = save_api_key(request.api_key)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "invalid_api_key", "message": str(exc)}) from exc
    if key_env:
        os.environ[key_env] = request.api_key
    # 确保本地配置指向正确的 key_env
    if provider and key_env:
        save_llm_config(provider, config.get("model") or "deepseek-v4-flash", api_key_env=key_env)
    return {"saved": True, **result, "api_key_available": True, "key_env": key_env}


@router.post("/llm/test")
def llm_test() -> dict:
    from ultrafast_memory.core.llm_config import (
        get_llm_config,
        restore_api_key_from_store,
    )
    from ultrafast_memory.llm.factory import create_llm_client
    from ultrafast_memory.llm.mock import MockLLMClient
    from ultrafast_memory.llm.openai_compatible import LLMProviderError

    # 已保存（DPAPI）的 Key 在服务重启后也要可用于测试：先恢复注入环境变量
    restore_api_key_from_store()
    config = get_llm_config()
    configured = bool(
        config.get("provider")
        and config.get("model")
        and config.get("api_base")
        and config.get("api_key_available")
    )
    result = {
        "configured": configured,
        "provider": config.get("provider"),
        "model": config.get("model"),
        "api_key_available": config.get("api_key_available"),
        "external_call_performed": False,
        "valid": False,
    }
    client = create_llm_client(config)
    if not configured or isinstance(client, MockLLMClient) or not hasattr(client, "test_connection"):
        result["message"] = "LLM 配置不完整，未执行外部验证。"
        return result
    result["external_call_performed"] = True
    try:
        client.test_connection(timeout=20)
        result["valid"] = True
        result["message"] = "LLM 凭证、接口和模型验证通过。"
    except LLMProviderError as exc:
        result["message"] = str(exc)
        result["status_code"] = exc.status_code
        result["error_code"] = exc.error_code
    return result


@router.get("/doctor")
def doctor() -> dict:
    from ultrafast_app.doctor.service import DoctorService

    return DoctorService().run()
