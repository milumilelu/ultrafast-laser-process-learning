from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def memory_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "memory-root"
    config_dir = root / "configs"
    config_dir.mkdir(parents=True)
    (config_dir / "default.yaml").write_text(
        "database:\n  url: sqlite:///data/test.db\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ULTRAFAST_MEMORY_ROOT", str(root))
    from ultrafast_shared.config import loader

    loader._load_revision_cached.cache_clear()
    yield root
    loader._load_revision_cached.cache_clear()
