"""Small HTTP client; it contains no modeling or optimization implementation."""

from __future__ import annotations

import os
from typing import Any

import httpx
from pydantic import BaseModel


class Topic2ClientError(RuntimeError):
    pass


class Topic2Client:
    def __init__(
        self,
        base_url: str | None = None,
        client: Any | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = (
            base_url or os.getenv("TOPIC2_API_URL", "http://127.0.0.1:8010")
        ).rstrip("/")
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    @staticmethod
    def _payload(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
        return value.model_dump(mode="json") if isinstance(value, BaseModel) else value

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise Topic2ClientError(
                f"Topic2 {method} {path} failed ({response.status_code}): {response.text}"
            )
        return response.json()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health")

    def import_experiments(self, request: BaseModel | dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/experiments/import", json=self._payload(request)
        )

    def identify_parameters(
        self, request: BaseModel | dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/parameter-identification/run", json=self._payload(request)
        )

    def train_model(self, request: BaseModel | dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/models/train", json=self._payload(request)
        )

    def model_policy(self, request: BaseModel | dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/e2p/model-policy", json=self._payload(request)
        )

    def recommend(self, request: BaseModel | dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/optimization/recommend", json=self._payload(request)
        )

    def save_task_context(
        self, task_context_id: str, version: int, snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/api/v1/task-contexts/{task_context_id}/versions/{version}",
            json=snapshot,
        )

    def task_context(
        self, task_context_id: str, version: int | None = None
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/task-contexts/{task_context_id}",
            params={"version": version} if version is not None else None,
        )

    def save_observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/process-observations", json=observation
        )

    def workflow_command(self, command: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/api/v1/process-workflows/commands", json=command
        )

    def workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/process-workflows/{workflow_id}")

    def statistics(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/database/statistics")
