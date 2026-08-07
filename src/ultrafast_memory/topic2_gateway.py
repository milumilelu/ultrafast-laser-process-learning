"""HTTP boundary to the Topic2 process application.

The Agent sidecar may enrich or explain process work, but it never owns process
state.  Every process mutation crosses this boundary into the Topic2 service.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class Topic2GatewayError(RuntimeError):
    pass


class Topic2ProcessGateway:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = (
            base_url or os.getenv("TOPIC2_API_URL", "http://127.0.0.1:8010")
        ).rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None):
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise Topic2GatewayError(f"Topic2 unavailable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise Topic2GatewayError(
                f"Topic2 rejected {method} {path} ({response.status_code}): "
                f"{response.text}"
            )
        return response.json()

    def recommend(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/optimization/recommend", request)

    def save_observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/process-observations", observation)

    def workflow_command(self, command: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/process-workflows/commands", command)

    def workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/process-workflows/{workflow_id}")
