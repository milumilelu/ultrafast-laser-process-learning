"""Real-PDF + real-DeepSeek acceptance for the Evidence→Prior V1.

The API key is restored from the configured encrypted store into the process
environment and is never serialized.  All scientific/equipment data is built
inside a temporary SQLite database.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ultrafast_evidence_prior.schemas import TaskRequestV1, ValidationState
from ultrafast_evidence_prior.service import EvidencePriorAnalysisService
from ultrafast_knowledge.evidence_pipeline import (
    ScientificIndexIngestionService,
    ScientificIndexStore,
)
from ultrafast_memory.core.llm_config import restore_api_key_from_store
from ultrafast_memory.equipment.schemas import EquipmentProfileCreate
from ultrafast_memory.equipment.service import create_equipment_profile
from ultrafast_memory.llm.factory import create_llm_client
from ultrafast_shared.config.loader import load_config

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
        {"material": "4H-SiC", "material_grade": "4H", "laser_type": "ps"},
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


class AuditedClient:
    def __init__(self) -> None:
        restore_api_key_from_store()
        config = load_config().get("llm", {})
        configured = {
            **config,
            "provider": "deepseek",
            "model": MODEL,
            "api_base": "https://api.deepseek.com",
            "api_key_env": "DEEPSEEK_API_KEY",
            "api_key_available": True,
        }
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise RuntimeError("DEEPSEEK_API_KEY is unavailable after encrypted-store restore")
        self._client = create_llm_client(configured)
        self.model = MODEL
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


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paper-root",
        type=Path,
        default=Path("artifacts/b1_annotation/papers"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/live_evidence_prior_acceptance.json"),
    )
    parser.add_argument("--paper-top-k", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def run_acceptance(
    paper_root: Path,
    *,
    paper_top_k: int,
    timeout: float,
) -> dict[str, Any]:
    paths = [paper_root / name for name, _title, _metadata in PAPERS]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"real acceptance PDFs are missing: {missing}")

    with tempfile.TemporaryDirectory(prefix="evidence-prior-live-") as temporary:
        database = Path(temporary) / "evidence-prior-live.db"
        os.environ["ULTRAFAST_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"

        @contextmanager
        def connection_factory():
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
            finally:
                connection.close()

        client = AuditedClient()
        connection_check = client.test_connection()
        equipment = create_equipment_profile(
            EquipmentProfileCreate(
                profile_name="Live 30 fs evidence acceptance system",
                machine_id="LIVE-ACCEPTANCE-ONLY",
                created_by="run_live_evidence_prior_acceptance.py",
                laser_source={
                    "wavelength_nm": 800,
                    "pulse_width_min_fs": 25,
                    "pulse_width_max_fs": 35,
                    "rated_max_power_W": 20,
                    "power_transmission_ratio": 0.8,
                    "frequency_min_kHz": 1,
                    "frequency_max_kHz": 1000,
                },
                optical_setup={"spot_diameter_um": 20},
                motion_system={
                    "scan_speed_min_mm_s": 1,
                    "scan_speed_max_mm_s": 2000,
                },
                field_verification={
                    "wavelength_nm": "MANUFACTURER_SPEC",
                    "pulse_width_min_fs": "MANUFACTURER_SPEC",
                    "pulse_width_max_fs": "MANUFACTURER_SPEC",
                    "rated_max_power_W": "MANUFACTURER_SPEC",
                    "power_transmission_ratio": "ESTIMATED",
                    "frequency_min_kHz": "MANUFACTURER_SPEC",
                    "frequency_max_kHz": "MANUFACTURER_SPEC",
                    "spot_diameter_um": "MANUFACTURER_SPEC",
                    "scan_speed_min_mm_s": "MANUFACTURER_SPEC",
                    "scan_speed_max_mm_s": "MANUFACTURER_SPEC",
                },
                set_active=True,
            )
        )
        store = ScientificIndexStore(connection_factory)
        ingestion = ScientificIndexIngestionService(store).ingest_many(
            [
                {
                    "pdf_path": path,
                    "title": title,
                    "metadata": metadata,
                }
                for path, (_name, title, metadata) in zip(paths, PAPERS, strict=True)
            ]
        )
        service = EvidencePriorAnalysisService(
            client,
            connection=connection_factory,
            paper_top_k=paper_top_k,
            windows_per_paper=8,
            llm_timeout=timeout,
        )
        result = service.analyze(
            TaskRequestV1(
                material="diamond",
                equipment_profile_id=equipment["equipment_profile_id"],
                equipment_revision_id=equipment["revision_id"],
                target_metric="depth_um",
            ),
            force_reextract=True,
        )
        validated = [
            item
            for item in result.evidence.items
            if item.validation_state == ValidationState.VALIDATED
        ]
        rejected = [
            item
            for item in result.evidence.items
            if item.validation_state == ValidationState.REJECTED
        ]
        with connection_factory() as connection:
            knowledge_count = connection.execute(
                "SELECT COUNT(*) FROM structured_scientific_knowledge_v2"
            ).fetchone()[0]
        checks = {
            "real_pdf_count": len(ingestion["document_versions"]),
            "real_llm_calls": len(client.calls),
            "service_llm_call_count": result.evidence.llm_call_count,
            "all_provider_models_match": all(call.get("model") == MODEL for call in client.calls),
            "validated_evidence_count": len(validated),
            "rejected_evidence_count": len(rejected),
            "structured_knowledge_count": knowledge_count,
            "belief_count": len(result.beliefs.beliefs),
            "prior_count": len(result.priors.priors),
            "all_beliefs_reference_validated_evidence": all(
                belief.evidence_id in {item.evidence_id for item in validated}
                for belief in result.beliefs.beliefs
            ),
            "governance_non_gating_warning_present": any(
                "治理状态未限制" in warning for warning in result.warnings
            ),
        }
        passed = (
            checks["real_pdf_count"] == len(PAPERS)
            and checks["real_llm_calls"] > 0
            and checks["real_llm_calls"] == checks["service_llm_call_count"]
            and checks["all_provider_models_match"]
            and checks["validated_evidence_count"] > 0
            and checks["structured_knowledge_count"] == checks["validated_evidence_count"]
            and checks["belief_count"] > 0
            and checks["prior_count"] > 0
            and checks["all_beliefs_reference_validated_evidence"]
            and checks["governance_non_gating_warning_present"]
        )
        return {
            "passed": passed,
            "actual_llm": True,
            "provider": "deepseek",
            "requested_model": MODEL,
            "connection_check": connection_check,
            "database_scope": "temporary",
            "paper_files": [str(path) for path in paths],
            "checks": checks,
            "provider_calls": client.calls,
            "analysis": result.model_dump(mode="json"),
        }


def main() -> int:
    options = arguments()
    report = run_acceptance(
        options.paper_root,
        paper_top_k=options.paper_top_k,
        timeout=options.timeout,
    )
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "passed": report["passed"],
        "output": str(options.output),
        "checks": report["checks"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
