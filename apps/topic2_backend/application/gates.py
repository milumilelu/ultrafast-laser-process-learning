"""Scientific execution gates (M4) - the four canonical run gates.

Gate A - Resource Ready   : canonical MachineProfileSnapshot resolved.
Gate B - Knowledge Ready  : active-mechanism required parameters have a
                            prior, a measurement, or fittable observations.
Gate C - Physical Model   : CalibrationResult produced real estimates.
Gate D - Planning Ready   : machine bounds + LocalRemovalModel + persisted
                            MorphologySimulationResult available.

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
    "simulate_morphology": "SIMULATION",
    "plan_process": "PLANNING",
    "evaluate_observation": "OBSERVATION",
}

# ordered phases the workbench displays (backend-computed statuses)
PHASE_ORDER = (
    "CAPABILITY",
    "KNOWLEDGE",
    "CALIBRATION",
    "MODEL",
    "SIMULATION",
    "PLANNING",
    "OBSERVATION",
)

# phase -> guarding gate (BLOCKED gate blocks its phase)
PHASE_GATE: dict[str, str] = {
    "CAPABILITY": "A",
    "KNOWLEDGE": "B",
    "CALIBRATION": "B",
    "MODEL": "C",
    "SIMULATION": "C",
    "PLANNING": "D",
    "OBSERVATION": "D",
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
        stage_results: dict[str, Any] | None = None,
    ):
        super().__init__(f"Gate {gate} BLOCKED: {'; '.join(reasons)}")
        self.gate = gate
        self.reasons = reasons
        self.next_actions = next_actions
        self.phase = phase
        self.run_control_state = run_control_state
        self.stage_results = stage_results or {}


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
    machine_snapshot: dict[str, Any] | None,
    data_state: dict[str, Any] | None,
    target_geometry: dict[str, Any] | None,
    execution_context: dict[str, Any] | None = None,
    *,
    execution_mode: str,
) -> GateResult:
    """Gate A (阶段二 T1): MachineProfileSnapshot + usable DataState +
    valid TargetGeometry — all three required (fail closed).

    DataState is a typed resource state, never a bare boolean:
      {status: READY|PARTIAL|INVALID, reason, n_samples, n_unique_designs}
    TargetGeometry is mandatory in RESEARCH / DEMO_FIXTURE; SANDBOX may use
    an explicit synthetic target (provisional).
    """
    if execution_mode == "SANDBOX":
        provisional = (
            ["SANDBOX: computational defaults allowed (provisional)"]
            if target_geometry is None
            else ["SANDBOX: gates bypassed (provisional)"]
        )
        return GateResult("A", "READY", provisional)

    reasons: list[str] = []
    actions: list[dict[str, Any]] = []

    if not machine_snapshot:
        reasons.append("MachineProfileSnapshot 未生成")
        actions.append({"type": "COMPLETE_EQUIPMENT_PROFILE", "missing": ["*"]})
    else:
        snapshot_status = str(machine_snapshot.get("resource_status") or "BLOCKED")
        missing = [str(name) for name in machine_snapshot.get("missing_required") or []]
        if snapshot_status != "READY":
            reasons.append(f"设备档案缺失必需字段: {', '.join(missing) or snapshot_status}")
            actions.append(
                {
                    "type": "COMPLETE_EQUIPMENT_PROFILE",
                    "missing": missing,
                    "source_quality": machine_snapshot.get("source_quality"),
                }
            )

    context_status = str((execution_context or {}).get("status") or "BLOCKED")
    if context_status != "READY":
        context_reasons = [
            str(reason) for reason in (execution_context or {}).get("reasons") or []
        ]
        reasons.append(
            "本次任务的材料表面入射平均功率不可执行"
            + (f": {'; '.join(context_reasons)}" if context_reasons else "")
        )
        actions.append(
            {
                "type": "SPECIFY_PROCESS_SETPOINT",
                "parameter": "laser_power_W",
                "location": "WORKPIECE_SURFACE_INCIDENT",
                "bounds": (execution_context or {}).get("bounds"),
            }
        )

    data_status = str((data_state or {}).get("status") or "INVALID")
    if data_status != "READY":
        reasons.append(
            f"数据集不可用: {data_status}"
            + (f"（{(data_state or {}).get('reason')}）" if (data_state or {}).get("reason") else "")
        )
        actions.append({"type": "IMPORT_DATASET"})

    geometry_issues = _geometry_issues(target_geometry)
    if geometry_issues:
        reasons.append(f"TargetGeometry 缺失或无效: {'; '.join(geometry_issues)}")
        actions.append({"type": "SPECIFY_TARGET_GEOMETRY", "missing": geometry_issues})

    if reasons:
        return GateResult("A", "BLOCKED", reasons, actions)
    return GateResult("A", "READY")


def _geometry_issues(target_geometry: dict[str, Any] | None) -> list[str]:
    """Per-geometry-type conditional requirements for TargetGeometry."""
    if not target_geometry:
        return ["geometry_type", "width_um", "height_um", "target_depth_um"]
    issues: list[str] = []
    geometry_type = str(target_geometry.get("geometry_type") or "")
    if not geometry_type:
        issues.append("geometry_type")
    for field_name in ("width_um", "height_um", "target_depth_um"):
        value = target_geometry.get(field_name)
        if value is None or float(value) <= 0:
            issues.append(field_name)
    return issues


def knowledge_gate(
    *,
    parameter_priors: set[str],
    mechanism_model_priors: set[str],
    observation_capabilities: set[str],
    mechanism_required: list[dict[str, Any]],
    machine_fields: set[str] | None = None,
    knowledge_state: dict[str, Any] | None = None,
    execution_mode: str,
) -> GateResult:
    """Gate B (阶段二 T5): active-mechanism model structure AND parameters.

    Consumes the PriorObjectSet (never re-interprets EvidenceIRSet):
    - parameter_priors        : parameters covered by ParameterPrior.
    - mechanism_model_priors  : model families covered by MechanismModelPrior.
    - observation_capabilities: parameters identifiable from independent
                                calibration observations (macro dataset rows
                                do NOT count).
    - machine_fields          : resource parameters resolved by Gate A
                                (e.g. beam_radius_um from the equipment
                                snapshot).
    - mechanism_required      : registry specs for the active mechanisms.

    Model structure and model parameters are checked separately:
    incubation requires a MechanismModelPrior (structure) AND incubation_S
    (parameter).  A dataset with pulse_count >= 2 never substitutes for the
    missing model structure.
    """
    if execution_mode == "SANDBOX":
        return GateResult("B", "READY", ["SANDBOX: gates bypassed (provisional)"])
    machine_fields = machine_fields or set()
    partial: list[str] = []
    structure_blocked: list[str] = []
    parameter_blocked: list[str] = []
    state_blocked: list[str] = []

    if knowledge_state:
        satisfaction_by_id = {
            str(item.get("requirement_id")): str(item.get("status") or "UNSATISFIED")
            for item in knowledge_state.get("satisfactions") or []
            if isinstance(item, dict)
        }
        for requirement in knowledge_state.get("requirements") or []:
            if not isinstance(requirement, dict) or requirement.get("priority") != "high":
                continue
            requirement_id = str(requirement.get("requirement_id") or "")
            satisfaction = satisfaction_by_id.get(requirement_id, "UNSATISFIED")
            if satisfaction != "SATISFIED":
                state_blocked.append(
                    f"{requirement_id}: KnowledgeState={satisfaction}"
                )

    # model structure: every structure-requiring active mechanism needs a
    # MechanismModelPrior (the mechanism registry decides which models
    # require structure via their parameter fallback semantics)
    for spec in mechanism_required:
        source_model = str(spec.get("source_model") or "")
        if source_model in _STRUCTURE_REQUIRED_MODELS:
            structure_ok = any(
                model_family in _STRUCTURE_ALIASES.get(source_model, {source_model})
                for model_family in mechanism_model_priors
            )
            if not structure_ok:
                structure_blocked.append(source_model)

    # parameters: prior OR identifiable independent observation OR resource.
    # Optional mechanisms (DEFOCUS/THERMAL) without support stay INACTIVE —
    # that is the designed C-方案 behavior (阶段二), expressed by the model's
    # inactive_mechanisms, not a PARTIAL gate warning.
    for spec in mechanism_required:
        name = str(spec.get("parameter") or "")
        source_model = str(spec.get("source_model") or "")
        if name in machine_fields:
            continue
        if source_model in _OPTIONAL_MECHANISMS:
            continue
        covered = (
            name in parameter_priors
            or name in observation_capabilities
        )
        if not covered:
            parameter_blocked.append(name)
    blocked = [
        *state_blocked,
        *(
            f"{model}: 模型结构未解决（需要 MechanismModelPrior）"
            for model in structure_blocked
        ),
        *(
            f"{name}: 无 ParameterPrior 且无独立观测"
            for name in sorted(set(parameter_blocked))
        ),
    ]
    if blocked:
        actions: list[dict[str, Any]] = []
        if state_blocked:
            actions.append(
                {
                    "type": "RESOLVE_KNOWLEDGE_REQUIREMENTS",
                    "requirement_ids": [
                        item.split(":", 1)[0] for item in state_blocked
                    ],
                }
            )
        if structure_blocked:
            actions.append(
                {
                    "type": "RESOLVE_LITERATURE",
                    "mechanism_models": sorted(set(structure_blocked)),
                }
            )
        if parameter_blocked:
            actions.append(
                {
                    "type": "RESOLVE_LITERATURE",
                    "parameters": sorted(set(parameter_blocked)),
                }
            )
            actions.append(
                {
                    "type": "ADD_CALIBRATION_OBSERVATION",
                    "observation_types": sorted(
                        {
                            "ABSOLUTE_FLUENCE"
                            if name in ("F_th_eff", "delta_eff")
                            else "MULTI_PULSE_CRATER"
                            for name in set(parameter_blocked)
                        }
                    ),
                }
            )
        return GateResult("B", "BLOCKED", blocked, actions)
    if partial:
        return GateResult(
            "B",
            "PARTIAL",
            partial,
            [{"type": "ADD_LITERATURE_PRIORS", "parameters": partial}],
        )
    return GateResult("B", "READY")


# mechanism models whose structure must be resolved by a MechanismModelPrior
_STRUCTURE_REQUIRED_MODELS = {"POWER_LAW_INCUBATION", "SATURATION_INCUBATION"}

# model family aliases per registry model id (registry-compatible families)
_STRUCTURE_ALIASES: dict[str, set[str]] = {
    "POWER_LAW_INCUBATION": {"POWER_LAW_INCUBATION"},
    "SATURATION_INCUBATION": {"SATURATION_INCUBATION"},
}

# mechanisms that may stay INACTIVE when unsupported (C 方案, 阶段二)
_OPTIONAL_MECHANISMS = {"DEFOCUS_RECURSION", "THERMAL_MEMORY_PROXY"}


CRITICAL_BOUND_PARAMETERS = ("F_th_eff", "incubation_S", "delta_eff", "beam_radius_um")

_UNRESOLVED_SOURCES = {"COMPUTATIONAL_DEFAULT", "UNRESOLVED"}


def physical_model_gate(
    calibration_result: dict[str, Any] | None,
    local_removal_model: dict[str, Any] | None,
    *,
    execution_mode: str,
) -> GateResult:
    """Gate C (阶段二 T3/T2): LocalRemovalModel exists AND critical parameters
    are bound from real sources — never COMPUTATIONAL_DEFAULT/UNRESOLVED.

    Reads the structured `parameter_bindings` field; assumption strings are
    never parsed.
    """
    if execution_mode == "SANDBOX":
        return GateResult("C", "READY", ["SANDBOX: gates bypassed (provisional)"])
    reasons: list[str] = []
    actions: list[dict[str, Any]] = []
    parameters = list((calibration_result or {}).get("parameters") or [])
    if not parameters:
        reasons.append("CalibrationResult 未产生任何参数估计")
        actions.append({"type": "REVIEW_CALIBRATION_INPUTS"})
    if not local_removal_model:
        reasons.append("LocalRemovalModel 未建立")
        actions.append(
            {"type": "RESUME_RUN", "target_phase": "MODEL", "resume_stage": "establish_process_model"}
        )
    else:
        bindings = {
            str(binding.get("parameter")): str(binding.get("source_type") or "UNRESOLVED")
            for binding in (local_removal_model.get("parameter_bindings") or [])
            if isinstance(binding, dict)
        }
        unexplained = [
            name
            for name in CRITICAL_BOUND_PARAMETERS
            if bindings.get(name) in _UNRESOLVED_SOURCES
        ]
        if unexplained:
            reasons.append(
                f"关键参数来源为 unexplained default: {', '.join(sorted(unexplained))}"
            )
            actions.append({"type": "REVIEW_MODEL_PARAMETER_BINDINGS"})
    if reasons:
        return GateResult("C", "BLOCKED", reasons, actions)
    return GateResult("C", "READY")


def planning_gate(
    *,
    model_available: bool,
    simulation_available: bool,
    machine_bounds: dict[str, Any],
    candidate_plan: dict[str, Any] | None,
    execution_mode: str,
) -> GateResult:
    """Gate D: simulation + constraint-compliant candidate before plan issuance."""
    if execution_mode == "SANDBOX":
        return GateResult("D", "READY", ["SANDBOX: gates bypassed (provisional)"])
    reasons: list[str] = []
    actions: list[dict[str, Any]] = []
    if not model_available:
        reasons.append("LocalRemovalModel 未建立")
        actions.append(
            {"type": "RESUME_RUN", "target_phase": "MODEL", "resume_stage": "establish_process_model"}
        )
    if not simulation_available:
        reasons.append("MorphologySimulationResult 未生成")
        actions.append(
            {
                "type": "RESUME_RUN",
                "target_phase": "SIMULATION",
                "resume_stage": "simulate_morphology",
            }
        )
    if not machine_bounds:
        reasons.append("机器边界（MachineBounds）不可用")
        actions.append({"type": "COMPLETE_EQUIPMENT_PROFILE", "missing": ["motion/laser ranges"]})
    if not candidate_plan:
        reasons.append("ToolpathCandidateSet 不可用")
        actions.append(
            {
                "type": "RESUME_RUN",
                "target_phase": "SIMULATION",
                "resume_stage": "simulate_morphology",
            }
        )
    elif machine_bounds:
        laser = candidate_plan.get("laser_parameters") or {}
        path = candidate_plan.get("path_parameters") or {}
        selected = {
            "pulse_width_ps": laser.get("pulse_width_ps"),
            "frequency_kHz": laser.get("frequency_kHz"),
            "scan_speed_mm_s": laser.get("scan_speed_mm_s"),
            "hatch_spacing_um": path.get("hatch_um"),
            "passes": path.get("passes"),
        }
        violations: list[str] = []
        for name, value in selected.items():
            bound = machine_bounds.get(name)
            if not isinstance(bound, dict):
                continue
            if value is None:
                violations.append(f"{name}: candidate value missing")
                continue
            lower = bound.get("lower")
            upper = bound.get("upper")
            numeric = float(value)
            if (lower is not None and numeric < float(lower)) or (
                upper is not None and numeric > float(upper)
            ):
                violations.append(
                    f"{name}={numeric} outside [{lower}, {upper}]"
                )
        if violations:
            reasons.extend(violations)
            actions.append({"type": "REGENERATE_TOOLPATH_CANDIDATES"})
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
    """Canonical RunControlState (frontend renders, never derives).

    `phases` gives every phase a backend-computed status - the frontend
    performs zero gate-to-phase interpretation (阶段三 T1).
    """
    # A resumed run may evaluate the same gate again.  The newest result is
    # authoritative; stale BLOCKED results must not poison the current state.
    gate_by_name = {result.name: result for result in gates}
    gate_dicts = {name: result.to_dict() for name, result in gate_by_name.items()}
    blocking = [
        reason
        for result in gate_by_name.values()
        for reason in result.reasons
        if result.status == "BLOCKED"
    ]
    next_actions: list[dict[str, Any]] = []
    for result in gate_by_name.values():
        for action in result.next_actions:
            if action not in next_actions:
                next_actions.append(action)
    status = "BLOCKED" if blocking else (
        "PARTIAL"
        if any(result.status == "PARTIAL" for result in gates)
        else phase_status
    )

    completed = set(completed_stages)
    phases: dict[str, dict[str, Any]] = {}
    for phase in PHASE_ORDER:
        phase_stages = [
            stage for stage, owner in STAGE_PHASES.items() if owner == phase
        ]
        stage_done = bool(phase_stages) and all(
            stage in completed for stage in phase_stages
        )
        gate = gate_by_name.get(PHASE_GATE[phase])
        if gate is not None and gate.status == "BLOCKED":
            phase_status_value = "BLOCKED"
            reasons = list(gate.reasons)
        elif stage_done:
            phase_status_value = "COMPLETED"
            reasons = []
        elif gate is not None and gate.status == "PARTIAL":
            phase_status_value = "PARTIAL"
            reasons = list(gate.reasons)
        elif gate is not None and gate.status == "READY":
            phase_status_value = "READY"
            reasons = []
        else:
            phase_status_value = "NOT_RUN"
            reasons = []
        phases[phase] = {
            "status": phase_status_value,
            "blocking_reasons": reasons,
        }

    if not next_actions and phase_status not in {"COMPLETED", "BLOCKED"}:
        remaining = [
            stage for stage in STAGE_PHASES if stage not in completed
        ]
        if remaining:
            next_actions.append(
                {
                    "type": "CONTINUE_RUN",
                    "resume_stage": remaining[0],
                    "target_phase": STAGE_PHASES[remaining[0]],
                }
            )

    return {
        "schema_version": RUN_CONTROL_SCHEMA_VERSION,
        "execution_mode": execution_mode,
        "current_phase": current_phase,
        "phase_status": status,
        "phases": phases,
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
