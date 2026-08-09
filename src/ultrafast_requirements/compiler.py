"""Requirement compiler based on recursive dependency closure."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ultrafast_requirements.graph import ScientificDependencyGraph, default_dependency_graph
from ultrafast_requirements.schemas import (
    CalibrationRequirement,
    DataRequirement,
    DependencySpec,
    KnowledgeRequirement,
    Requirement,
    RequirementCategory,
    RequirementSet,
    RequirementSource,
    RequirementStatus,
    ResourceRequirement,
)

_TASK_ALIASES = {
    "frequency_kHz": "frequency_Hz",
    "repetition_rate_Hz": "frequency_Hz",
    "average_power_W": "laser_power_W",
    "spot_radius_um": "beam_radius_m",
    "scan_speed_mm_s": "scan_speed_m_s",
}


class RequirementCompiler:
    def __init__(self, graph: ScientificDependencyGraph | None = None) -> None:
        self.graph = graph or default_dependency_graph()

    def compile(
        self,
        task_spec: Mapping[str, Any],
        available_quantities: Mapping[str, Any] | set[str] | None = None,
    ) -> RequirementSet:
        task = dict(task_spec)
        roots = self._root_quantities(task)
        supplied = self._supplied(task, available_quantities)
        preferred = dict(task.get("capability_by_quantity") or {})
        if task.get("model_capability_id") and len(roots) == 1:
            preferred[roots[0]] = str(task["model_capability_id"])

        compiled: dict[str, Requirement] = {}
        selected: list[str] = []
        visiting: list[str] = []

        def visit(quantity: str, dependency: DependencySpec, required_by: str) -> None:
            if quantity in compiled:
                if required_by not in compiled[quantity].required_by:
                    compiled[quantity].required_by.append(required_by)
                return
            conditions = {**self._task_conditions(task), **dependency.conditions}
            if quantity in supplied and supplied[quantity] is not None:
                compiled[quantity] = Requirement(
                    requirement_id=self._requirement_id(quantity, conditions),
                    quantity=quantity,
                    role=dependency.role,
                    required_by=[required_by],
                    acceptable_sources=dependency.acceptable_sources,
                    expected_unit=dependency.expected_unit,
                    conditions=conditions,
                    resolution_policy=dependency.resolution_policy,
                    status=RequirementStatus.SATISFIED,
                    category=RequirementCategory.SATISFIED,
                    query_terms=dependency.query_terms,
                    supplied_value=supplied[quantity],
                )
                return
            if quantity in visiting:
                cycle = " -> ".join([*visiting, quantity])
                raise ValueError(f"cyclic scientific dependency: {cycle}")
            provider = self.graph.choose_provider(quantity, preferred.get(quantity))
            if provider is not None:
                compiled[quantity] = Requirement(
                    requirement_id=self._requirement_id(quantity, conditions),
                    quantity=quantity,
                    role=dependency.role,
                    required_by=[required_by],
                    acceptable_sources=[RequirementSource.DERIVED],
                    expected_unit=dependency.expected_unit,
                    conditions=conditions,
                    resolution_policy="derive_after_dependencies_are_satisfied",
                    status=RequirementStatus.DERIVABLE,
                    category=RequirementCategory.DERIVABLE,
                    derivation_capability_id=provider.capability_id,
                    query_terms=dependency.query_terms,
                )
                if provider.capability_id not in selected:
                    selected.append(provider.capability_id)
                visiting.append(quantity)
                for child in provider.inputs:
                    visit(child.quantity, child, provider.capability_id)
                visiting.pop()
                return
            compiled[quantity] = self._missing_requirement(
                dependency, required_by=required_by, conditions=conditions
            )

        root_dependency = DependencySpec(
            quantity="",
            role="task_target",
            acceptable_sources=[RequirementSource.DERIVED, RequirementSource.DATASET],
            resolution_policy="selected_scientific_model_required",
        )
        for root in roots:
            visit(root, root_dependency.model_copy(update={"quantity": root}), "task")
        set_payload = {"task": task, "roots": roots, "supplied": sorted(supplied)}
        digest = hashlib.sha256(
            json.dumps(set_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        return RequirementSet(
            requirement_set_id=f"requirements-{digest}",
            task_spec=task,
            root_quantities=roots,
            selected_capabilities=selected,
            requirements=list(compiled.values()),
        )

    @staticmethod
    def _root_quantities(task: dict[str, Any]) -> list[str]:
        roots = task.get("goal_quantities") or task.get("required_outputs")
        if isinstance(roots, str):
            roots = [roots]
        if not roots and task.get("target"):
            roots = [task["target"]]
        if not roots:
            raise ValueError("task_spec must declare goal_quantities, required_outputs, or target")
        return [str(item) for item in roots]

    @staticmethod
    def _task_conditions(task: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "material",
            "material_grade",
            "laser_type",
            "wavelength_nm",
            "pulse_width_fs",
            "process_type",
            "geometry_type",
            "environment",
        )
        return {key: task[key] for key in keys if task.get(key) is not None}

    @staticmethod
    def _supplied(
        task: dict[str, Any],
        available: Mapping[str, Any] | set[str] | None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        task_values = task.get("available_quantities") or task.get("known_quantities") or {}
        if isinstance(task_values, Mapping):
            values.update(task_values)
        if isinstance(available, Mapping):
            values.update(available)
        elif isinstance(available, set):
            values.update({name: True for name in available})
        for source, canonical in _TASK_ALIASES.items():
            if source in task and task[source] is not None:
                values.setdefault(canonical, task[source])
        for canonical in set(_TASK_ALIASES.values()):
            if canonical in task and task[canonical] is not None:
                values.setdefault(canonical, task[canonical])
        return dict(values)

    @staticmethod
    def _requirement_id(quantity: str, conditions: dict[str, Any]) -> str:
        payload = json.dumps(conditions, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(f"{quantity}\n{payload}".encode()).hexdigest()[:16]
        return f"req-{digest}"

    def _missing_requirement(
        self,
        dependency: DependencySpec,
        *,
        required_by: str,
        conditions: dict[str, Any],
    ) -> Requirement:
        common = {
            "requirement_id": self._requirement_id(dependency.quantity, conditions),
            "quantity": dependency.quantity,
            "role": dependency.role,
            "required_by": [required_by],
            "acceptable_sources": dependency.acceptable_sources,
            "expected_unit": dependency.expected_unit,
            "conditions": conditions,
            "resolution_policy": dependency.resolution_policy,
            "status": RequirementStatus.MISSING,
            "query_terms": dependency.query_terms,
        }
        sources = set(dependency.acceptable_sources)
        if RequirementSource.LITERATURE in sources or RequirementSource.PRIOR in sources:
            return KnowledgeRequirement(**common)
        if RequirementSource.CALIBRATION in sources:
            return CalibrationRequirement(**common)
        if RequirementSource.EQUIPMENT in sources or RequirementSource.TASK in sources:
            return ResourceRequirement(**common)
        return DataRequirement(**common)
