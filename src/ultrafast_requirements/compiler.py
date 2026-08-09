"""Requirement compiler based on recursive scientific dependency closure."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ultrafast_requirements.graph import ScientificDependencyGraph, default_dependency_graph
from ultrafast_requirements.schemas import (
    CalibrationRequirement,
    Constraint,
    DataRequirement,
    DecisionVariable,
    DependencySpec,
    KnowledgeRequirement,
    QuantityValue,
    Requirement,
    RequirementCategory,
    RequirementSet,
    RequirementSource,
    RequirementStatus,
    ResolutionStatus,
    ResolutionStep,
    ResourceRequirement,
    VariableSemantic,
    VerificationStatus,
)
from ultrafast_requirements.values import QuantityInputNormalizer


class RequirementCompiler:
    def __init__(
        self,
        graph: ScientificDependencyGraph | None = None,
        normalizer: QuantityInputNormalizer | None = None,
    ) -> None:
        self.graph = graph or default_dependency_graph()
        self.normalizer = normalizer or QuantityInputNormalizer()

    def compile(
        self,
        task_spec: Mapping[str, Any],
        available_quantities: Mapping[str, Any] | list[dict[str, Any]] | None = None,
    ) -> RequirementSet:
        task = dict(task_spec)
        task_type = str(task.get("task_type") or "").strip().lower()
        if task_type not in {"optimization", "prediction"}:
            raise ValueError("task_spec.task_type must be optimization or prediction")
        roots = self._root_quantities(task)
        values = self._normalize_values(task, available_quantities)
        decisions = self.normalizer.normalize_decisions(task.get("decision_variables"))
        if task_type == "optimization" and not decisions:
            raise ValueError("optimization task requires at least one DecisionVariable")
        if task_type == "prediction" and decisions:
            raise ValueError("prediction task cannot declare DecisionVariable entries")
        constraints = self._constraints(task)
        value_by_quantity = {item.canonical_quantity: item for item in values}
        decision_by_quantity = {item.canonical_quantity: item for item in decisions}
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
            decision = decision_by_quantity.get(quantity)
            if decision is not None:
                compiled[quantity] = self._satisfied_decision(
                    dependency, decision, required_by, conditions
                )
                return
            supplied = value_by_quantity.get(quantity)
            if supplied is not None:
                compiled[quantity] = self._satisfied_value(
                    dependency, supplied, required_by, conditions
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
                    variable_semantic=dependency.variable_semantic,
                    resolution_chain=[
                        ResolutionStep(
                            order=1,
                            source=RequirementSource.DERIVED,
                            status=ResolutionStatus.PENDING,
                        )
                    ],
                    current_resolution_step=0,
                )
                if provider.capability_id not in selected:
                    selected.append(provider.capability_id)
                visiting.append(quantity)
                for child in provider.inputs:
                    visit(child.quantity, child, provider.capability_id)
                visiting.pop()
                return
            compiled[quantity] = self._missing_requirement(
                dependency,
                required_by=required_by,
                conditions=conditions,
                optimization_task=task_type == "optimization",
            )

        root_dependency = DependencySpec(
            quantity="",
            role="task_target",
            acceptable_sources=[RequirementSource.DERIVED, RequirementSource.DATASET],
            resolution_policy="selected_scientific_model_required",
            variable_semantic=VariableSemantic.TARGET_OUTPUT,
        )
        for root in roots:
            visit(root, root_dependency.model_copy(update={"quantity": root}), "task")
        reached_decisions = set(compiled).intersection(decision_by_quantity)
        unused = set(decision_by_quantity).difference(reached_decisions)
        if unused:
            raise ValueError(f"decision variables not consumed by selected model: {sorted(unused)}")
        set_payload = {
            "task": task,
            "roots": roots,
            "values": [item.model_dump(mode="json") for item in values],
            "decisions": [item.model_dump(mode="json") for item in decisions],
        }
        digest = hashlib.sha256(
            json.dumps(set_payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        return RequirementSet(
            requirement_set_id=f"requirements-{digest}",
            task_spec=task,
            root_quantities=roots,
            selected_capabilities=selected,
            requirements=list(compiled.values()),
            quantity_values=values,
            decision_variables=decisions,
            constraints=constraints,
        )

    def _normalize_values(
        self,
        task: dict[str, Any],
        available: Mapping[str, Any] | list[dict[str, Any]] | None,
    ) -> list[QuantityValue]:
        embedded = task.get("available_quantities")
        if embedded is not None and available is not None:
            raise ValueError("available_quantities must be supplied in exactly one location")
        return self.normalizer.normalize_values(available if available is not None else embedded)

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
            "process_type",
            "geometry_type",
            "environment",
        )
        return {key: task[key] for key in keys if task.get(key) is not None}

    @staticmethod
    def _constraints(task: dict[str, Any]) -> list[Constraint]:
        constraints = [Constraint.model_validate(item) for item in task.get("constraints") or []]
        ids = [item.constraint_id for item in constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate constraint_id")
        return constraints

    @staticmethod
    def _requirement_id(quantity: str, conditions: dict[str, Any]) -> str:
        payload = json.dumps(conditions, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(f"{quantity}\n{payload}".encode()).hexdigest()[:16]
        return f"req-{digest}"

    def _satisfied_value(
        self,
        dependency: DependencySpec,
        supplied: QuantityValue,
        required_by: str,
        conditions: dict[str, Any],
    ) -> Requirement:
        if supplied.verification_status != VerificationStatus.VERIFIED:
            raise ValueError(f"unverified quantity cannot satisfy dependency: {supplied.quantity}")
        return Requirement(
            requirement_id=self._requirement_id(dependency.quantity, conditions),
            quantity=dependency.quantity,
            role=dependency.role,
            required_by=[required_by],
            acceptable_sources=dependency.acceptable_sources,
            expected_unit=dependency.expected_unit,
            conditions=conditions,
            resolution_policy=dependency.resolution_policy,
            status=RequirementStatus.SATISFIED,
            category=RequirementCategory.SATISFIED,
            query_terms=dependency.query_terms,
            supplied_value=supplied.model_dump(mode="json"),
            variable_semantic=dependency.variable_semantic,
            resolution_chain=[
                ResolutionStep(order=1, source=supplied.source, status=ResolutionStatus.RESOLVED)
            ],
        )

    def _satisfied_decision(
        self,
        dependency: DependencySpec,
        decision: DecisionVariable,
        required_by: str,
        conditions: dict[str, Any],
    ) -> Requirement:
        if decision.verification_status != VerificationStatus.VERIFIED:
            raise ValueError(
                f"unverified decision variable cannot satisfy dependency: {decision.quantity}"
            )
        return Requirement(
            requirement_id=self._requirement_id(dependency.quantity, conditions),
            quantity=dependency.quantity,
            role="decision_variable_search_space",
            required_by=[required_by],
            acceptable_sources=[RequirementSource.TASK, RequirementSource.EQUIPMENT],
            expected_unit=decision.canonical_unit,
            conditions=conditions,
            resolution_policy="bounded_decision_search",
            status=RequirementStatus.SATISFIED,
            category=RequirementCategory.SATISFIED,
            query_terms=dependency.query_terms,
            supplied_value=decision.model_dump(mode="json"),
            variable_semantic=VariableSemantic.DECISION_VARIABLE,
            resolution_chain=[
                ResolutionStep(order=1, source=decision.source, status=ResolutionStatus.RESOLVED)
            ],
        )

    def _missing_requirement(
        self,
        dependency: DependencySpec,
        *,
        required_by: str,
        conditions: dict[str, Any],
        optimization_task: bool,
    ) -> Requirement:
        semantic = dependency.variable_semantic
        sources = list(dependency.acceptable_sources)
        policy = dependency.resolution_policy
        if optimization_task and dependency.optimizable:
            semantic = VariableSemantic.DECISION_VARIABLE
            sources = [RequirementSource.TASK, RequirementSource.EQUIPMENT]
            policy = "decision_variable_bounds_resolution_and_admissible_region_required"
        chain = [
            ResolutionStep(order=index + 1, source=source)
            for index, source in enumerate(sources)
        ]
        common = {
            "requirement_id": self._requirement_id(dependency.quantity, conditions),
            "quantity": dependency.quantity,
            "role": dependency.role,
            "required_by": [required_by],
            "acceptable_sources": sources,
            "expected_unit": dependency.expected_unit,
            "conditions": conditions,
            "resolution_policy": policy,
            "status": RequirementStatus.MISSING,
            "query_terms": dependency.query_terms,
            "variable_semantic": semantic,
            "resolution_chain": chain,
            "current_resolution_step": 0 if chain else None,
        }
        source_set = set(sources)
        if RequirementSource.LITERATURE in source_set or RequirementSource.STRUCTURED_KNOWLEDGE in source_set:
            return KnowledgeRequirement(**common)
        if RequirementSource.CALIBRATION in source_set:
            return CalibrationRequirement(**common)
        if RequirementSource.EQUIPMENT in source_set or RequirementSource.TASK in source_set:
            return ResourceRequirement(**common)
        return DataRequirement(**common)
