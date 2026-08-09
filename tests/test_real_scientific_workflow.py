"""Scientific acceptance over repository-owned original experimental files.

This suite deliberately does not create equipment measurements, calibration
observations, priors, or papers.  Missing resources must remain BLOCKED.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from apps.topic2_backend.application.service import Topic2ApplicationService
from apps.topic2_backend.service import Topic2Service
from apps.topic2_backend.settings import Settings
from packages.process_contracts.schemas import ExperimentRecord, ModelTrainRequest, TaskScope
from scripts.import_real_data import CSV_SOURCES, XLSX_SOURCE, build_records


@pytest.fixture()
def real_service(tmp_path: Path) -> Topic2Service:
    settings = replace(
        Settings.from_env(),
        database_path=tmp_path / "topic2.db",
        artifact_dir=tmp_path / "artifacts",
        report_dir=tmp_path / "reports",
        equipment_profiles_path=None,
        calibration_fixture_path=None,
        prior_fixture_path=None,
        auto_seed_fixture=False,
        equipment_profiles={},
    )
    service = Topic2Service(settings, approval_verifier=lambda _review_id: False)
    records = [ExperimentRecord.model_validate(item) for item in build_records()]
    service.repository.import_experiments(records)
    return service


def test_original_files_are_the_only_scientific_dataset(real_service: Topic2Service) -> None:
    rows = real_service.repository.list_experiments(real_only=True)
    expected_sources = {path.name for path in [*CSV_SOURCES.values(), *XLSX_SOURCE.values()]}

    assert rows
    assert {row["source_file"] for row in rows} == expected_sources
    assert all(row["is_synthetic"] == 0 for row in rows)
    assert all(row["data_origin"] == "real_machining_data" for row in rows)
    assert len(rows) == len(build_records())
    assert real_service.repository.list_experiments() == rows


def test_model_selection_uses_real_sic_measurements(real_service: Topic2Service) -> None:
    request = ModelTrainRequest(
        scope=TaskScope(
            material="SiC",
            laser_type="fs",
            equipment_id="EQ-REAL",
            geometry_type="rectangular_groove",
            target="depth_um",
        ),
        candidate_models=["RSM"],
        cv_folds=3,
        random_seed=42,
    )
    result = real_service.train_model(request, persist=False)

    assert result["selected_model"] == "RSM"
    assert result["dataset_version"] == real_service.repository.latest_dataset(
        real_only=True
    )["dataset_version"]
    assert result["cv_strategy"] == "GroupKFold(parameter_combination_id)"
    assert set(result["validation_metrics"]) == {"RSM"}


def test_application_auto_resolves_historical_equipment_and_fails_closed(
    real_service: Topic2Service,
) -> None:
    application = Topic2ApplicationService(real_service, agent_proxy_target=None)
    dataset = real_service.repository.latest_dataset(real_only=True)
    summary = application.create_application_run(
        mode="research",
        task_spec={
            "material": "SiC",
            "laser_type": "fs",
            "process_type": "fs_laser_processing",
            "geometry_type": "rectangular_groove",
            "objective_metric": "depth_um",
            "dataset_ref": dataset["dataset_version"],
            "equipment_profile_id": "UNRESOLVED",
            "execution_equipment_ref": {
                "equipment_profile_id": "UNRESOLVED",
                "revision_id": "UNRESOLVED",
            },
            "execution_mode": "RESEARCH",
        },
    )

    assert summary["status"] == "blocked"
    run_id = summary["application_run_id"]
    artifacts = {
        item["artifact_type"]: application.artifact(item["artifact_id"])["content"][
            "content"
        ]
        for item in application.artifacts(run_id)
    }
    assert artifacts["DatasetRef"]["equipment_scope_id"] == "EQ-REAL"
    assert artifacts["DatasetRef"]["status"] == "READY"
    assert artifacts["MachineProfileSnapshot"]["resource_status"] == "BLOCKED"
    assert artifacts["ExecutionContext"]["status"] == "BLOCKED"
