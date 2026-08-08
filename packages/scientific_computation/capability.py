"""Deterministic scientific capability preflight.

The analyzer is intentionally independent from literature retrieval: it derives
knowledge requirements only from downstream computation dependencies and the
observations/machine facts currently available.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from packages.scientific_computation.contracts import (
    ArtifactRef,
    AvailabilityStatus,
    CapabilityInput,
    CapabilityRequirement,
    IdentifiabilityStatus,
    InteractionTopology,
    ParameterIdentifiability,
    ProvenanceRecord,
    ScientificCapabilityReport,
    ScientificStatus,
    SimulationFidelity,
)

_DATA_INPUTS: tuple[tuple[str, str], ...] = (
    ("pulse_width_ps", "ps"),
    ("frequency_kHz", "kHz"),
    ("scan_speed_mm_s", "mm/s"),
    ("hatch_spacing_um", "um"),
    ("passes", "count"),
)
_MACHINE_INPUTS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("actual_power_W", ("actual_power_W", "laser_power_W", "average_power_W"), "W"),
    ("beam_radius_um", ("beam_radius_um", "spot_radius_um"), "um"),
    ("wavelength_nm", ("wavelength_nm",), "nm"),
)


def _stable_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:16]}"


def infer_interaction_topology(geometry_type: str) -> InteractionTopology:
    value = geometry_type.strip().lower().replace("-", "_").replace(" ", "_")
    if any(token in value for token in ("through_hole", "throughhole")):
        return InteractionTopology.THROUGH_HOLE
    if any(token in value for token in ("deep", "high_aspect", "confined")):
        return InteractionTopology.DEEP_CONFINED
    if any(token in value for token in ("percussion", "drill")):
        return InteractionTopology.PERCUSSION_DRILLING
    if any(token in value for token in ("groove", "pocket", "rectangle", "circle", "surface")):
        return InteractionTopology.SHALLOW_2_5D
    if any(token in value for token in ("line", "open")):
        return InteractionTopology.OPEN_SURFACE
    return InteractionTopology.UNKNOWN


class ScientificCapabilityAnalyzer:
    """Map task/data/machine state to explicit computation readiness."""

    def analyze(
        self,
        *,
        task: dict[str, Any],
        data_rows: list[dict[str, Any]],
        machine_profile: dict[str, Any] | None = None,
        knowledge_state: dict[str, Any] | None = None,
        input_refs: list[ArtifactRef] | None = None,
    ) -> ScientificCapabilityReport:
        machine = dict(machine_profile or {})
        refs = list(input_refs or [])
        task_ref = next((ref for ref in refs if ref.type == "TaskState"), None) or ArtifactRef(
            type="TaskState", id=str(task.get("task_context_id") or "task")
        )
        available: list[CapabilityInput] = []
        missing: list[CapabilityInput] = []

        for name, unit in _DATA_INPUTS:
            values = [row.get(name) for row in data_rows if row.get(name) is not None]
            item = CapabilityInput(
                name=name,
                value=values[0] if values else None,
                unit=unit,
                status=(AvailabilityStatus.AVAILABLE if values else AvailabilityStatus.MISSING),
                source_refs=[ArtifactRef(type="DataState", id="current-data")],
            )
            (available if values else missing).append(item)

        process_parameters = dict(task.get("process_parameters") or {})
        device_properties = dict(task.get("device_properties") or {})
        combined_machine = {**machine, **device_properties, **process_parameters}
        for canonical, aliases, unit in _MACHINE_INPUTS:
            found_name = next(
                (alias for alias in aliases if combined_machine.get(alias) is not None), None
            )
            verified = (
                bool(
                    combined_machine.get(f"{found_name}_verified", False)
                    or combined_machine.get("verified", False)
                )
                if found_name
                else False
            )
            if found_name is None:
                item = CapabilityInput(
                    name=canonical,
                    value=None,
                    unit=unit,
                    status=AvailabilityStatus.MISSING,
                    source_refs=[],
                )
                missing.append(item)
            else:
                item = CapabilityInput(
                    name=canonical,
                    value=combined_machine[found_name],
                    unit=unit,
                    status=(
                        AvailabilityStatus.AVAILABLE if verified else AvailabilityStatus.UNVERIFIED
                    ),
                    source_refs=[
                        ArtifactRef(
                            type="MachineProfile",
                            id=str(
                                task.get("equipment_id")
                                or task.get("equipment_profile_id")
                                or "machine"
                            ),
                        )
                    ],
                )
                available.append(item)

        has_rows = bool(data_rows)
        has_absolute_optics = all(
            any(
                item.name == name and item.status == AvailabilityStatus.AVAILABLE
                for item in available
            )
            for name in ("actual_power_W", "beam_radius_um")
        )
        has_local_morphology = any(
            row.get("single_pulse_depth_um") is not None or row.get("crater_profile_ref")
            for row in data_rows
        )
        pulse_counts = {row.get("passes") for row in data_rows if row.get("passes") is not None}
        has_multi_pulse_variation = len(pulse_counts) >= 2

        identifiability = [
            ParameterIdentifiability(
                parameter="F_th_eff",
                status=(
                    IdentifiabilityStatus.IDENTIFIABLE
                    if has_absolute_optics and has_local_morphology
                    else IdentifiabilityStatus.WEAKLY_IDENTIFIABLE
                    if has_rows
                    else IdentifiabilityStatus.NOT_IDENTIFIABLE
                ),
                reason_codes=(
                    ["absolute_fluence_and_local_morphology_available"]
                    if has_absolute_optics and has_local_morphology
                    else ["terminal_macro_depth_without_absolute_fluence"]
                    if has_rows
                    else ["no_target_observations"]
                ),
                required_observations=["absolute fluence", "single/multi-pulse crater morphology"],
            ),
            ParameterIdentifiability(
                parameter="incubation_S",
                status=(
                    IdentifiabilityStatus.WEAKLY_IDENTIFIABLE
                    if has_rows and has_multi_pulse_variation
                    else IdentifiabilityStatus.NOT_IDENTIFIABLE
                ),
                reason_codes=(
                    ["multi_pass_terminal_depth_only"]
                    if has_rows and has_multi_pulse_variation
                    else ["pulse_count_variation_missing"]
                ),
                required_observations=["multi-pulse crater series"],
            ),
            ParameterIdentifiability(
                parameter="delta_eff",
                status=(
                    IdentifiabilityStatus.WEAKLY_IDENTIFIABLE
                    if has_rows
                    else IdentifiabilityStatus.NOT_IDENTIFIABLE
                ),
                reason_codes=["macro_depth_supports_effective_scale_only"]
                if has_rows
                else ["no_depth_data"],
                required_observations=["depth observations"],
            ),
            ParameterIdentifiability(
                parameter="thermal_diffusivity",
                status=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                reason_codes=["terminal_depth_only_has_no_time_resolved_thermal_information"],
                required_observations=["time-resolved thermal measurement"],
            ),
            ParameterIdentifiability(
                parameter="thermal_memory_eff",
                status=(
                    IdentifiabilityStatus.WEAKLY_IDENTIFIABLE
                    if has_rows and has_multi_pulse_variation
                    else IdentifiabilityStatus.NOT_IDENTIFIABLE
                ),
                reason_codes=["effective_proxy_not_physical_diffusivity"],
                required_observations=["frequency/pass variation with morphology"],
            ),
        ]

        requirements: list[CapabilityRequirement] = []

        def add_requirement(
            type_: str,
            question: str,
            required_for: str,
            priority: Literal["high", "medium", "low"],
            reasons: list[str],
            roles: list[str],
            criteria: list[str],
        ) -> None:
            number = len(requirements) + 1
            requirements.append(
                CapabilityRequirement(
                    requirement_id=f"KR-{number:03d}",
                    type=type_,
                    scientific_question=question,
                    required_for=required_for,
                    priority=priority,
                    trigger_reasons=reasons,
                    required_evidence_roles=roles,
                    satisfaction_criteria=criteria,
                    status=ScientificStatus.UNKNOWN,
                    provenance=refs,
                )
            )

        missing_names = {item.name for item in missing}
        if "actual_power_W" in missing_names:
            add_requirement(
                "PHYSICS_DEPENDENCY",
                "目标设备的实际到样品平均功率或脉冲能量是多少？",
                "PhysicsCanonicalization.peak_fluence",
                "high",
                ["actual_power_W missing"],
                ["experimental_condition"],
                ["verified machine measurement or equipment record"],
            )
        if "beam_radius_um" in missing_names:
            add_requirement(
                "PHYSICS_DEPENDENCY",
                "目标设备采用何种光斑定义，其 beam radius 是多少？",
                "PhysicsCanonicalization.peak_fluence",
                "high",
                ["beam_radius_um missing"],
                ["experimental_condition"],
                ["beam definition and verified radius"],
            )
        if not (has_absolute_optics and has_local_morphology):
            add_requirement(
                "PARAMETER_PRIOR",
                f"{task.get('material', 'target material')} 在当前超快脉冲区间的烧蚀阈值合理范围是多少？",
                "LocalRemovalModel.F_th_eff",
                "high",
                ["F_th_eff not directly identifiable"],
                ["threshold", "material_property"],
                ["direct measurement or reconstructible applicable source"],
            )
        if not has_local_morphology:
            add_requirement(
                "MECHANISM_MODEL",
                "多脉冲孵化应采用哪种模型结构？",
                "MechanismModelRuntime.incubation",
                "high",
                ["local multi-pulse morphology missing"],
                ["mechanism_model", "formula", "functional_shape"],
                ["explicit model formula with source conditions"],
            )
        add_requirement(
            "PATH_STRATEGY",
            "浅层 2.5D 目标应优先评估哪些参数化路径族？",
            "ToolpathPlanner",
            "low",
            ["planning candidate ranking may use soft evidence"],
            ["path_strategy"],
            ["applicable path strategy evidence; never a machine hard bound"],
        )

        topology = infer_interaction_topology(str(task.get("geometry_type") or ""))
        simulation_supported = has_rows and topology in {
            InteractionTopology.OPEN_SURFACE,
            InteractionTopology.SHALLOW_2_5D,
        }
        status = ScientificStatus.PARTIAL if simulation_supported else ScientificStatus.UNKNOWN
        payload_for_id = {
            "task": task,
            "available": [item.model_dump(mode="json") for item in available],
            "missing": [item.model_dump(mode="json") for item in missing],
            "identifiability": [item.model_dump(mode="json") for item in identifiability],
        }
        return ScientificCapabilityReport(
            capability_id=_stable_id("capability", payload_for_id),
            task_ref=task_ref,
            input_refs=refs,
            interaction_topology=topology,
            simulation_supported=simulation_supported,
            supported_fidelity=(
                [
                    SimulationFidelity.F0_FIXED_KERNEL,
                    SimulationFidelity.F1_INCUBATION,
                    SimulationFidelity.F2_DEFOCUS_RECURSION,
                ]
                if topology in {InteractionTopology.OPEN_SURFACE, InteractionTopology.SHALLOW_2_5D}
                else []
            ),
            available=available,
            missing=missing,
            identifiability=identifiability,
            recommended_requirements=requirements,
            status=status,
            reason_codes=(
                ["terminal_macro_data_requires_effective_parameters"]
                if has_rows
                else ["no_target_data"]
            ),
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="ScientificCapabilityAnalyzer:v1",
                    role="capability_preflight",
                )
            ],
        )
