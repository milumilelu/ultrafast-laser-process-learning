"""Scientific execution gates (M4) - the four canonical run gates.

Gate A - Resource Ready   : canonical MachineProfileSnapshot resolved.
Gate B - Knowledge Ready  : active-mechanism required parameters have a
                            prior, a measurement, or fittable observations.
Gate C - Physical Model   : CalibrationResult produced real estimates.
Gate D - Planning Ready   : machine bounds + LocalRemovalModel available.

Research mode fails closed (BLOCKED).  DEMO_FIXTURE is allowed to be PARTIAL
with explicit tracking.  SANDBOX bypasses gates (computational defaults
allowed, every artifact marked provisional).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from packages.scientific_computation.mechanism_registry import MechanismRegistry

RUN_CONTROL_SCHEMA_VERSION = "run-control-state-v1"

# stage -> phase (frontend no longer derives workflow state)
STAGE_PHASES: dict[str, str] = {
    "prepare_task": "CAPABILITY",
    "assess_capability": "CAPABILITY",
    "assess_data": "CAPABILITY",
    "baseline_learning": "CAPABILITY",
    "analyze_knowledge_requirements": "KNOWLEDGE",
    "prepare_knowledge": "KNOWLEDGE",
    "satisfy_requirements": "KNOWLEDGE",
    "calibrate_physics": "CALIBRATION",
    "establish_process_model": "MODEL",
    "plan_process": "PLANNING",
    "evaluate_observation": "OBSERVATION",
}

GATE_NAMES = ("A", "B", "C", "D")


class StageBlockedError(Exception):
    """A canonical gate rejected the run (fail closed)."""

    def __init__(
        self,
        gate: str,
        *,
        reasons: list[str],
        next_actions: list[dict[str, Any]],
        phase: str,
        run_control_state: dict[str, Any] | None = None,
    ):
        super().__init__(f"Gate {gate} BLOCKED: {'; '.join(reasons)}")
        self.gate = gate
        self.reasons = reasons
        self.next_actions = next_actions
        self.phase = phase
        self.run_control_state = run_control_state


@dataclass
class GateResult:
    name: str
    status: str  # READY | PARTIAL | BLOCKED
    reasons: list[str] = field(default_factory=list)
    next_actions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.name,
            "status": self.status,
            "reasons": list(self.reasons),
            "next_actions": list(self.next_actions),
        }


def resource_gate(
    snapshot: dict[str, Any] | None,
    *,
    execution_mode: str,
) -> GateResult:
    """Gate A: canonical MachineProfileSnapshot resolved (fail closed)."""
    if execution_mode == "SANDBOX":
        return GateResult("A", "READY", ["SANDBOX: computational defaults allowed (provisional)"])
    if not snapshot:
        return GateResult(
            "A",
            "BLOCKED",
            ["MachineProfileSnapshot 未生成"],
            [{"type": "COMPLETE_EQUIPMENT_PROFILE", "missing": ["*"]}],
        )
    status = str(snapshot.get("resource_status") or "BLOCKED")
    missing = [str(name) for name in snapshot.get("missing_required") or []]
    if status == "READY":
        return GateResult("A", "READY")
    if missing:
        return GateResult(
            "A",
            "BLOCKED",
            [f"设备档案缺失必需字段: {', '.join(missing)}"],
            [
                {
                    "type": "COMPLETE_EQUIPMENT_PROFILE",
                    "missing": missing,
                    "source_quality": snapshot.get("source_quality"),
                }
            ],
        )
    return GateResult(
        "A", "BLOCKED", [f"设备档案不可用（{status}）"],
        [{"type": "COMPLETE_EQUIPMENT_PROFILE", "missing": ["*"]}],
    )


def knowledge_gate(
    *,
    mechanism_required: list[dict[str, Any]],
    machine_fields: set[str],
    prior_parameters: set[str],
    has_observations: bool,
    execution_mode: str,
) -> GateResult:
    """Gate B: active-mechanism parameters are prior/measured/fittable."""
    if execution_mode == "SANDBOX":
        return GateResult("B", "READY", ["SANDBOX: gates bypassed (provisional)"])
    blocked: list[str] = []
    partial: list[str] = []
    for spec in mechanism_required:
        name = str(spec.get("parameter") or "")
        covered = (
            name in machine_fields
            or name in prior_parameters
            or (bool(spec.get("calibration_supported")) and has_observations)
        )
        if covered:
            continue
        if spec.get("calibration_supported"):
            blocked.append(f"{name}: 无先验且无可用观测")
        else:
            partial.append(f"{name}: 无文献先验（显式计算默认并标注）")
    if blocked:
        return GateResult(
            "B",
            "BLOCKED",
            blocked,
            [
                {
                    "type": "RESOLVE_LITERATURE_OR_ADD_OBSERVATIONS",
                    "parameters": blocked,
                }
            ],
        )
    if partial:
        return GateResult(
            "B",
            "PARTIAL",
            partial,
            [{"type": "ADD_LITERATURE_PRIORS", "parameters": partial}],
        )
    return GateResult("B", "READY")


def physical_model_gate(
    calibration_result: dict[str, Any] | None,
    *,
    execution_mode: str,
) -> GateResult:
    """Gate C: calibration produced real parameter estimates (not empty)."""
    if execution_mode == "SANDBOX":
        return GateResult("C", "READY", ["SANDBOX: gates bypassed (provisional)"])
    parameters = list((calibration_result or {}).get("parameters") or [])
    if not parameters:
        return GateResult(
            "C",
            "BLOCKED",
            ["CalibrationResult 未产生任何参数估计"],
            [{"type": "REVIEW_CALIBRATION_INPUTS"}],
        )
    return GateResult("C", "READY")


def planning_gate(
    *,
    model_available: bool,
    machine_bounds: dict[str, Any],
    execution_mode: str,
) -> GateResult:
    """Gate D: LocalRemovalModel + machine bounds before path planning."""
    if execution_mode == "SANDBOX":
        return GateResult("D", "READY", ["SANDBOX: gates bypassed (provisional)"])
    reasons: list[str] = []
    actions: list[dict[str, Any]] = []
    if not model_available:
        reasons.append("LocalRemovalModel 未建立")
        actions.append({"type": "ESTABLISH_PROCESS_MODEL"})
    if not machine_bounds:
        reasons.append("机器边界（MachineBounds）不可用")
        actions.append({"type": "COMPLETE_EQUIPMENT_PROFILE", "missing": ["motion/laser ranges"]})
    if reasons:
        return GateResult("D", "BLOCKED", reasons, actions)
    return GateResult("D", "READY")


def run_control_state(
    *,
    gates: list[GateResult],
    execution_mode: str,
    current_phase: str,
    phase_status: str,
    completed_stages: list[str],
) -> dict[str, Any]:
    """Canonical RunControlState artifact (frontend renders, never derives)."""
    gate_dicts = {result.name: result.to_dict() for result in gates}
    blocking = [
        reason
        for result in gates
        for reason in result.reasons
        if result.status == "BLOCKED"
    ]
    next_actions: list[dict[str, Any]] = []
    for result in gates:
        for action in result.next_actions:
            if action not in next_actions:
                next_actions.append(action)
    status = "BLOCKED" if blocking else (
        "PARTIAL"
        if any(result.status == "PARTIAL" for result in gates)
        else phase_status
    )
    return {
        "schema_version": RUN_CONTROL_SCHEMA_VERSION,
        "execution_mode": execution_mode,
        "current_phase": current_phase,
        "phase_status": status,
        "gates": gate_dicts,
        "blocking_reasons": blocking,
        "next_actions": next_actions,
        "completed_stages": list(completed_stages),
        "provisional": execution_mode == "SANDBOX",
    }


def mechanism_prior_parameters(prior_set: dict[str, Any] | None) -> set[str]:
    """Parameters covered by ParameterPrior items in a PriorObjectSet payload."""
    priors = list((prior_set or {}).get("priors") or [])
    return {
        str(item.get("parameter"))
        for item in priors
        if item.get("prior_type") == "ParameterPrior"
        and item.get("parameter") is not None
    }


def active_mechanism_required(mechanism_parameter_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Registry-driven required parameter specs (union, stable order)."""
    return list(mechanism_parameter_requirements or [])


def required_parameters_for_default_models() -> list[dict[str, Any]]:
    return MechanismRegistry.required_parameters(
        list(MechanismRegistry.DEFAULT_ACTIVE_MODELS)
    )
