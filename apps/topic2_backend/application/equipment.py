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

from packages.process_contracts.equipment import (
    MachineProfileSnapshot,
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
    run_mode: str,
    task_spec: dict[str, Any],
    agent_proxy_target: str | None,
    fixture_profiles: dict[str, dict[str, Any]] | None,
) -> MachineProfileSnapshot:
    """Resolve the canonical MachineProfileSnapshot for a run.

    Resolution order:
    1. SANDBOX + task_spec.machine_profile  -> TASK_OVERRIDE (provisional)
    2. fixture store                        -> DEMO_FIXTURE
    3. agent archive over HTTP              -> RESEARCH_AGENT
    4. otherwise                            -> BLOCKED snapshot
    """
    mode = effective_execution_mode(run_mode, task_spec)
    if mode == "SANDBOX" and task_spec.get("machine_profile"):
        return snapshot_from_task_override(
            dict(task_spec["machine_profile"]),
            equipment_profile_id=equipment_profile_id,
        )

    fixture = (fixture_profiles or {}).get(equipment_profile_id)
    if fixture is not None:
        return snapshot_from_profile(
            fixture, source_quality="DEMO_FIXTURE"
        )

    if agent_proxy_target:
        profile = _fetch_agent_profile(agent_proxy_target, equipment_profile_id)
        if profile is not None:
            return snapshot_from_profile(
                profile, source_quality="RESEARCH_AGENT"
            )

    return build_blocked_snapshot(
        equipment_profile_id,
        "equipment profile 不可解析（无 fixture，且 agent 档案不可达）",
    )


def _fetch_agent_profile(
    agent_proxy_target: str, equipment_profile_id: str
) -> dict[str, Any] | None:
    import httpx

    try:
        response = httpx.get(
            f"{agent_proxy_target.rstrip('/')}/equipment/profiles/{equipment_profile_id}",
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("equipment_profile_id"):
            return None
        return payload
    except Exception:  # noqa: BLE001 - agent unreachable -> fail closed
        return None
