"""Live DeepSeek acceptance over repository-owned scientific PDFs.

The API key is read only from DEEPSEEK_API_KEY and is never serialized.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ultrafast_knowledge.evidence_pipeline import (
    PersistentScientificPaperRepository,
    RequirementEvidenceExtractor,
    RequirementEvidencePipeline,
    RetrievalGold,
    ScientificIndexIngestionService,
    ScientificIndexStore,
    evaluate_evidence_run,
)
from ultrafast_memory.llm.openai_compatible import OpenAICompatibleClient
from ultrafast_requirements import RequirementCompiler
from ultrafast_shared.units import convert

MODEL = "deepseek-v4-flash"
PAPERS = (
    (
        "04_arxiv_2502.16530.pdf",
        "Ultrashort 30-fs laser photoablation of diamond",
        {"material": "diamond", "laser_type": "fs"},
    ),
    (
        "10_arxiv_2411.18093.pdf",
        "Multi-focal picosecond laser vertical slicing of 4H-SiC",
        {"material": "4H-SiC", "laser_type": "ps"},
    ),
    (
        "11_arxiv_2404.09906.pdf",
        "Photoluminescence of femtosecond laser-irradiated silicon carbide",
        {"material": "SiC", "laser_type": "fs"},
    ),
    (
        "13_arxiv_2411.18868.pdf",
        "Laser writing and spin control of near infrared emitters in SiC",
        {"material": "SiC", "laser_type": "fs"},
    ),
)


class AuditedDeepSeekClient:
    """Capture provider request identity and token usage, never prompts or credentials."""

    model = MODEL

    def __init__(self) -> None:
        self._client = OpenAICompatibleClient(
            {
                "provider": "deepseek",
                "model": MODEL,
                "api_base": "https://api.deepseek.com",
                "api_key_env": "DEEPSEEK_API_KEY",
            }
        )
        self.calls: list[dict[str, Any]] = []

    def test_connection(self) -> dict[str, Any]:
        return self._client.test_connection(timeout=30)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        response = self._client.chat(messages, **kwargs)
        raw = dict(response.get("raw") or {})
        self.calls.append(
            {
                "request_id": raw.get("id"),
                "created": raw.get("created"),
                "model": raw.get("model") or response.get("model"),
                "usage": raw.get("usage") or {},
            }
        )
        return response


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paper-root",
        type=Path,
        default=Path("artifacts/b1_annotation/papers"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def _client() -> AuditedDeepSeekClient:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY is required for live acceptance")
    client = AuditedDeepSeekClient()
    client.test_connection()
    return client


def _requirement_set():
    compiled = RequirementCompiler().compile(
        {
            "target": "depth_um",
            "task_type": "prediction",
            "material": "diamond",
            "laser_type": "fs",
        },
        [
            {
                "quantity": "laser_power_W",
                "value": 20.0,
                "unit": "W",
                "source": "task",
            },
            {
                "quantity": "frequency_kHz",
                "value": 100.0,
                "unit": "kHz",
                "source": "task",
            },
            {
                "quantity": "scan_speed_m_s",
                "value": 1.0,
                "unit": "m/s",
                "source": "task",
            },
        ],
    )
    threshold = next(
        item
        for item in compiled.knowledge_requirements
        if item.quantity == "ablation_threshold_J_m2"
    )
    return compiled.model_copy(update={"requirements": [threshold]})


def _paper_evidence(run: Any, requirement_id: str) -> list[dict[str, Any]]:
    return [
        {
            "paper_id": item.paper_id,
            "document_version_id": item.document_version_id,
            **item.evidence.model_dump(mode="json"),
        }
        for item in run.paper_evidence[requirement_id]
    ]


def run_acceptance(paper_root: Path, timeout: float) -> dict[str, Any]:
    paths = [paper_root / name for name, _title, _metadata in PAPERS]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"real acceptance PDFs are missing: {missing}")
    client = _client()
    with tempfile.TemporaryDirectory(prefix="deepseek-live-evidence-") as temp:
        database = Path(temp) / "scientific-index.db"

        @contextmanager
        def connection():
            conn = sqlite3.connect(database)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

        store = ScientificIndexStore(connection)
        ScientificIndexIngestionService(store).ingest_many(
            [
                {
                    "pdf_path": paper_root / name,
                    "title": title,
                    "metadata": metadata,
                }
                for name, title, metadata in PAPERS
            ]
        )
        repository = PersistentScientificPaperRepository(store)
        pipeline = RequirementEvidencePipeline(
            RequirementEvidenceExtractor(client, model=MODEL, timeout=timeout),
            repository=repository,
            store=store,
        )
        positive_set = _requirement_set()
        positive_requirement = positive_set.knowledge_requirements[0]
        positive_run = pipeline.analyze(positive_set, paper_top_k=4, window_top_k=8)

        negative_requirement = positive_requirement.model_copy(
            update={
                "requirement_id": "req-live-negative",
                "quantity": "nonexistent_material_constant",
                "role": "negative_live_acceptance",
                "expected_unit": None,
                "query_terms": ["nonexistent material constant qzxv"],
            }
        )
        negative_set = positive_set.model_copy(
            update={"requirements": [negative_requirement]}
        )
        negative_run = pipeline.analyze(negative_set, paper_top_k=4, window_top_k=8)

        candidates, windows = repository.retrieve(positive_requirement, paper_top_k=4)
        gold_block = next(
            block
            for block in store.blocks(paper_ids=[PAPERS[0][0]])
            if "ablation threshold of diamond (3.0 J/cm2)" in block.text
        )
        metrics = evaluate_evidence_run(
            candidates,
            windows,
            positive_run.results[0],
            RetrievalGold(
                relevant_paper_ids={PAPERS[0][0]},
                relevant_block_ids={gold_block.block_id},
                expected_value=3.0,
                expected_unit="J/cm2",
                expected_conditions={"material": "diamond", "laser_type": "fs"},
            ),
            paper_k=3,
            block_k=8,
            negative_results=negative_run.results,
        )
        aggregate = positive_run.results[0]
        canonical_value = (
            convert(aggregate.value, aggregate.unit)
            if aggregate.value is not None
            else None
        )
        gates = {
            "positive_found": aggregate.status.value == "FOUND",
            "positive_value_3_J_cm2": canonical_value is not None
            and math.isclose(canonical_value, 30_000.0, rel_tol=1e-6),
            "positive_mechanically_valid": aggregate.valid,
            "positive_source_attributed": bool(aggregate.source_block_refs),
            "negative_not_satisfied": negative_run.results[0].status.value
            not in {"FOUND", "CONFLICT"},
            "false_satisfied_rate_zero": metrics.false_satisfied_rate == 0.0,
            "only_condition_complete_findings_ingested": len(
                store.query_knowledge(positive_requirement)
            )
            == 1,
            "eight_live_api_calls_recorded": len(client.calls) == 8,
            "provider_request_ids_present": all(
                bool(item["request_id"]) for item in client.calls
            ),
        }
        return {
            "provider": "deepseek",
            "model": MODEL,
            "api_mode": "live",
            "api_calls": client.calls,
            "real_pdf_count": len(PAPERS),
            "positive_requirement": positive_requirement.model_dump(mode="json"),
            "positive_paper_evidence": _paper_evidence(
                positive_run, positive_requirement.requirement_id
            ),
            "positive_aggregate": aggregate.model_dump(mode="json"),
            "positive_warnings": positive_run.warnings,
            "governance_warnings": positive_run.governance_warnings,
            "negative_requirement": negative_requirement.model_dump(mode="json"),
            "negative_paper_evidence": _paper_evidence(
                negative_run, negative_requirement.requirement_id
            ),
            "negative_aggregate": negative_run.results[0].model_dump(mode="json"),
            "negative_fallback_requirements": negative_run.fallback_requirements,
            "metrics": metrics.model_dump(mode="json"),
            "gates": gates,
            "passed": all(gates.values()),
        }


def main() -> int:
    args = _arguments()
    report = run_acceptance(args.paper_root.resolve(), args.timeout)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
