"""Equipment resolution service (M1).

One resolution implementation, two source qualities:

- RESEARCH_AGENT : resolve `equipment_profile_id` from the agent archive
                   over HTTP (AGENT_PROXY_TARGET /equipment/profiles/{id}).
- DEMO_FIXTURE   : resolve from the pre-installed fixture store (identical
                   profile shape, deterministic, marked DEMO_FIXTURE).
- TASK_OVERRIDE  : SANDBOX-only path from task_spec.machine_profile; the
                   snapshot is provisional and never consumed by research.

Fail closed: an unresolvable profile yields a BLOCKED snapshot, never
silent computational defaults.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from packages.process_contracts.equipment import (
    MachineProfileSnapshot,
    SourceQuality,
    build_blocked_snapshot,
    snapshot_from_profile,
    snapshot_from_task_override,
)

EXECUTION_MODES = ("RESEARCH", "DEMO_FIXTURE", "SANDBOX")


class EquipmentResolutionError(Exception):
    """Equipment profile could not be resolved (fail closed)."""


def effective_execution_mode(run_mode: str, task_spec: dict[str, Any]) -> str:
    mode = str(task_spec.get("execution_mode") or "").upper()
    if mode not in EXECUTION_MODES:
        return "DEMO_FIXTURE" if run_mode == "demo" else "RESEARCH"
    return mode


def resolve_machine_snapshot(
    *,
    equipment_profile_id: str,
    equipment_revision_id: str | None = None,
    run_mode: str,
    task_spec: dict[str, Any],
    agent_proxy_target: str | None,
    fixture_profiles: dict[str, dict[str, Any]] | None,
) -> MachineProfileSnapshot:
    """Resolve the canonical MachineProfileSnapshot for a run.

    Resolution is mode-exclusive.  A RESEARCH run can never consume a demo
    fixture merely because the identifiers happen to match.

    - SANDBOX      : task override, then an explicitly selected fixture.
    - DEMO_FIXTURE : fixture store only.
    - RESEARCH     : versioned agent archive only.
    """
    mode = effective_execution_mode(run_mode, task_spec)
    if mode == "SANDBOX" and task_spec.get("machine_profile"):
        return snapshot_from_task_override(
            dict(task_spec["machine_profile"]),
            equipment_profile_id=equipment_profile_id,
        )

    if mode in {"DEMO_FIXTURE", "SANDBOX"}:
        fixture = (fixture_profiles or {}).get(equipment_profile_id)
        if fixture is not None:
            return _snapshot_with_revision_check(
                fixture,
                source_quality="DEMO_FIXTURE",
                requested_revision_id=equipment_revision_id,
            )
        return build_blocked_snapshot(
            equipment_profile_id,
            "DEMO_FIXTURE 设备档案不可解析（fixture store 中不存在）",
        )

    if mode == "RESEARCH" and agent_proxy_target:
        profile = _fetch_agent_profile(
            agent_proxy_target,
            equipment_profile_id,
            equipment_revision_id,
        )
        if profile is not None:
            return _snapshot_with_revision_check(
                profile,
                source_quality="RESEARCH_AGENT",
                requested_revision_id=equipment_revision_id,
            )

    return build_blocked_snapshot(
        equipment_profile_id,
        "RESEARCH 设备档案不可解析（agent 档案不可达或 profile 不存在；禁止回退到 fixture）",
    )


def _snapshot_with_revision_check(
    profile: dict[str, Any],
    *,
    source_quality: SourceQuality,
    requested_revision_id: str | None,
) -> MachineProfileSnapshot:
    actual_revision = str(profile.get("revision_id") or "") or None
    if requested_revision_id and actual_revision != requested_revision_id:
        return build_blocked_snapshot(
            str(profile.get("equipment_profile_id") or "unknown"),
            (
                "equipment revision mismatch: "
                f"requested={requested_revision_id}, resolved={actual_revision or 'missing'}"
            ),
        )
    return snapshot_from_profile(profile, source_quality=source_quality)


def _fetch_agent_profile(
    agent_proxy_target: str,
    equipment_profile_id: str,
    equipment_revision_id: str | None = None,
) -> dict[str, Any] | None:
    import httpx

    try:
        profile_path = (
            f"equipment/profiles/{quote(equipment_profile_id, safe='')}"
        )
        if equipment_revision_id:
            profile_path += (
                f"/revisions/{quote(equipment_revision_id, safe='')}"
            )
        response = httpx.get(
            f"{agent_proxy_target.rstrip('/')}/{profile_path}",
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("equipment_profile_id"):
            return None
        return payload
    except Exception:  # noqa: BLE001 - agent unreachable -> fail closed
        return None
