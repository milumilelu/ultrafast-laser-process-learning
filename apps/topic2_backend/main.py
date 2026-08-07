"""Independent Topic2 ASGI entry point: no Agent, LLM or RAG imports."""

from __future__ import annotations

import uvicorn

from apps.topic2_backend.api.app import create_app

app = create_app()


def main() -> None:
    uvicorn.run(
        "apps.topic2_backend.main:app", host="127.0.0.1", port=8010, reload=False
    )


if __name__ == "__main__":
    main()
