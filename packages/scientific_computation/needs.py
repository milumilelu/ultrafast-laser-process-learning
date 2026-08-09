"""Scientific need classification (M2).

Separates four fundamentally different gap kinds that used to be collapsed
into one "knowledge requirement" list:

- RESOURCE_INPUT          : task execution setpoints (actual_power_W) or
                            equipment record fields (beam_radius_um,
                            wavelength_nm). They are resolved by the task
                            definition or Equipment Manager, never by
                            literature.
- SCIENTIFIC_KNOWLEDGE    : knowledge gaps (F_th prior, incubation model,
                            path strategy) - resolved by literature + LLM
                            reading.
- CALIBRATION_OBSERVATION : observation gaps (single-pulse crater,
                            multi-pulse series) - resolved by experiment/data,
                            literature cannot satisfy them.
- TARGET_DATA             : target-scope data gaps (no rows for scope).

The KnowledgeRequirementSet artifact (legacy consumers) is derived from the
SCIENTIFIC_KNOWLEDGE + CALIBRATION_OBSERVATION needs only; RESOURCE_INPUT
needs never become knowledge requirements.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from packages.scientific_computation.contracts import (
    ArtifactRef,
    CapabilityRequirement,
    IdentifiabilityStatus,
    ScientificCapabilityReport,
    StrictModel,
)

SCIENTIFIC_NEED_SCHEMA_VERSION = "scientific-need-set-v1"

TASK_SETPOINT_PARAMETERS = ("actual_power_W",)
EQUIPMENT_INPUT_PARAMETERS = ("beam_radius_um", "wavelength_nm")
RESOURCE_INPUT_PARAMETERS = TASK_SETPOINT_PARAMETERS + EQUIPMENT_INPUT_PARAMETERS
RESOURCE_REQUIREMENT_TYPES = ("PHYSICS_DEPENDENCY", "physics_dependency")
OBSERVATION_REQUIREMENT_TYPES = ("data_quality",)


class ScientificNeedType(StrEnum):
    RESOURCE_INPUT = "RESOURCE_INPUT"
    SCIENTIFIC_KNOWLEDGE = "SCIENTIFIC_KNOWLEDGE"
    CALIBRATION_OBSERVATION = "CALIBRATION_OBSERVATION"
    TARGET_DATA = "TARGET_DATA"


class NeedResolutionTarget(StrEnum):
    TASK_DEFINITION = "TASK_DEFINITION"
    EQUIPMENT_MANAGER = "EQUIPMENT_MANAGER"
    LITERATURE_RETRIEVAL = "LITERATURE_RETRIEVAL"
    EXPERIMENT_OBSERVATION = "EXPERIMENT_OBSERVATION"
    DATASET = "DATASET"


class ScientificNeed(StrictModel):
    need_id: str
    need_type: ScientificNeedType
    target: str
    question: str
    required_for: str
    priority: Literal["high", "medium", "low"]
    trigger_reasons: list[str]
    resolution_target: NeedResolutionTarget
    satisfaction_criteria: list[str] = Field(default_factory=list)
    provenance: list[ArtifactRef] = Field(default_factory=list)


class ScientificNeedSet(StrictModel):
    schema_version: str = SCIENTIFIC_NEED_SCHEMA_VERSION
    need_set_id: str
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    needs: list[ScientificNeed] = Field(default_factory=list)

    def needs_of(self, need_type: ScientificNeedType) -> list[ScientificNeed]:
        return [need for need in self.needs if need.need_type == need_type]


def _need_id(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"NEED-{hashlib.sha256(encoded).hexdigest()[:16]}"


def classify_requirement(req: CapabilityRequirement | dict[str, Any]) -> ScientificNeedType:
    req_type = req.type if hasattr(req, "type") else req.get("type")
    if req_type in RESOURCE_REQUIREMENT_TYPES:
        return ScientificNeedType.RESOURCE_INPUT
    if req_type in OBSERVATION_REQUIREMENT_TYPES:
        return ScientificNeedType.CALIBRATION_OBSERVATION
    return ScientificNeedType.SCIENTIFIC_KNOWLEDGE


def _infer_target(req_type: str, required_for: str) -> str:
    """Map requirement provenance to the canonical need subject."""
    lowered = (required_for or "").lower()
    if "f_th" in lowered:
        return "F_th_eff"
    if "incubation" in lowered:
        return "incubation_law"
    if "planner" in lowered or "path" in lowered:
        return "path_strategy"
    if "peak_fluence" in lowered or "canonical" in lowered:
        return "canonical_physics_inputs"
    if "parameter" in lowered or "calibrat" in lowered:
        return "model_parameters"
    return req_type


def _requirement_as_need(
    req: CapabilityRequirement | dict[str, Any],
    need_type: ScientificNeedType,
) -> ScientificNeed:
    if hasattr(req, "model_dump"):
        payload = req.model_dump(mode="json")
    else:
        payload = dict(req)
    target: str = payload.get("target") or ""
    if not target:
        if need_type == ScientificNeedType.CALIBRATION_OBSERVATION:
            target = "observations"
        else:
            target = _infer_target(
                str(payload.get("type") or ""), str(payload.get("required_for") or "")
            )
    return ScientificNeed(
        need_id=_need_id(
            {"type": need_type, "requirement_id": payload.get("requirement_id"), "question": payload.get("scientific_question")}
        ),
        need_type=need_type,
        target=target,
        question=str(payload.get("scientific_question") or payload.get("question") or ""),
        required_for=str(payload.get("required_for") or "unknown"),
        priority=payload.get("priority") or "medium",
        trigger_reasons=list(payload.get("trigger_reasons") or []),
        resolution_target=_resolution_target(need_type),
        satisfaction_criteria=list(payload.get("satisfaction_criteria") or []),
        provenance=list(payload.get("provenance") or []),
    )


def _resolution_target(need_type: ScientificNeedType) -> NeedResolutionTarget:
    return {
        ScientificNeedType.RESOURCE_INPUT: NeedResolutionTarget.EQUIPMENT_MANAGER,
        ScientificNeedType.SCIENTIFIC_KNOWLEDGE: NeedResolutionTarget.LITERATURE_RETRIEVAL,
        ScientificNeedType.CALIBRATION_OBSERVATION: NeedResolutionTarget.EXPERIMENT_OBSERVATION,
        ScientificNeedType.TARGET_DATA: NeedResolutionTarget.DATASET,
    }[need_type]


def compile_scientific_needs(
    capability: ScientificCapabilityReport,
    *,
    machine_snapshot: dict[str, Any] | None = None,
    data_rows: list[dict[str, Any]] | None = None,
    requirements: list[dict[str, Any]] | None = None,
    input_refs: list[ArtifactRef] | None = None,
) -> ScientificNeedSet:
    """Compile the four-way need set from capability + snapshot + requirements.

    `requirements` (optional) are the stage-level requirement dicts; when
    omitted, capability.recommended_requirements are used.
    """
    refs = list(input_refs or [])
    needs: list[ScientificNeed] = []
    resolved_resource_targets: set[str] = set()

    # 1. RESOURCE_INPUT from task-setpoint or machine-origin gaps (never literature)
    snapshot = dict(machine_snapshot or {})
    snapshot_missing = [str(name) for name in snapshot.get("missing_required") or []]
    capability_missing = {
        item.name for item in capability.missing
    }
    resource_names: set[str] = set()
    resource_names.update(
        name for name in capability_missing if name in RESOURCE_INPUT_PARAMETERS
    )
    resource_names.update(snapshot_missing)
    for name in sorted(resource_names):
        resolved_resource_targets.add(name)
        is_task_setpoint = name in TASK_SETPOINT_PARAMETERS
        needs.append(
            ScientificNeed(
                need_id=_need_id({"type": "RESOURCE_INPUT", "target": name}),
                need_type=ScientificNeedType.RESOURCE_INPUT,
                target=name,
                question=(
                    "本次任务在材料表面处的入射平均功率设定值是多少？"
                    if is_task_setpoint
                    else f"目标设备的 {name} 是多少？"
                ),
                required_for=(
                    "ExecutionContext" if is_task_setpoint else "MachineProfileSnapshot"
                ),
                priority="high",
                trigger_reasons=[
                    (
                        "task workpiece-surface incident power setpoint missing"
                        if is_task_setpoint
                        else f"{name} missing in machine profile"
                    )
                ],
                resolution_target=(
                    NeedResolutionTarget.TASK_DEFINITION
                    if is_task_setpoint
                    else NeedResolutionTarget.EQUIPMENT_MANAGER
                ),
                satisfaction_criteria=[
                    (
                        "task setpoint verified against measured workpiece-surface equipment bounds"
                        if is_task_setpoint
                        else "verified equipment profile field"
                    )
                ],
                provenance=refs,
            )
        )

    # 2. stage requirements -> classify (resource types already emitted above)
    req_items: list[dict[str, Any]] = []
    if requirements is not None:
        req_items = list(requirements)
    else:
        req_items = [item.model_dump(mode="json") for item in capability.recommended_requirements]
    for req in req_items:
        need_type = classify_requirement(req)
        if need_type == ScientificNeedType.RESOURCE_INPUT:
            continue
        needs.append(_requirement_as_need(req, need_type))

    # 3. CALIBRATION_OBSERVATION from identifiability abstentions
    observation_targets = {need.target for need in needs}
    for item in capability.identifiability:
        if item.status in (
            IdentifiabilityStatus.NOT_IDENTIFIABLE,
            IdentifiabilityStatus.WEAKLY_IDENTIFIABLE,
        ) and item.required_observations:
            if item.parameter in observation_targets:
                continue
            needs.append(
                ScientificNeed(
                    need_id=_need_id({"type": "CALIBRATION_OBSERVATION", "target": item.parameter}),
                    need_type=ScientificNeedType.CALIBRATION_OBSERVATION,
                    target=item.parameter,
                    question=f"{item.parameter} 当前不可辨识，需要哪些观测？",
                    required_for="ParameterIdentificationEngine",
                    priority="high",
                    trigger_reasons=list(item.reason_codes),
                    resolution_target=NeedResolutionTarget.EXPERIMENT_OBSERVATION,
                    satisfaction_criteria=list(item.required_observations),
                    provenance=refs,
                )
            )

    # 4. TARGET_DATA when the scope has no rows
    if not data_rows:
        needs.append(
            ScientificNeed(
                need_id=_need_id({"type": "TARGET_DATA"}),
                need_type=ScientificNeedType.TARGET_DATA,
                target="target_dataset",
                question="当前任务范围内没有可用实验数据，需要补充数据集？",
                required_for="ParameterIdentificationEngine",
                priority="high",
                trigger_reasons=["no rows for scope"],
                resolution_target=NeedResolutionTarget.DATASET,
                satisfaction_criteria=["dataset rows matching task scope"],
                provenance=refs,
            )
        )

    return ScientificNeedSet(
        need_set_id=_need_id({"version": SCIENTIFIC_NEED_SCHEMA_VERSION, "needs": [n.model_dump(mode="json") for n in needs]}),
        input_refs=refs,
        needs=needs,
    )
