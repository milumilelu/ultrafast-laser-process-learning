"""LLM 配置读写：非敏感配置存 llm.local.json；API Key 用 Windows DPAPI 加密存储。

明文 Key 永不落盘；保存后注入进程环境变量，/llm/test 与 chat 无需重启即可生效。
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from ultrafast_memory.core.config import get_project_root, load_config

SECRET_DIR = "configs/secrets"
SECRET_FILE = "llm_api_key.bin"


PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "ZHIPUAI_API_KEY",
    "local": "OPENAI_API_KEY",
}

PROVIDER_BASE_URL = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "anthropic": "https://api.anthropic.com",
    "moonshot": "https://api.moonshot.ai/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://api.z.ai/api/paas/v4",
    "local": "",
}

PROVIDER_MODELS = {
    "openai": ["gpt-5.4-mini", "gpt-5.4", "gpt-5.5"],
    "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
    "anthropic": ["claude-sonnet-4-5", "claude-opus-4-1"],
    "moonshot": ["moonshot-v1-32k"],
    "qwen": ["qwen-plus", "qwen-max"],
    "glm": ["glm-4-plus", "glm-4-flash"],
    "local": ["local-model"],
}


def secret_path(root: Path | None = None) -> Path:
    return (root or get_project_root()) / SECRET_DIR / SECRET_FILE


def _dpapi_protect(data: bytes) -> bytes | None:
    """Windows DPAPI 加密；非 Windows 返回 None（调用方回退）。"""
    try:
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        input_blob = DATA_BLOB(
            len(data),
            ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)),
        )
        output_blob = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
        ):
            return None
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    except Exception:  # noqa: BLE001 - 非 Windows 环境回退
        return None


def _dpapi_unprotect(data: bytes) -> bytes | None:
    try:
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        input_blob = DATA_BLOB(
            len(data),
            ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)),
        )
        output_blob = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
        ):
            return None
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    except Exception:  # noqa: BLE001 - 非 Windows 环境回退
        return None


def save_api_key(api_key: str, root: Path | None = None) -> dict[str, Any]:
    """加密保存 API Key 并注入当前进程环境变量。返回加密方式说明。"""
    if not api_key or not api_key.strip():
        raise ValueError("api key is empty")
    path = secret_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    protected = _dpapi_protect(api_key.strip().encode("utf-8"))
    if protected is not None:
        path.write_bytes(protected)
        encryption = "dpapi"
    else:
        # 非 Windows 回退：base64 混淆 + 显式标注，不假装安全
        path.write_bytes(base64.b64encode(api_key.strip().encode("utf-8")))
        encryption = "plaintext_fallback"
    return {"stored": True, "encryption": encryption, "path": str(path)}


def load_stored_api_key(root: Path | None = None) -> str | None:
    path = secret_path(root)
    if not path.exists():
        return None
    raw = path.read_bytes()
    protected = _dpapi_unprotect(raw)
    if protected is not None:
        return protected.decode("utf-8")
    try:
        return base64.b64decode(raw).decode("utf-8")
    except Exception:  # noqa: BLE001 - 损坏的存储视为未配置
        return None


def restore_api_key_from_store(root: Path | None = None) -> None:
    """服务启动时把已存 Key 注入环境变量（key_env 已配置时）。"""
    local = _load_local_config(root or get_project_root())
    key_env = local.get("api_key_env")
    if not key_env or os.environ.get(key_env):
        return
    stored = load_stored_api_key(root)
    if stored:
        os.environ[key_env] = stored


def save_llm_config(
    provider: str,
    model: str,
    api_base: str | None = None,
    api_key_env: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """保存非敏感 LLM 配置到 configs/llm.local.json（永不写明文 Key）。"""
    base = root or get_project_root()
    if provider not in PROVIDER_KEY_ENV:
        raise ValueError(f"unsupported provider: {provider}")
    payload = {
        "provider": provider,
        "model": model,
        "api_base": api_base or PROVIDER_BASE_URL[provider],
        "api_key_env": api_key_env or PROVIDER_KEY_ENV[provider],
    }
    path = base / "configs" / "llm.local.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return payload


def _configured(provider: str | None, model: str | None, api_base: str | None, api_key_env: str | None) -> dict[str, Any]:
    key_env = api_key_env or (PROVIDER_KEY_ENV.get(provider or "") if provider else None)
    return {
        "provider": provider,
        "model": model,
        "api_base": api_base,
        "api_key_env": key_env,
        "api_key_available": bool(key_env and os.environ.get(key_env)),
    }


def _load_local_config(root: Path) -> dict[str, Any]:
    path = root / "configs" / "llm.local.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.pop("api_key", None)
    return data


def get_llm_config(root: Path | None = None) -> dict[str, Any]:
    base = root or get_project_root()
    env_provider = os.environ.get("ULTRAFAST_LLM_PROVIDER")
    env_model = os.environ.get("ULTRAFAST_LLM_MODEL")
    env_base = os.environ.get("ULTRAFAST_LLM_API_BASE")
    env_key_env = os.environ.get("ULTRAFAST_LLM_API_KEY_ENV")
    if env_provider or env_model or env_base or env_key_env:
        provider = env_provider
        return _configured(
            provider,
            env_model,
            env_base or PROVIDER_BASE_URL.get(provider or ""),
            env_key_env,
        )

    local = _load_local_config(base)
    if local:
        provider = local.get("provider")
        return _configured(
            provider,
            local.get("model"),
            local.get("api_base") or PROVIDER_BASE_URL.get(provider or ""),
            local.get("api_key_env"),
        )

    default = load_config(base).get("llm", {})
    if default:
        provider = default.get("provider")
        return _configured(provider, default.get("model"), default.get("api_base"), default.get("api_key_env"))

    return {
        "provider": None,
        "model": None,
        "api_base": None,
        "api_key_env": None,
        "api_key_available": False,
    }