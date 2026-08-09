"""Guardrail: scientific tests must not reintroduce fabricated resources."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_no_fabricated_scientific_test_sources() -> None:
    forbidden = (
        "np." + "random",
        "default_" + "rng",
        "make_" + "doc(",
        "SYNTHETIC_" + "TEST_FIXTURE",
        "seed_" + "golden",
        "topic2_" + "experiments_v1",
        "golden_" + "sic",
    )
    violations: list[str] = []
    roots = (REPO / "tests", REPO / "apps" / "topic2_frontend" / "src")
    for root in roots:
        candidates = root.rglob("*test*.py") if root.name == "tests" else root.rglob("*test*")
        for path in candidates:
            if path == Path(__file__) or not path.is_file():
                continue
            if path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            text = path.read_text(encoding="utf-8")
            hits = [token for token in forbidden if token in text]
            if hits:
                violations.append(f"{path.relative_to(REPO)}: {', '.join(hits)}")
    assert not violations, "fabricated scientific test inputs detected:\n" + "\n".join(
        violations
    )


def test_legacy_fabricated_suite_is_removed() -> None:
    legacy = REPO / "tests" / "legacy_agent"
    assert not legacy.exists() or not any(legacy.rglob("test_*.py"))


def test_frontend_fixture_generator_is_removed() -> None:
    assert not (REPO / "scripts" / "export_golden_frontend_fixture.py").exists()
    assert not (
        REPO / "apps" / "topic2_frontend" / "src" / "__fixtures__" / "goldenRun.json"
    ).exists()
