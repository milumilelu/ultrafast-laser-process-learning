"""Architecture boundary guardrails（PR-01）。

运行 import-linter 契约；本测试是 CI 的一部分。
import-linter 未安装时跳过（本地最小环境）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

def _repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while not (current / "pyproject.toml").exists() and current.parent != current:
        current = current.parent
    return current


REPO_ROOT = _repo_root()
CONFIG_PATH = REPO_ROOT / ".importlinter"
EXPECTED_CONTRACTS = {
    "domain-leaf",
    "e2p-leaf",
    "shared-leaf",
    "bo-not-on-orchestration",
    "agent-not-on-infra-core",
}


def _lint_imports() -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env.setdefault("PYTHONUTF8", "1")
    executable = shutil.which("lint-imports") or sys.executable
    args = (
        [executable, "-c", "from importlinter.cli import lint_imports; import sys; sys.exit(lint_imports())"]
        if executable == sys.executable
        else [executable]
    )
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
        env=env,
        timeout=300,
    )


def test_config_file_exists() -> None:
    assert CONFIG_PATH.exists(), ".importlinter 契约文件缺失"


def test_importlinter_contracts_pass() -> None:
    if shutil.which("lint-imports") is None and not _importlinter_installed():
        pytest.skip("import-linter 未安装")
    result = _lint_imports()
    output = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"import-linter 契约失败（exit={result.returncode}）：\n{output[-4000:]}"
    )
    summary = "".join(line.strip() for line in output.splitlines() if "broken" in line.lower())
    assert "0 broken" in summary, f"存在被打破的契约：{summary or output[-2000:]}"


def _importlinter_installed() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("importlinter") is not None
    except Exception:
        return False


def test_no_forbidden_cross_package_imports_via_ast() -> None:
    """AST 级静态兜底：叶子包（domain/e2p/shared）不得 import 任何项目包。"""
    import ast

    src = REPO_ROOT / "src"
    leaf_packages = {"ultrafast_domain", "ultrafast_e2p", "ultrafast_shared"}
    other = {
        "ultrafast_agent",
        "ultrafast_bo",
        "ultrafast_integrations",
        "ultrafast_knowledge",
        "ultrafast_memory",
        "ultrafast_app",
    }
    violations: list[str] = []
    for path in src.rglob("*.py"):
        if not path.parts[-2].startswith("ultrafast_") or path.parts[-2] not in leaf_packages:
            continue
        owner = path.parts[-2]
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in other or (top in leaf_packages and top != owner):
                    violations.append(f"{path.relative_to(src)} -> {name}")
    assert not violations, "叶子包存在非法跨包 import：\n" + "\n".join(violations[:30])
