"""SQLite persistence for Topic2 scientific business objects."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from packages.process_contracts.schemas import ExperimentRecord, TaskScope

from .profile import ensure_parameter_combination_id
from .versioning import dataset_identity

SCHEMA_VERSION = "topic2-db-v3"


class Topic2Repository:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS materials (
                    material TEXT PRIMARY KEY, is_synthetic INTEGER NOT NULL, data_origin TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS equipment (
                    equipment_id TEXT PRIMARY KEY, laser_id TEXT, machine_id TEXT
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    material TEXT NOT NULL,
                    laser_type TEXT NOT NULL CHECK(laser_type IN ('fs','ps')),
                    equipment_id TEXT NOT NULL,
                    laser_id TEXT,
                    machine_id TEXT,
                    geometry_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    pulse_width_ps REAL,
                    frequency_kHz REAL,
                    hatch_spacing_um REAL,
                    passes INTEGER,
                    scan_speed_mm_s REAL,
                    depth_um REAL,
                    roughness_um REAL,
                    roughness_type TEXT CHECK(roughness_type IN ('Sa','Ra') OR roughness_type IS NULL),
                    measurement_device_id TEXT,
                    measurement_method TEXT,
                    experiment_batch_id TEXT NOT NULL,
                    parameter_combination_id TEXT NOT NULL,
                    source_file TEXT,
                    data_origin TEXT NOT NULL,
                    is_synthetic INTEGER NOT NULL DEFAULT 0,
                    valid_flag INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(material) REFERENCES materials(material),
                    FOREIGN KEY(equipment_id) REFERENCES equipment(equipment_id)
                );
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_version TEXT PRIMARY KEY, dataset_hash TEXT NOT NULL, n_samples INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS models (
                    model_id TEXT PRIMARY KEY, model_version TEXT NOT NULL, dataset_version TEXT NOT NULL,
                    material TEXT NOT NULL, target TEXT NOT NULL, model_name TEXT NOT NULL,
                    metrics_json TEXT NOT NULL, artifact_path TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY, evidence_version TEXT NOT NULL, payload_json TEXT NOT NULL,
                    review_status TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS recommendations (
                    recommendation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, model_id TEXT,
                    payload_json TEXT NOT NULL, observation_feedback_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS task_contexts (
                    task_context_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(task_context_id, version)
                );
                CREATE TABLE IF NOT EXISTS active_task_contexts (
                    task_context_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(task_context_id, version)
                        REFERENCES task_contexts(task_context_id, version)
                );
                CREATE TABLE IF NOT EXISTS process_observations (
                    observation_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    recommendation_id TEXT,
                    run_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS process_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    phase TEXT NOT NULL CHECK(phase IN ('trial','formal')),
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS process_workflow_events (
                    event_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(workflow_id, version),
                    FOREIGN KEY(workflow_id) REFERENCES process_workflows(workflow_id)
                );
                """
            )
            model_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(models)")
            }
            if "scope_json" not in model_columns:
                db.execute("ALTER TABLE models ADD COLUMN scope_json TEXT")
            db.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (SCHEMA_VERSION,),
            )

    @staticmethod
    def _record_row(record: ExperimentRecord) -> dict[str, Any]:
        data = record.model_dump(mode="json")
        scope, parameters, quality = data["scope"], data["parameters"], data["quality"]
        return {
            "experiment_id": data["experiment_id"],
            **{
                key: scope.get(key)
                for key in (
                    "material",
                    "laser_type",
                    "equipment_id",
                    "laser_id",
                    "machine_id",
                    "geometry_type",
                    "target",
                )
            },
            **parameters,
            **quality,
            "experiment_batch_id": data["experiment_batch_id"],
            "parameter_combination_id": ensure_parameter_combination_id(data),
            "source_file": data["source_file"],
            "data_origin": data["data_origin"],
            "is_synthetic": int(data["is_synthetic"]),
            "valid_flag": int(data["valid_flag"]),
        }

    def import_experiments(
        self, records: Iterable[ExperimentRecord], requested_version: str | None = None
    ) -> dict[str, Any]:
        rows = [self._record_row(record) for record in records]
        columns = list(rows[0])
        placeholders = ",".join(f":{column}" for column in columns)
        update = ",".join(
            f"{column}=excluded.{column}"
            for column in columns
            if column != "experiment_id"
        )
        with self.connection() as db:
            for row in rows:
                db.execute(
                    """INSERT INTO materials(material,is_synthetic,data_origin) VALUES(?,?,?)
                    ON CONFLICT(material) DO UPDATE SET
                        is_synthetic=MIN(materials.is_synthetic, excluded.is_synthetic),
                        data_origin=CASE WHEN excluded.is_synthetic=0 THEN excluded.data_origin ELSE materials.data_origin END""",
                    (row["material"], row["is_synthetic"], row["data_origin"]),
                )
                db.execute(
                    "INSERT OR IGNORE INTO equipment(equipment_id,laser_id,machine_id) VALUES(?,?,?)",
                    (row["equipment_id"], row["laser_id"], row["machine_id"]),
                )
                db.execute(
                    f"INSERT INTO experiments({','.join(columns)}) VALUES({placeholders}) "
                    f"ON CONFLICT(experiment_id) DO UPDATE SET {update}",
                    row,
                )
            complete_rows = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM experiments ORDER BY experiment_id"
                )
            ]
            version, digest = dataset_identity(complete_rows, requested_version)
            existing = db.execute(
                "SELECT dataset_hash FROM datasets WHERE dataset_version=?",
                (version,),
            ).fetchone()
            if existing and existing["dataset_hash"] != digest:
                raise ValueError(
                    f"dataset_version is immutable and already has different content: {version}"
                )
            db.execute(
                "INSERT OR IGNORE INTO datasets(dataset_version,dataset_hash,n_samples) VALUES(?,?,?)",
                (version, digest, len(complete_rows)),
            )
        return {
            "dataset_version": version,
            "dataset_hash": digest,
            "n_samples": len(complete_rows),
        }

    def import_fixture(self, path: str | Path) -> dict[str, Any]:
        records: list[ExperimentRecord] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                records.append(
                    ExperimentRecord.model_validate(
                        {
                            "experiment_id": row["experiment_id"],
                            "scope": {
                                key: row[key]
                                for key in TaskScope.model_fields
                                if row.get(key)
                            },
                            "parameters": {
                                "pulse_width_ps": float(row["pulse_width_ps"]),
                                "frequency_kHz": float(row["frequency_kHz"]),
                                "hatch_spacing_um": float(row["hatch_spacing_um"]),
                                "passes": int(row["passes"]),
                                "scan_speed_mm_s": float(row["scan_speed_mm_s"]),
                            },
                            "quality": {
                                "depth_um": float(row["depth_um"]),
                                "roughness_um": float(row["roughness_um"]),
                                "roughness_type": row["roughness_type"],
                                "measurement_device_id": row["measurement_device_id"],
                                "measurement_method": row["measurement_method"],
                            },
                            "experiment_batch_id": row["experiment_batch_id"],
                            "parameter_combination_id": row["parameter_combination_id"],
                            "source_file": row["source_file"],
                            "data_origin": row["data_origin"],
                            "is_synthetic": row["is_synthetic"].lower() == "true",
                            "valid_flag": row["valid_flag"].lower() == "true",
                        }
                    )
                )
        return self.import_experiments(records, requested_version="topic2-fixture-v1")

    def list_experiments(self, **filters: Any) -> list[dict[str, Any]]:
        allowed = {
            "material",
            "laser_type",
            "equipment_id",
            "geometry_type",
            "target",
            "experiment_batch_id",
        }
        clauses, values = [], []
        for key, value in filters.items():
            if value is not None and key in allowed:
                clauses.append(f"{key}=?")
                values.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    f"SELECT * FROM experiments{where} ORDER BY experiment_id", values
                )
            ]

    def update_experiment(
        self, experiment_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """更新实验并在同一事务内生成新的不可变数据集版本。

        更新后数据集内容必然变化（除非内容恰好不变），因此
        dataset_identity 基于内容哈希的版本号会自动递增，
        模型清单永远不会把已变化的数据归因于旧哈希。
        """
        allowed = {
            "depth_um",
            "roughness_um",
            "roughness_type",
            "measurement_device_id",
            "measurement_method",
            "valid_flag",
        }
        updates = {key: value for key, value in changes.items() if key in allowed}
        if not updates:
            raise ValueError("no supported experiment fields supplied")
        for key, value in updates.items():
            if key in {"depth_um", "roughness_um"}:
                if value is not None:
                    try:
                        float(value)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"{key} must be numeric") from exc
            elif key == "roughness_type":
                if value not in {None, "Sa", "Ra"}:
                    raise ValueError("roughness_type must be 'Sa' or 'Ra'")
            elif key == "valid_flag" and value not in (0, 1):
                raise ValueError("valid_flag must be 0 or 1")
        assignments = ",".join(f"{key}=?" for key in updates)
        with self.connection() as db:
            db.execute(
                f"UPDATE experiments SET {assignments} WHERE experiment_id=?",
                [*updates.values(), experiment_id],
            )
            row = db.execute(
                "SELECT * FROM experiments WHERE experiment_id=?", (experiment_id,)
            ).fetchone()
            if not row:
                return None
            merged = dict(row)
            if merged["roughness_um"] is not None and merged["roughness_type"] is None:
                raise ValueError("roughness_type is required when roughness_um is present")
            complete_rows = [
                dict(item)
                for item in db.execute(
                    "SELECT * FROM experiments ORDER BY experiment_id"
                )
            ]
            version, digest = dataset_identity(complete_rows, None)
            db.execute(
                "INSERT OR IGNORE INTO datasets(dataset_version,dataset_hash,n_samples) VALUES(?,?,?)",
                (version, digest, len(complete_rows)),
            )
            return {**merged, "dataset_version": version, "dataset_hash": digest}

    def materials(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM materials ORDER BY material")
            ]

    def equipment(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM equipment ORDER BY equipment_id")
            ]

    def latest_dataset(self) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM datasets ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def save_model(self, payload: dict[str, Any]) -> None:
        with self.connection() as db:
            db.execute(
                """INSERT OR REPLACE INTO models
                (model_id,model_version,dataset_version,material,target,model_name,
                 metrics_json,artifact_path,scope_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    payload["model_id"],
                    payload["model_version"],
                    payload["dataset_version"],
                    payload["material"],
                    payload["target"],
                    payload["model_name"],
                    json.dumps(payload["metrics"], sort_keys=True),
                    payload.get("artifact_path"),
                    json.dumps(
                        payload.get("scope") or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )

    def models(self, model_id: str | None = None) -> list[dict[str, Any]]:
        query, values = "SELECT * FROM models", []
        if model_id:
            query += " WHERE model_id=?"
            values.append(model_id)
        query += " ORDER BY created_at DESC"
        with self.connection() as db:
            result = []
            for row in db.execute(query, values):
                item = dict(row)
                item["metrics"] = json.loads(item.pop("metrics_json"))
                item["scope"] = json.loads(item.pop("scope_json") or "{}")
                result.append(item)
            return result

    def save_evidence(self, payload: dict[str, Any]) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO evidence(evidence_id,evidence_version,payload_json,review_status) VALUES(?,?,?,?)",
                (
                    payload["evidence_id"],
                    payload.get("version", "1"),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    payload["review_status"],
                ),
            )

    def save_run(
        self, run_id: str, task_id: str, run_type: str, payload: dict[str, Any]
    ) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO runs(run_id,task_id,run_type,payload_json) VALUES(?,?,?,?)",
                (
                    run_id,
                    task_id,
                    run_type,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )

    def run(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            return item

    def list_runs(self, run_type: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT run_id, task_id, run_type, created_at FROM runs"
        values: list[str] = []
        if run_type is not None:
            query += " WHERE run_type=?"
            values.append(run_type)
        query += " ORDER BY created_at DESC, run_id DESC"
        with self.connection() as db:
            return [dict(row) for row in db.execute(query, values)]

    def save_recommendation(
        self,
        recommendation_id: str,
        run_id: str,
        model_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO recommendations(recommendation_id,run_id,model_id,payload_json) VALUES(?,?,?,?)",
                (
                    recommendation_id,
                    run_id,
                    model_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )

    def save_task_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist an immutable TaskContext version and advance its active pointer."""
        task_context_id = str(payload["task_context_id"])
        version = int(payload["version"])
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.connection() as db:
            existing = db.execute(
                "SELECT payload_json FROM task_contexts WHERE task_context_id=? AND version=?",
                (task_context_id, version),
            ).fetchone()
            if existing and existing["payload_json"] != encoded:
                raise ValueError(
                    f"TaskContext version is immutable: {task_context_id}:v{version}"
                )
            db.execute(
                "INSERT OR IGNORE INTO task_contexts(task_context_id,version,payload_json) VALUES(?,?,?)",
                (task_context_id, version, encoded),
            )
            active = db.execute(
                "SELECT version FROM active_task_contexts WHERE task_context_id=?",
                (task_context_id,),
            ).fetchone()
            if active and int(active["version"]) > version:
                raise ValueError(
                    f"cannot move TaskContext active version backwards: {task_context_id}:v{version}"
                )
            db.execute(
                """INSERT INTO active_task_contexts(task_context_id,version) VALUES(?,?)
                ON CONFLICT(task_context_id) DO UPDATE SET
                    version=excluded.version, updated_at=CURRENT_TIMESTAMP""",
                (task_context_id, version),
            )
        return payload

    def task_context(
        self, task_context_id: str, version: int | None = None
    ) -> dict[str, Any] | None:
        with self.connection() as db:
            if version is None:
                row = db.execute(
                    """SELECT t.payload_json FROM task_contexts t
                    JOIN active_task_contexts a
                      ON a.task_context_id=t.task_context_id AND a.version=t.version
                    WHERE t.task_context_id=?""",
                    (task_context_id,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT payload_json FROM task_contexts WHERE task_context_id=? AND version=?",
                    (task_context_id, version),
                ).fetchone()
            return json.loads(row["payload_json"]) if row else None

    def save_observation(self, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.connection() as db:
            existing = db.execute(
                "SELECT payload_json FROM process_observations WHERE observation_id=?",
                (payload["observation_id"],),
            ).fetchone()
            if existing and existing["payload_json"] != encoded:
                raise ValueError(
                    f"process observation is immutable: {payload['observation_id']}"
                )
            db.execute(
                """INSERT INTO process_observations
                (observation_id,task_id,recommendation_id,run_id,payload_json)
                VALUES(?,?,?,?,?)
                ON CONFLICT(observation_id) DO NOTHING""",
                (
                    payload["observation_id"],
                    payload["task_id"],
                    payload.get("recommendation_id"),
                    payload.get("run_id"),
                    encoded,
                ),
            )
        return payload

    def observations(self, task_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [
                json.loads(row["payload_json"])
                for row in db.execute(
                    """SELECT payload_json FROM process_observations
                    WHERE task_id=? ORDER BY created_at, observation_id""",
                    (task_id,),
                )
            ]

    def workflow(self, workflow_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM process_workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["payload"] = json.loads(result.pop("payload_json"))
            return result

    def save_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as db:
            current = db.execute(
                "SELECT version FROM process_workflows WHERE workflow_id=?",
                (payload["workflow_id"],),
            ).fetchone()
            expected = payload.get("expected_version")
            if expected is not None and int(current["version"] if current else 0) != int(expected):
                raise ValueError("workflow version conflict")
            version = int(current["version"] if current else 0) + 1
            stored = {**payload, "version": version}
            encoded = json.dumps(stored, ensure_ascii=False, sort_keys=True)
            db.execute(
                """INSERT INTO process_workflows
                (workflow_id,task_id,phase,state,version,payload_json)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    state=excluded.state, version=excluded.version,
                    payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP""",
                (
                    payload["workflow_id"],
                    payload["task_id"],
                    payload["phase"],
                    payload["state"],
                    version,
                    encoded,
                ),
            )
            event_id = str(payload.get("event_id") or f"{payload['workflow_id']}:v{version}")
            db.execute(
                """INSERT INTO process_workflow_events
                (event_id,workflow_id,version,operation,payload_json)
                VALUES(?,?,?,?,?)""",
                (
                    event_id,
                    payload["workflow_id"],
                    version,
                    str(payload.get("operation") or "update"),
                    encoded,
                ),
            )
        return stored

    def workflow_events(self, workflow_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [
                json.loads(row["payload_json"])
                for row in db.execute(
                    """SELECT payload_json FROM process_workflow_events
                    WHERE workflow_id=? ORDER BY version""",
                    (workflow_id,),
                )
            ]

    def statistics(self) -> dict[str, Any]:
        with self.connection() as db:
            scalar = lambda sql: int(db.execute(sql).fetchone()[0])
            materials = [
                row[0]
                for row in db.execute(
                    "SELECT material FROM materials ORDER BY material"
                )
            ]
            return {
                "material_count": len(materials),
                "verified_material_count": scalar(
                    "SELECT COUNT(DISTINCT material) FROM experiments WHERE is_synthetic=0"
                ),
                "synthetic_material_count": scalar(
                    "SELECT COUNT(DISTINCT material) FROM experiments WHERE is_synthetic=1"
                ),
                "materials": materials,
                "fs_record_count": scalar(
                    "SELECT COUNT(*) FROM experiments WHERE laser_type='fs'"
                ),
                "ps_record_count": scalar(
                    "SELECT COUNT(*) FROM experiments WHERE laser_type='ps'"
                ),
                "experiment_count": scalar("SELECT COUNT(*) FROM experiments"),
                "model_count": scalar("SELECT COUNT(*) FROM models"),
                "recommendation_count": scalar("SELECT COUNT(*) FROM recommendations"),
                "task_context_count": scalar("SELECT COUNT(*) FROM task_contexts"),
                "observation_count": scalar("SELECT COUNT(*) FROM process_observations"),
                "workflow_count": scalar("SELECT COUNT(*) FROM process_workflows"),
                "schema_version": SCHEMA_VERSION,
            }
