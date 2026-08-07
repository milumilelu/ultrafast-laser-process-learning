"""Topic2 backend settings with environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_path: Path = ROOT / "data" / "topic2.db"
    fixture_path: Path = ROOT / "data" / "test_fixture" / "topic2_experiments_v1.csv"
    artifact_dir: Path = ROOT / "model_artifacts"
    report_dir: Path = ROOT / "outputs" / "topic2_acceptance"
    auto_seed_fixture: bool = True
    random_seed: int = 42
    cv_folds: int = 5
    bo_beta: float = 2.0
    lambda_0: float = 0.2
    alpha: float = 0.1
    bo_candidate_count: int = 1000
    candidate_models: tuple[str, ...] = (
        "RSM",
        "GPR",
        "RandomForest",
        "HistGradientBoosting",
    )

    @classmethod
    def from_env(cls) -> Settings:
        config_path = Path(os.getenv("TOPIC2_CONFIG", ROOT / "configs" / "topic2.yaml"))
        config = (
            yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if config_path.exists()
            else {}
        )
        modeling = config.get("modeling", {})
        optimization = config.get("optimization", {})
        paths = config.get("paths", {})
        return cls(
            database_path=Path(
                os.getenv(
                    "TOPIC2_DB_PATH", ROOT / paths.get("database", "data/topic2.db")
                )
            ),
            fixture_path=Path(
                os.getenv(
                    "TOPIC2_FIXTURE_PATH",
                    ROOT
                    / paths.get(
                        "fixture", "data/test_fixture/topic2_experiments_v1.csv"
                    ),
                )
            ),
            artifact_dir=Path(
                os.getenv(
                    "TOPIC2_ARTIFACT_DIR",
                    ROOT / paths.get("artifact_dir", "model_artifacts"),
                )
            ),
            report_dir=Path(
                os.getenv(
                    "TOPIC2_REPORT_DIR",
                    ROOT / paths.get("report_dir", "outputs/topic2_acceptance"),
                )
            ),
            auto_seed_fixture=os.getenv(
                "TOPIC2_AUTO_SEED_FIXTURE", str(config.get("auto_seed_fixture", True))
            ).lower()
            == "true",
            random_seed=int(
                os.getenv("TOPIC2_RANDOM_SEED", str(config.get("random_seed", 42)))
            ),
            cv_folds=int(
                os.getenv("TOPIC2_CV_FOLDS", str(modeling.get("cv_folds", 5)))
            ),
            bo_beta=float(
                os.getenv("TOPIC2_BO_BETA", str(optimization.get("beta", 2.0)))
            ),
            lambda_0=float(
                os.getenv("TOPIC2_LAMBDA_0", str(optimization.get("lambda_0", 0.2)))
            ),
            alpha=float(os.getenv("TOPIC2_ALPHA", str(optimization.get("alpha", 0.1)))),
            bo_candidate_count=int(
                os.getenv(
                    "TOPIC2_BO_CANDIDATES",
                    str(optimization.get("candidate_count", 1000)),
                )
            ),
            candidate_models=tuple(
                modeling.get(
                    "candidate_models",
                    ("RSM", "GPR", "RandomForest", "HistGradientBoosting"),
                )
            ),
        )
