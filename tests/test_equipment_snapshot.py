"""M1: canonical MachineProfileSnapshot resolution semantics.

- RESEARCH_AGENT / DEMO_FIXTURE share one implementation (same profile shape).
- SANDBOX task override is provisional and marked TASK_OVERRIDE.
- Unresolvable profiles fail closed to a BLOCKED snapshot (no silent defaults).
- average_power_max_W is never silently used as actual_power_W.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from apps.topic2_backend.application.equipment import (
    effective_execution_mode,
    resolve_machine_snapshot,
)
from packages.process_contracts.equipment import (
    MachineProfileSnapshot,
    snapshot_from_profile,
    snapshot_from_task_override,
)

FIXTURE_PROFILE = {
    "equipment_profile_id": "DEMO-FS-LASER-01",
    "revision_id": "rev-1",
    "laser_source": {
        "wavelength_nm": 1030.0,
        "pulse_width_fixed_fs": 300.0,
        "average_power_min_W": 1.0,
        "average_power_max_W": 20.0,
        "actual_power_W": 10.0,
        "frequency_min_kHz": 50.0,
        "frequency_max_kHz": 1000.0,
    },
    "optical_setup": {"spot_diameter_um": 16.0},
    "motion_system": {
        "scan_speed_min_mm_s": 50.0,
        "scan_speed_max_mm_s": 2000.0,
    },
    "process_capability": {},
}


def test_fixture_profile_resolves_ready() -> None:
    snapshot = snapshot_from_profile(FIXTURE_PROFILE, source_quality="DEMO_FIXTURE")
    assert snapshot.schema_version == "machine-profile-snapshot-v1"
    assert snapshot.resource_status == "READY"
    assert snapshot.missing_required == []
    assert snapshot.value("actual_power_W") == 10.0
    assert snapshot.value("wavelength_nm") == 1030.0
    # beam radius is DERIVED from spot diameter/2, never guessed
    assert snapshot.value("beam_radius_um") == 8.0
    assert snapshot.fields["beam_radius_um"].status == "DERIVED"
    assert "derived from spot_diameter_um/2" in snapshot.fields[
        "beam_radius_um"
    ].provenance
    assert snapshot.machine_bounds["frequency_kHz"] == {
        "lower": 50.0,
        "upper": 1000.0,
    }
    assert snapshot.machine_bounds["pulse_width_ps"] == {
        "lower": 0.3,
        "upper": 0.3,
    }
    # agent and fixture share the same builder
    agent = snapshot_from_profile(FIXTURE_PROFILE, source_quality="RESEARCH_AGENT")
    assert agent.resource_status == "READY"
    assert agent.value("actual_power_W") == snapshot.value("actual_power_W")
    assert agent.fields["actual_power_W"].provenance[0] == (
        "equipment_profile:DEMO-FS-LASER-01"
    )


def test_missing_power_fails_closed_not_from_max() -> None:
    partial = dict(FIXTURE_PROFILE)
    partial["laser_source"] = dict(FIXTURE_PROFILE["laser_source"])
    del partial["laser_source"]["actual_power_W"]
    snapshot = snapshot_from_profile(partial, source_quality="DEMO_FIXTURE")
    assert snapshot.resource_status == "PARTIAL"
    assert "actual_power_W" in snapshot.missing_required
    assert snapshot.value("actual_power_W") is None
    # average_power_max_W never silently becomes the actual power
    assert any("average_power_max_W" in w for w in snapshot.warnings)


def test_sandbox_task_override_is_provisional() -> None:
    snapshot = snapshot_from_task_override(
        {
            "actual_power_W": 5.0,
            "actual_power_W_verified": True,
            "beam_radius_um": 10.0,
            "wavelength_nm": 1030.0,
        },
        equipment_profile_id="EQ-TEST-FS",
    )
    assert snapshot.source_quality == "TASK_OVERRIDE"
    assert snapshot.resource_status == "READY"
    assert snapshot.value("beam_radius_um") == 10.0
    assert any("SANDBOX" in w for w in snapshot.warnings)


def test_unresolvable_profile_is_blocked() -> None:
    snapshot = resolve_machine_snapshot(
        equipment_profile_id="EQ-NOPE",
        run_mode="research",
        task_spec={},
        agent_proxy_target=None,
        fixture_profiles={"DEMO-FS-LASER-01": FIXTURE_PROFILE},
    )
    assert snapshot.resource_status == "BLOCKED"
    assert set(snapshot.missing_required) == {
        "wavelength_nm",
        "actual_power_W",
        "beam_radius_um",
    }
    assert all(
        state.status == "MISSING" for state in snapshot.fields.values()
    )


def test_fixture_store_resolution_order() -> None:
    # fixture store wins over agent for DEMO_FIXTURE quality
    snapshot = resolve_machine_snapshot(
        equipment_profile_id="DEMO-FS-LASER-01",
        run_mode="research",
        task_spec={"execution_mode": "DEMO_FIXTURE"},
        agent_proxy_target="http://127.0.0.1:1",
        fixture_profiles={"DEMO-FS-LASER-01": FIXTURE_PROFILE},
    )
    assert snapshot.source_quality == "DEMO_FIXTURE"
    assert snapshot.resource_status == "READY"


def test_execution_mode_derivation() -> None:
    assert effective_execution_mode("demo", {}) == "DEMO_FIXTURE"
    assert effective_execution_mode("research", {}) == "RESEARCH"
    assert effective_execution_mode("research", {"execution_mode": "SANDBOX"}) == (
        "SANDBOX"
    )
    assert effective_execution_mode("research", {"execution_mode": "bogus"}) == (
        "RESEARCH"
    )


def test_snapshot_json_roundtrip() -> None:
    snapshot = snapshot_from_profile(FIXTURE_PROFILE, source_quality="DEMO_FIXTURE")
    restored = MachineProfileSnapshot.model_validate(
        snapshot.model_dump(mode="json")
    )
    assert restored == snapshot
