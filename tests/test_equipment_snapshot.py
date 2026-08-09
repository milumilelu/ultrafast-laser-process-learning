"""Equipment semantics against the user's persisted equipment archive.

No equipment measurement is invented here.  The tests read the real local
archive and verify that legacy power fields are never reinterpreted as the new
workpiece-plane capability contract.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from apps.topic2_backend.application.equipment import resolve_machine_snapshot
from apps.topic2_backend.application.service import Topic2ApplicationService
from packages.process_contracts.equipment import snapshot_from_profile

REPO = Path(__file__).resolve().parents[1]
MEMORY_DB = REPO / "data" / "ultrafast_memory.db"


def _real_active_profile() -> dict:
    if not MEMORY_DB.exists():
        pytest.skip(f"real equipment archive missing: {MEMORY_DB}")
    with sqlite3.connect(MEMORY_DB) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM equipment_profile WHERE is_active = 1 "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            pytest.skip("real equipment archive has no active profile")
        profile = dict(row)
        profile["field_verification"] = json.loads(
            profile.pop("field_verification_json") or "{}"
        )
        for section, table in (
            ("laser_source", "laser_source_config"),
            ("optical_setup", "optical_setup_config"),
            ("motion_system", "motion_system_config"),
            ("process_capability", "process_capability_config"),
        ):
            section_row = connection.execute(
                f"SELECT * FROM {table} WHERE equipment_profile_id = ?",
                (profile["equipment_profile_id"],),
            ).fetchone()
            values = dict(section_row) if section_row else {}
            extras = json.loads(values.pop("parameters_json", None) or "{}")
            values.update(extras)
            profile[section] = {
                key: value
                for key, value in values.items()
                if key not in {"config_id", "equipment_profile_id"}
                and value is not None
            }
        revision = connection.execute(
            "SELECT revision_id FROM equipment_config_revision "
            "WHERE equipment_profile_id = ? ORDER BY revision_number DESC LIMIT 1",
            (profile["equipment_profile_id"],),
        ).fetchone()
        profile["revision_id"] = revision["revision_id"] if revision else None
        return profile


def test_real_profile_keeps_capability_separate_from_task_power() -> None:
    profile = _real_active_profile()
    snapshot = snapshot_from_profile(profile, source_quality="RESEARCH_AGENT")

    assert "actual_power_W" not in snapshot.fields
    laser = profile["laser_source"]
    has_surface_bounds = all(
        laser.get(name) is not None
        for name in (
            "workpiece_incident_power_min_W",
            "workpiece_incident_power_max_W",
        )
    )
    if not has_surface_bounds:
        assert {
            "workpiece_incident_power_min_W",
            "workpiece_incident_power_max_W",
        }.issubset(snapshot.missing_required)
        assert "laser_power_W" not in snapshot.machine_bounds
    else:
        assert snapshot.machine_bounds["laser_power_W"] == {
            "lower": float(laser["workpiece_incident_power_min_W"]),
            "upper": float(laser["workpiece_incident_power_max_W"]),
        }


def test_legacy_maximum_is_not_silently_promoted_to_surface_range() -> None:
    profile = _real_active_profile()
    laser = profile["laser_source"]
    if laser.get("actual_max_power_W") is None:
        pytest.skip("real profile no longer contains the legacy maximum field")
    assert laser.get("workpiece_incident_power_min_W") is None
    snapshot = snapshot_from_profile(profile, source_quality="RESEARCH_AGENT")
    assert "laser_power_W" not in snapshot.machine_bounds


def test_execution_context_fails_closed_until_real_surface_bounds_exist() -> None:
    profile = _real_active_profile()
    laser = profile["laser_source"]
    if laser.get("workpiece_incident_power_min_W") is not None:
        pytest.skip("real profile has already been upgraded with measured bounds")
    snapshot = snapshot_from_profile(profile, source_quality="RESEARCH_AGENT")
    context = Topic2ApplicationService._build_execution_context(
        {
            "process_parameters": {
                "laser_power_W": laser.get("actual_max_power_W"),
                "laser_power_location": "WORKPIECE_SURFACE_INCIDENT",
            }
        },
        snapshot.model_dump(mode="json"),
    )
    assert context["status"] == "BLOCKED"
    assert any("缺少材料表面" in reason for reason in context["reasons"])


def test_unresolvable_research_profile_uses_new_required_fields() -> None:
    snapshot = resolve_machine_snapshot(
        equipment_profile_id="UNRESOLVED",
        run_mode="research",
        task_spec={"execution_mode": "RESEARCH"},
        agent_proxy_target=None,
        fixture_profiles={},
    )
    assert snapshot.resource_status == "BLOCKED"
    assert set(snapshot.missing_required) == {
        "wavelength_nm",
        "workpiece_incident_power_min_W",
        "workpiece_incident_power_max_W",
        "beam_radius_um",
    }
