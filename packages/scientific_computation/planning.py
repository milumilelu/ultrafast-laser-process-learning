"""Simulator-in-the-loop parameterized toolpath planning."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from typing import Any

import numpy as np

from packages.process_contracts.prior_objects import PlanningPreferencePrior
from packages.scientific_computation.contracts import (
    ArtifactRef,
    ConstraintValue,
    LocalRemovalModel,
    MorphologySimulationResult,
    PathFamily,
    PlanStatus,
    ProvenanceRecord,
    SimulationFidelity,
    TargetGeometry,
    ToolpathPlan,
)
from packages.scientific_computation.simulator import MorphologySimulator


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:16]}"


class ToolpathPlanner:
    """Choose a path family by evaluating predicted morphology, not raw recipes."""

    def __init__(self, simulator: MorphologySimulator | None = None) -> None:
        self.simulator = simulator or MorphologySimulator()

    def plan(
        self,
        *,
        target: TargetGeometry | dict[str, Any],
        model: LocalRemovalModel | dict[str, Any],
        laser_parameters: dict[str, float | int | str],
        machine_constraints: Iterable[ConstraintValue | dict[str, Any]] = (),
        planning_priors: Iterable[PlanningPreferencePrior | dict[str, Any]] = (),
        path_families: Iterable[PathFamily | str] = (PathFamily.RASTER, PathFamily.CROSS_HATCH),
        fidelity: SimulationFidelity | str = SimulationFidelity.F2_DEFOCUS_RECURSION,
        deterministic_seed: int = 42,
        input_refs: list[ArtifactRef] | None = None,
    ) -> tuple[ToolpathPlan, MorphologySimulationResult]:
        geometry = (
            target if isinstance(target, TargetGeometry) else TargetGeometry.model_validate(target)
        )
        removal_model = (
            model
            if isinstance(model, LocalRemovalModel)
            else LocalRemovalModel.model_validate(model)
        )
        constraints = [
            item if isinstance(item, ConstraintValue) else ConstraintValue.model_validate(item)
            for item in machine_constraints
        ]
        priors = [
            item
            if isinstance(item, PlanningPreferencePrior)
            else PlanningPreferencePrior.model_validate(item)
            for item in planning_priors
        ]
        families = [PathFamily(value) for value in path_families]
        supported = {
            PathFamily.RASTER,
            PathFamily.CROSS_HATCH,
            PathFamily.SINGLE_LINE,
            PathFamily.CONTOUR,
        }
        if not families or any(family not in supported for family in families):
            raise ValueError("planner requires supported parameterized path families")

        grid_shape = (
            max(5, round(geometry.height_um / geometry.grid_spacing_um) + 1),
            max(5, round(geometry.width_um / geometry.grid_spacing_um) + 1),
        )
        target_depth = np.full(grid_shape, geometry.target_depth_um, dtype=float)
        frequency_kHz = float(laser_parameters.get("frequency_kHz", 100.0))
        scan_speed_mm_s = float(laser_parameters.get("scan_speed_mm_s", 100.0))
        peak_fluence = float(
            laser_parameters.get(
                "peak_fluence_J_cm2", max(removal_model.threshold_J_cm2 * 2.0, 1e-6)
            )
        )
        if frequency_kHz <= 0 or scan_speed_mm_s <= 0 or peak_fluence <= 0:
            raise ValueError("frequency, scan speed, and peak fluence must be positive")
        pulse_spacing_um = max(scan_speed_mm_s / frequency_kHz, geometry.grid_spacing_um)
        hatch_candidates = sorted(
            {
                max(geometry.grid_spacing_um, removal_model.kernel.radius_um * 0.75),
                max(geometry.grid_spacing_um, removal_model.kernel.radius_um),
                max(geometry.grid_spacing_um, removal_model.kernel.radius_um * 1.5),
            }
        )
        pass_candidates = (1, 2)
        candidates: list[tuple[float, ToolpathPlan, MorphologySimulationResult]] = []
        prior_refs = [
            ArtifactRef(type="PlanningPreferencePrior", id=item.prior_id) for item in priors
        ]
        refs = [
            *(input_refs or []),
            ArtifactRef(type="LocalRemovalModel", id=removal_model.model_id),
            *prior_refs,
        ]

        for family in families:
            for hatch in hatch_candidates:
                for passes in pass_candidates:
                    positions = self._positions(
                        family=family,
                        geometry=geometry,
                        hatch_um=hatch,
                        pulse_spacing_um=pulse_spacing_um,
                        passes=passes,
                    )
                    # Protect V1 acceptance runs from accidental event/artifact explosion.
                    if len(positions) > 10_000:
                        stride = math.ceil(len(positions) / 10_000)
                        positions = positions[::stride]
                    path_length_um = max(len(positions) - 1, 0) * pulse_spacing_um
                    machining_time = path_length_um / (scan_speed_mm_s * 1000.0)
                    simulation = self.simulator.simulate(
                        model=removal_model,
                        pulse_positions_um=positions,
                        grid_shape=grid_shape,
                        grid_spacing_um=geometry.grid_spacing_um,
                        peak_fluence_J_cm2=peak_fluence,
                        fidelity=fidelity,
                        deterministic_seed=deterministic_seed,
                        target_depth_field_um=target_depth,
                        machining_time_s=machining_time,
                        input_refs=refs,
                    )
                    morphology_error = float(simulation.metrics.morphology_rmse_um or 0.0)
                    time_penalty = 0.01 * machining_time
                    prior_adjustment = self._planning_prior_adjustment(family, priors)
                    objective = morphology_error + time_penalty + prior_adjustment
                    plan_payload = {
                        "family": family.value,
                        "hatch": hatch,
                        "passes": passes,
                        "simulation": simulation.simulation_id,
                        "objective": objective,
                    }
                    plan = ToolpathPlan(
                        plan_id=_stable_id("toolpath-plan", plan_payload),
                        input_refs=refs
                        + [
                            ArtifactRef(
                                type="MorphologySimulationResult", id=simulation.simulation_id
                            )
                        ],
                        path_family=family,
                        path_parameters={
                            "hatch_um": hatch,
                            "passes": passes,
                            "pulse_spacing_um": pulse_spacing_um,
                            "angle_deg": 0.0,
                            "angle_change_per_pass_deg": 90.0
                            if family == PathFamily.CROSS_HATCH
                            else 0.0,
                            "pulse_position_count": len(positions),
                        },
                        laser_parameters=dict(laser_parameters),
                        predicted_metrics=simulation.metrics,
                        machine_constraints=constraints,
                        simulation_ref=ArtifactRef(
                            type="MorphologySimulationResult", id=simulation.simulation_id
                        ),
                        planning_prior_refs=prior_refs,
                        status=PlanStatus.CANDIDATE,
                        objective_value=objective,
                        candidate_summary=[],
                        provenance=[
                            ProvenanceRecord(
                                source_type="DETERMINISTIC_COMPUTATION",
                                source_ref="ToolpathPlanner:v1",
                                role="simulator_in_the_loop_evaluation",
                            )
                        ],
                    )
                    candidates.append((objective, plan, simulation))

        candidates.sort(key=lambda item: (item[0], item[1].path_family.value, item[1].plan_id))
        best_objective, best_plan, best_simulation = candidates[0]
        summary = [
            {
                "plan_id": plan.plan_id,
                "path_family": plan.path_family.value,
                "objective_value": objective,
                "morphology_rmse_um": simulation.metrics.morphology_rmse_um,
                "machining_time_s": simulation.metrics.machining_time_s,
                "simulation_ref": simulation.simulation_id,
            }
            for objective, plan, simulation in candidates
        ]
        best_plan = best_plan.model_copy(
            update={
                "status": PlanStatus.RECOMMENDED,
                "objective_value": best_objective,
                "candidate_summary": summary,
            }
        )
        return best_plan, best_simulation

    @staticmethod
    def _planning_prior_adjustment(
        family: PathFamily, priors: list[PlanningPreferencePrior]
    ) -> float:
        adjustment = 0.0
        for prior in priors:
            if prior.path_families and family.value in prior.path_families:
                # Small soft ranking term only; never a hard constraint.
                adjustment -= 0.001
        return adjustment

    @staticmethod
    def _positions(
        *,
        family: PathFamily,
        geometry: TargetGeometry,
        hatch_um: float,
        pulse_spacing_um: float,
        passes: int,
    ) -> list[tuple[float, float]]:
        x_values = np.arange(
            -geometry.width_um / 2, geometry.width_um / 2 + pulse_spacing_um * 0.5, pulse_spacing_um
        )
        y_values = np.arange(
            -geometry.height_um / 2, geometry.height_um / 2 + hatch_um * 0.5, hatch_um
        )
        positions: list[tuple[float, float]] = []
        if family == PathFamily.SINGLE_LINE:
            positions = [(float(x), 0.0) for x in x_values]
        elif family == PathFamily.RASTER:
            for pass_index in range(passes):
                for line_index, y in enumerate(y_values):
                    xs = x_values if (line_index + pass_index) % 2 == 0 else x_values[::-1]
                    positions.extend((float(x), float(y)) for x in xs)
        elif family == PathFamily.CROSS_HATCH:
            for pass_index in range(passes):
                if pass_index % 2 == 0:
                    for line_index, y in enumerate(y_values):
                        xs = x_values if line_index % 2 == 0 else x_values[::-1]
                        positions.extend((float(x), float(y)) for x in xs)
                else:
                    y_pulses = np.arange(
                        -geometry.height_um / 2,
                        geometry.height_um / 2 + pulse_spacing_um * 0.5,
                        pulse_spacing_um,
                    )
                    x_lines = np.arange(
                        -geometry.width_um / 2, geometry.width_um / 2 + hatch_um * 0.5, hatch_um
                    )
                    for line_index, x in enumerate(x_lines):
                        ys = y_pulses if line_index % 2 == 0 else y_pulses[::-1]
                        positions.extend((float(x), float(y)) for y in ys)
        elif family == PathFamily.CONTOUR:
            top, bottom = geometry.height_um / 2, -geometry.height_um / 2
            left, right = -geometry.width_um / 2, geometry.width_um / 2
            positions.extend((float(x), bottom) for x in x_values)
            positions.extend((right, float(y)) for y in y_values)
            positions.extend((float(x), top) for x in x_values[::-1])
            positions.extend((left, float(y)) for y in y_values[::-1])
        return positions
