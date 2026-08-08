"""Stateful reduced-order 2.5D morphology simulator (F0-F2)."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from typing import Any

import numpy as np

from packages.scientific_computation.contracts import (
    ArtifactRef,
    LocalRemovalModel,
    MorphologyMetrics,
    MorphologySimulationResult,
    MorphologyState,
    ProvenanceRecord,
    ScientificStatus,
    SimulationFidelity,
)


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:16]}"


class MorphologySimulator:
    """One simulator for every LocalRemovalModel initialization mode."""

    def simulate(
        self,
        *,
        model: LocalRemovalModel | dict[str, Any],
        pulse_positions_um: Iterable[tuple[float, float]],
        grid_shape: tuple[int, int] = (31, 31),
        grid_spacing_um: float | None = None,
        peak_fluence_J_cm2: float = 2.0,
        fidelity: SimulationFidelity | str = SimulationFidelity.F2_DEFOCUS_RECURSION,
        deterministic_seed: int = 0,
        target_depth_field_um: list[list[float]] | np.ndarray | None = None,
        machining_time_s: float = 0.0,
        input_refs: list[ArtifactRef] | None = None,
    ) -> MorphologySimulationResult:
        removal_model = (
            model
            if isinstance(model, LocalRemovalModel)
            else LocalRemovalModel.model_validate(model)
        )
        fidelity_value = SimulationFidelity(fidelity)
        if peak_fluence_J_cm2 <= 0:
            raise ValueError("peak_fluence_J_cm2 must be positive and expressed in J/cm2")
        if len(grid_shape) != 2 or grid_shape[0] <= 0 or grid_shape[1] <= 0:
            raise ValueError("grid_shape must contain two positive dimensions")
        spacing = float(grid_spacing_um or removal_model.kernel.grid_spacing_um)
        if spacing <= 0:
            raise ValueError("grid_spacing_um must be positive")
        positions = [(float(x), float(y)) for x, y in pulse_positions_um]
        height = np.zeros(grid_shape, dtype=float)
        pulses = np.zeros(grid_shape, dtype=float)
        dose = np.zeros(grid_shape, dtype=float)
        thermal = np.zeros(grid_shape, dtype=float)
        center_y = (grid_shape[0] - 1) / 2.0
        center_x = (grid_shape[1] - 1) / 2.0

        for x_um, y_um in positions:
            ix = round(center_x + x_um / spacing)
            iy = round(center_y + y_um / spacing)
            if fidelity_value == SimulationFidelity.F0_FIXED_KERNEL:
                self._overlay_fixed(height, pulses, dose, removal_model, ix, iy, peak_fluence_J_cm2)
            elif fidelity_value == SimulationFidelity.F1_INCUBATION:
                self._overlay_incubation(
                    height, pulses, dose, removal_model, ix, iy, peak_fluence_J_cm2
                )
            elif fidelity_value in {
                SimulationFidelity.F2_DEFOCUS_RECURSION,
                SimulationFidelity.F3_THERMAL_MEMORY_PROXY,
            }:
                self._overlay_defocus(
                    height, pulses, dose, thermal, removal_model, ix, iy, peak_fluence_J_cm2
                )
            else:  # pragma: no cover - enum is exhaustive
                raise ValueError(f"unsupported fidelity: {fidelity_value}")
            if removal_model.thermal_memory_eff > 0:
                thermal *= 0.95

        depth = -height
        target = (
            np.asarray(target_depth_field_um, dtype=float)
            if target_depth_field_um is not None
            else None
        )
        if target is not None and target.shape != depth.shape:
            raise ValueError("target_depth_field_um shape must equal grid_shape")
        rmse = float(np.sqrt(np.mean((depth - target) ** 2))) if target is not None else None
        metrics = MorphologyMetrics(
            mean_depth_um=float(np.mean(depth)),
            max_depth_um=float(np.max(depth)) if depth.size else 0.0,
            removed_volume_um3=float(np.sum(depth) * spacing**2),
            morphology_rmse_um=rmse,
            machining_time_s=machining_time_s,
        )
        state = MorphologyState(
            height_field_um=height.tolist(),
            effective_pulse_count=pulses.tolist(),
            accumulated_fluence_J_cm2=dose.tolist(),
            thermal_memory_proxy=thermal.tolist(),
            grid_spacing_um=spacing,
            validity_flags=(
                ["F0_BASELINE_NOT_STATEFUL"]
                if fidelity_value == SimulationFidelity.F0_FIXED_KERNEL
                else []
            ),
        )
        refs = list(input_refs or [])
        model_ref = ArtifactRef(type="LocalRemovalModel", id=removal_model.model_id)
        refs.append(model_ref)
        payload = {
            "model": removal_model.model_id,
            "positions": positions,
            "grid": grid_shape,
            "spacing": spacing,
            "fluence": peak_fluence_J_cm2,
            "fidelity": fidelity_value.value,
            "state": state.model_dump(mode="json"),
        }
        return MorphologySimulationResult(
            simulation_id=_stable_id("morphology-simulation", payload),
            input_refs=refs,
            local_removal_model_ref=model_ref,
            fidelity=fidelity_value,
            state=state,
            target_depth_field_um=target.tolist() if target is not None else None,
            predicted_depth_field_um=depth.tolist(),
            difference_field_um=(depth - target).tolist() if target is not None else None,
            metrics=metrics,
            pulse_count=len(positions),
            deterministic_seed=deterministic_seed,
            status=(
                ScientificStatus.PARTIAL
                if removal_model.status != ScientificStatus.KNOWN
                else ScientificStatus.KNOWN
            ),
            warnings=(
                [
                    "F0 fixed-kernel superposition is a baseline, not a high-confidence multi-pulse model"
                ]
                if fidelity_value == SimulationFidelity.F0_FIXED_KERNEL
                else []
            ),
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="MorphologySimulator:v1",
                    role=fidelity_value.value,
                )
            ],
        )

    @staticmethod
    def removal_depth_field(result: MorphologySimulationResult) -> np.ndarray:
        return -np.asarray(result.state.height_field_um, dtype=float)

    @staticmethod
    def _overlay_fixed(
        height: np.ndarray,
        pulses: np.ndarray,
        dose: np.ndarray,
        model: LocalRemovalModel,
        ix: int,
        iy: int,
        fluence: float,
    ) -> None:
        values = np.asarray(model.kernel.values_um, dtype=float)
        cy, cx = values.shape[0] // 2, values.shape[1] // 2
        for ky in range(values.shape[0]):
            for kx in range(values.shape[1]):
                gy, gx = iy + ky - cy, ix + kx - cx
                if 0 <= gy < height.shape[0] and 0 <= gx < height.shape[1]:
                    height[gy, gx] -= values[ky, kx]
                    if values[ky, kx] > 0:
                        pulses[gy, gx] += 1
                        dose[gy, gx] += fluence

    @staticmethod
    def _overlay_incubation(
        height: np.ndarray,
        pulses: np.ndarray,
        dose: np.ndarray,
        model: LocalRemovalModel,
        ix: int,
        iy: int,
        fluence: float,
    ) -> None:
        values = np.asarray(model.kernel.values_um, dtype=float)
        cy, cx = values.shape[0] // 2, values.shape[1] // 2
        base_log = (
            max(math.log(fluence / model.threshold_J_cm2), 1e-12)
            if fluence > model.threshold_J_cm2
            else 1e-12
        )
        for ky in range(values.shape[0]):
            for kx in range(values.shape[1]):
                gy, gx = iy + ky - cy, ix + kx - cx
                if not (0 <= gy < height.shape[0] and 0 <= gx < height.shape[1]):
                    continue
                next_count = pulses[gy, gx] + 1.0
                threshold = model.threshold_J_cm2 * next_count ** (model.incubation_S - 1.0)
                scale = max(math.log(fluence / threshold), 0.0) / base_log
                height[gy, gx] -= values[ky, kx] * scale
                if values[ky, kx] > 0:
                    pulses[gy, gx] = next_count
                    dose[gy, gx] += fluence

    @staticmethod
    def _overlay_defocus(
        height: np.ndarray,
        pulses: np.ndarray,
        dose: np.ndarray,
        thermal: np.ndarray,
        model: LocalRemovalModel,
        ix: int,
        iy: int,
        fluence: float,
    ) -> None:
        if not (0 <= iy < height.shape[0] and 0 <= ix < height.shape[1]):
            return
        local_depth = max(-height[iy, ix], 0.0)
        radius_scale = 1.0 + model.alpha_defocus_per_um * local_depth
        radius = model.kernel.radius_um * radius_scale
        effective_peak = fluence / radius_scale**2
        half_width = max(1, math.ceil(3.0 * radius / model.kernel.grid_spacing_um))
        for gy in range(max(0, iy - half_width), min(height.shape[0], iy + half_width + 1)):
            for gx in range(max(0, ix - half_width), min(height.shape[1], ix + half_width + 1)):
                radial_sq = ((gx - ix) * model.kernel.grid_spacing_um) ** 2 + (
                    (gy - iy) * model.kernel.grid_spacing_um
                ) ** 2
                local_fluence = effective_peak * math.exp(-2.0 * radial_sq / radius**2)
                next_count = pulses[gy, gx] + 1.0
                threshold = model.threshold_J_cm2 * next_count ** (model.incubation_S - 1.0)
                if local_fluence <= threshold:
                    continue
                increment = model.delta_um * math.log(local_fluence / threshold)
                height[gy, gx] -= increment
                pulses[gy, gx] = next_count
                dose[gy, gx] += local_fluence
                thermal[gy, gx] += model.thermal_memory_eff * local_fluence
