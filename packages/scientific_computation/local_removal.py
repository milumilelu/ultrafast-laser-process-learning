"""Canonical LocalRemovalModel initialization for all simulator modes."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from typing import Any

from packages.process_contracts.prior_objects import MechanismModelPrior, ParameterPrior
from packages.scientific_computation.contracts import (
    ArtifactRef,
    CalibrationResult,
    EvidenceOrigin,
    IdentifiabilityStatus,
    LocalRemovalModel,
    ParameterSemantics,
    ProvenanceRecord,
    RemovalKernel,
    RemovalModelMode,
    ScientificStatus,
)


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:16]}"


def gaussian_kernel(
    *, radius_um: float, peak_depth_um: float, grid_spacing_um: float, half_width_cells: int = 4
) -> RemovalKernel:
    if radius_um <= 0 or peak_depth_um < 0 or grid_spacing_um <= 0:
        raise ValueError("kernel radius/grid spacing must be positive and peak depth non-negative")
    values: list[list[float]] = []
    for iy in range(-half_width_cells, half_width_cells + 1):
        row: list[float] = []
        for ix in range(-half_width_cells, half_width_cells + 1):
            radius_sq = (ix * grid_spacing_um) ** 2 + (iy * grid_spacing_um) ** 2
            row.append(float(peak_depth_um * math.exp(-2.0 * radius_sq / radius_um**2)))
        values.append(row)
    return RemovalKernel(
        shape="GAUSSIAN",
        radius_um=radius_um,
        peak_depth_um=peak_depth_um,
        grid_spacing_um=grid_spacing_um,
        values_um=values,
        origin=EvidenceOrigin.MODEL_RECONSTRUCTION,
    )


class LocalRemovalModelFactory:
    """Create one canonical model contract for EMPIRICAL/RECONSTRUCTED/HYBRID."""

    def empirical(
        self,
        *,
        kernel: RemovalKernel | dict[str, Any],
        threshold_J_cm2: float,
        incubation_S: float = 1.0,
        delta_um: float | None = None,
        alpha_defocus_per_um: float = 0.0,
        input_refs: list[ArtifactRef] | None = None,
        assumptions: list[str] | None = None,
    ) -> LocalRemovalModel:
        value = (
            kernel if isinstance(kernel, RemovalKernel) else RemovalKernel.model_validate(kernel)
        )
        if value.origin == EvidenceOrigin.SYNTHETIC_TEST_FIXTURE:
            status = ScientificStatus.PARTIAL
            synthetic_note = [
                "synthetic fixture is a deterministic test input, not experimental validation"
            ]
        else:
            status = ScientificStatus.KNOWN
            synthetic_note = []
        return self._build(
            mode=RemovalModelMode.EMPIRICAL,
            kernel=value,
            threshold=threshold_J_cm2,
            incubation=incubation_S,
            delta=delta_um or max(value.peak_depth_um, 1e-6),
            alpha=alpha_defocus_per_um,
            semantics={
                "F_th_eff": ParameterSemantics.PHYSICAL
                if value.origin == EvidenceOrigin.EXPERIMENTAL_OBSERVATION
                else ParameterSemantics.PROVISIONAL,
                "incubation_S": ParameterSemantics.PROVISIONAL,
                "delta_eff": ParameterSemantics.EFFECTIVE,
                "alpha_defocus": ParameterSemantics.EFFECTIVE,
            },
            status=status,
            refs=list(input_refs or []),
            assumptions=[*(assumptions or []), *synthetic_note],
            origin_role="empirical_kernel_initialization",
        )

    def reconstructed(
        self,
        *,
        calibration: CalibrationResult | dict[str, Any],
        parameter_priors: Iterable[ParameterPrior | dict[str, Any]] = (),
        mechanism_priors: Iterable[MechanismModelPrior | dict[str, Any]] = (),
        beam_radius_um: float | None = None,
        grid_spacing_um: float = 2.0,
        input_refs: list[ArtifactRef] | None = None,
    ) -> LocalRemovalModel:
        result = (
            calibration
            if isinstance(calibration, CalibrationResult)
            else CalibrationResult.model_validate(calibration)
        )
        ppriors = [
            item if isinstance(item, ParameterPrior) else ParameterPrior.model_validate(item)
            for item in parameter_priors
        ]
        mpriors = [
            item
            if isinstance(item, MechanismModelPrior)
            else MechanismModelPrior.model_validate(item)
            for item in mechanism_priors
        ]
        estimates = {
            item.parameter: item
            for item in result.parameters
            if item.estimate is not None
            and item.identifiability != IdentifiabilityStatus.NOT_IDENTIFIABLE
        }

        def parameter_value(name: str, default: float) -> tuple[float, ParameterSemantics, str]:
            if name in estimates:
                estimate = estimates[name]
                assert estimate.estimate is not None
                return float(estimate.estimate), estimate.parameter_semantics, "target_calibration"
            aliases = {
                "F_th_eff": {"F_th_eff", "F_th", "ablation_threshold"},
                "delta_eff": {"delta_eff", "delta"},
            }
            prior = next(
                (
                    item
                    for item in ppriors
                    if item.parameter in aliases.get(name, {name})
                    and item.conflict_status.value == "NONE"
                ),
                None,
            )
            if prior is not None:
                return (
                    (prior.lower + prior.upper) / 2.0,
                    ParameterSemantics.PROVISIONAL,
                    "literature_prior_midpoint",
                )
            return default, ParameterSemantics.PROVISIONAL, "explicit_computational_default"

        threshold, threshold_semantics, threshold_source = parameter_value("F_th_eff", 1.0)
        incubation, incubation_semantics, incubation_source = parameter_value("incubation_S", 1.0)
        delta, delta_semantics, delta_source = parameter_value("delta_eff", 1.0)
        alpha, alpha_semantics, alpha_source = parameter_value("alpha_defocus", 0.02)
        thermal, thermal_semantics, thermal_source = parameter_value("thermal_memory_eff", 0.0)
        radius = float(beam_radius_um or 10.0)
        kernel = gaussian_kernel(
            radius_um=radius,
            peak_depth_um=max(delta * max(math.log(max(2.0 / threshold, 1.0)), 0.1), 1e-6),
            grid_spacing_um=grid_spacing_um,
        )
        refs = list(input_refs or [])
        refs.append(ArtifactRef(type="CalibrationResult", id=result.calibration_id))
        refs.extend(ArtifactRef(type="ParameterPrior", id=item.prior_id) for item in ppriors)
        refs.extend(ArtifactRef(type="MechanismModelPrior", id=item.prior_id) for item in mpriors)
        return self._build(
            mode=RemovalModelMode.RECONSTRUCTED,
            kernel=kernel,
            threshold=threshold,
            incubation=incubation,
            delta=max(delta, 1e-6),
            alpha=max(alpha, 0.0),
            thermal=max(thermal, 0.0),
            semantics={
                "F_th_eff": threshold_semantics,
                "incubation_S": incubation_semantics,
                "delta_eff": delta_semantics,
                "alpha_defocus": alpha_semantics,
                "thermal_memory_eff": thermal_semantics,
            },
            status=ScientificStatus.PARTIAL,
            refs=refs,
            assumptions=[
                f"F_th_eff source={threshold_source}",
                f"incubation_S source={incubation_source}",
                f"delta_eff source={delta_source}",
                f"alpha_defocus source={alpha_source}",
                f"thermal_memory_eff source={thermal_source}",
                "provisional defaults are computation hypotheses, not material constants",
            ],
            origin_role="reconstructed_model_initialization",
        )

    def hybrid(
        self,
        *,
        empirical_kernel: RemovalKernel | dict[str, Any],
        calibration: CalibrationResult | dict[str, Any],
        parameter_priors: Iterable[ParameterPrior | dict[str, Any]] = (),
        mechanism_priors: Iterable[MechanismModelPrior | dict[str, Any]] = (),
        input_refs: list[ArtifactRef] | None = None,
    ) -> LocalRemovalModel:
        reconstructed = self.reconstructed(
            calibration=calibration,
            parameter_priors=parameter_priors,
            mechanism_priors=mechanism_priors,
            input_refs=input_refs,
        )
        kernel = (
            empirical_kernel
            if isinstance(empirical_kernel, RemovalKernel)
            else RemovalKernel.model_validate(empirical_kernel)
        )
        return self._build(
            mode=RemovalModelMode.HYBRID,
            kernel=kernel,
            threshold=reconstructed.threshold_J_cm2,
            incubation=reconstructed.incubation_S,
            delta=reconstructed.delta_um,
            alpha=reconstructed.alpha_defocus_per_um,
            thermal=reconstructed.thermal_memory_eff,
            semantics=reconstructed.parameter_semantics,
            status=ScientificStatus.PARTIAL,
            refs=reconstructed.input_refs,
            assumptions=[
                *reconstructed.assumptions,
                "empirical kernel replaces reconstructed spatial kernel",
            ],
            origin_role="hybrid_model_initialization",
        )

    @staticmethod
    def _build(
        *,
        mode: RemovalModelMode,
        kernel: RemovalKernel,
        threshold: float,
        incubation: float,
        delta: float,
        alpha: float,
        semantics: dict[str, ParameterSemantics],
        status: ScientificStatus,
        refs: list[ArtifactRef],
        assumptions: list[str],
        origin_role: str,
        thermal: float = 0.0,
    ) -> LocalRemovalModel:
        payload = {
            "mode": mode.value,
            "kernel": kernel.model_dump(mode="json"),
            "threshold": threshold,
            "incubation": incubation,
            "delta": delta,
            "alpha": alpha,
            "refs": [item.model_dump(mode="json") for item in refs],
        }
        return LocalRemovalModel(
            model_id=_stable_id("local-removal", payload),
            input_refs=refs,
            mode=mode,
            kernel=kernel,
            threshold_J_cm2=threshold,
            incubation_S=incubation,
            delta_um=delta,
            alpha_defocus_per_um=alpha,
            thermal_memory_eff=thermal,
            parameter_semantics=semantics,
            status=status,
            assumptions=assumptions,
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="LocalRemovalModelFactory:v1",
                    role=origin_role,
                )
            ],
        )
