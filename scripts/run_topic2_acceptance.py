"""Generate the frozen Topic2 software-acceptance report bundle."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.topic2_backend.service import Topic2Service
from apps.topic2_backend.settings import Settings
from packages.process_contracts.schemas import (
    CORE_PARAMETER_NAMES,
    Evidence,
    EvidenceProvenance,
    EvidenceScope,
    ModelPolicyRequest,
    ModelTrainRequest,
    OptimizationRequest,
    ParameterBounds,
    ParameterIdentificationRequest,
    TaskScope,
)
from packages.process_data.profile import build_data_profile


def main() -> None:
    settings = Settings.from_env()
    service = Topic2Service(settings)
    scope = TaskScope(
        material="SiC",
        laser_type="fs",
        equipment_id="EQ-TEST-FS",
        laser_id="LASER-TEST-FS",
        machine_id="MACHINE-TEST-A",
        geometry_type="rectangular_groove",
        target="depth_um",
    )
    rows = service._rows_for_scope(scope)
    profile = build_data_profile(rows)
    evidence = Evidence(
        evidence_id="E-SYNTHETIC-ACCEPTANCE-001",
        source_type="process_prior",
        claim_type="range_preference",
        parameter="frequency_kHz",
        target="depth_um",
        claim={"lower": 5.0, "upper": 20.0},
        scope=EvidenceScope(
            material="SiC",
            laser_type="fs",
            geometry_type="rectangular_groove",
            equipment_id="EQ-TEST-FS",
            target="depth_um",
        ),
        provenance=EvidenceProvenance(
            source_id="SYNTHETIC-SOFTWARE-ACCEPTANCE",
            review_id="REV-SYNTHETIC-TEST-001",
        ),
        review_status="approved",
    )
    service.parameter_identification(
        ParameterIdentificationRequest(scope=scope, random_seed=settings.random_seed)
    )
    policy = service.model_policy(
        ModelPolicyRequest(scope=scope, data_profile=profile, evidence=[evidence])
    )
    service.train_model(
        ModelTrainRequest(
            scope=scope,
            candidate_models=policy["candidate_models"],
            cv_folds=settings.cv_folds,
            random_seed=settings.random_seed,
        )
    )
    bounds = {
        name: ParameterBounds(
            lower=float(min(row[name] for row in rows)),
            upper=float(max(row[name] for row in rows)),
        )
        for name in CORE_PARAMETER_NAMES
    }
    service.recommend(
        OptimizationRequest(
            scope=scope,
            machine_bounds=bounds,
            evidence=[evidence],
            beta=settings.bo_beta,
            lambda_0=settings.lambda_0,
            alpha=settings.alpha,
            n_candidates=1000,
            random_seed=settings.random_seed,
        )
    )
    service._export_json("database_statistics.json", service.repository.statistics())
    print(f"Topic2 acceptance reports: {settings.report_dir}")


if __name__ == "__main__":
    main()
