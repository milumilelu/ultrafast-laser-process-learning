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
    ParameterBinding,
    ParameterSemantics,
    ParameterSourceType,
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
        allow_computational_defaults: bool = False,
        input_refs: list[ArtifactRef] | None = None,
    ) -> LocalRemovalModel:
        """RECONSTRUCTED model with structured parameter bindings.

        Mechanism semantics (阶段二 T3/T4):
        - critical parameters (F_th_eff / incubation_S / delta_eff / beam
          radius): unresolved -> raise (fail closed).
        - optional mechanisms (DEFOCUS_RECURSION -> alpha_defocus,
          THERMAL_MEMORY -> thermal_memory_eff): unresolved -> mechanism
          INACTIVE, never a hardcoded default.
        - COMPUTATIONAL_DEFAULT bindings exist only in SANDBOX
          (allow_computational_defaults=True).
        """
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

        def _prior_for(name: str) -> ParameterPrior | None:
            aliases = {
                "F_th_eff": {"F_th_eff", "F_th", "ablation_threshold"},
                "delta_eff": {"delta_eff", "delta"},
            }
            return next(
                (
                    item
                    for item in ppriors
                    if item.parameter in aliases.get(name, {name})
                    and item.conflict_status.value == "NONE"
                ),
                None,
            )

        def _resolve(name: str) -> tuple[float, ParameterSemantics, ParameterSourceType, str] | None:
            """None = UNRESOLVED (mechanism stays inactive)."""
            estimate = estimates.get(name)
            if estimate is not None:
                assert estimate.estimate is not None
                return (
                    float(estimate.estimate),
                    estimate.parameter_semantics,
                    ParameterSourceType.TARGET_CALIBRATION,
                    f"calibration:{result.calibration_id}",
                )
            prior = _prior_for(name)
            if prior is not None:
                fixture_based = any(
                    str(ref.type) == "DemoFixturePrior" for ref in prior.provenance
                )
                return (
                    (prior.lower + prior.upper) / 2.0,
                    ParameterSemantics.PROVISIONAL,
                    ParameterSourceType.DEMO_FIXTURE
                    if fixture_based
                    else ParameterSourceType.LITERATURE_PRIOR,
                    prior.prior_id,
                )
            return None

        def _critical(name: str, default: float) -> tuple[float, ParameterSemantics, ParameterSourceType, str]:
            resolved = _resolve(name)
            if resolved is not None:
                return resolved
            if allow_computational_defaults:
                return (
                    default,
                    ParameterSemantics.PROVISIONAL,
                    ParameterSourceType.COMPUTATIONAL_DEFAULT,
                    "sandbox-default",
                )
            raise ValueError(
                f"{name} is unresolved (no prior, no calibration estimate) "
                "and computational defaults are not allowed in this execution mode"
            )

        def _optional(
            name: str, default: float
        ) -> tuple[float, ParameterSemantics, ParameterSourceType, str] | None:
            resolved = _resolve(name)
            if resolved is not None:
                return resolved
            if allow_computational_defaults:
                return (
                    default,
                    ParameterSemantics.PROVISIONAL,
                    ParameterSourceType.COMPUTATIONAL_DEFAULT,
                    "sandbox-default",
                )
            return None

        threshold, threshold_semantics, threshold_source, threshold_ref = _critical(
            "F_th_eff", 1.0
        )
        incubation, incubation_semantics, incubation_source, incubation_ref = _critical(
            "incubation_S", 1.0
        )
        delta, delta_semantics, delta_source, delta_ref = _critical("delta_eff", 1.0)
        alpha_binding = _optional("alpha_defocus", 0.02)
        thermal_binding = _optional("thermal_memory_eff", 0.0)
        if beam_radius_um is None:
            raise ValueError(
                "beam_radius_um is required for RECONSTRUCTED LocalRemovalModel "
                "(no silent computational default; resolve from the equipment snapshot)"
            )
        radius = float(beam_radius_um)
        if radius <= 0:
            raise ValueError(f"beam_radius_um must be positive, got {radius}")
        kernel = gaussian_kernel(
            radius_um=radius,
            peak_depth_um=max(delta * max(math.log(max(2.0 / threshold, 1.0)), 0.1), 1e-6),
            grid_spacing_um=grid_spacing_um,
        )
        refs = list(input_refs or [])
        refs.append(ArtifactRef(type="CalibrationResult", id=result.calibration_id))
        refs.extend(ArtifactRef(type="ParameterPrior", id=item.prior_id) for item in ppriors)
        refs.extend(ArtifactRef(type="MechanismModelPrior", id=item.prior_id) for item in mpriors)

        bindings: list[ParameterBinding] = [
            ParameterBinding(
                parameter="F_th_eff",
                value=threshold,
                unit="J/cm2",
                source_type=threshold_source,
                source_ref=threshold_ref,
                semantics=threshold_semantics,
            ),
            ParameterBinding(
                parameter="incubation_S",
                value=incubation,
                unit="dimensionless",
                source_type=incubation_source,
                source_ref=incubation_ref,
                semantics=incubation_semantics,
            ),
            ParameterBinding(
                parameter="delta_eff",
                value=delta,
                unit="um",
                source_type=delta_source,
                source_ref=delta_ref,
                semantics=delta_semantics,
            ),
            ParameterBinding(
                parameter="beam_radius_um",
                value=radius,
                unit="um",
                source_type=ParameterSourceType.DERIVED,
                source_ref="machine-profile-snapshot",
                semantics=ParameterSemantics.PHYSICAL,
            ),
        ]
        if alpha_binding is not None:
            bindings.append(
                ParameterBinding(
                    parameter="alpha_defocus",
                    value=alpha_binding[0],
                    unit="1/um",
                    source_type=alpha_binding[2],
                    source_ref=alpha_binding[3],
                    semantics=alpha_binding[1],
                )
            )
        if thermal_binding is not None:
            bindings.append(
                ParameterBinding(
                    parameter="thermal_memory_eff",
                    value=thermal_binding[0],
                    unit="dimensionless",
                    source_type=thermal_binding[2],
                    source_ref=thermal_binding[3],
                    semantics=thermal_binding[1],
                )
            )
        inactive_mechanisms: list[dict[str, str]] = []
        if alpha_binding is None:
            inactive_mechanisms.append(
                {
                    "mechanism": "DEFOCUS_RECURSION",
                    "status": "INACTIVE",
                    "reason": "no supporting alpha_defocus prior or calibration evidence",
                }
            )
        if thermal_binding is None:
            inactive_mechanisms.append(
                {
                    "mechanism": "THERMAL_MEMORY",
                    "status": "INACTIVE",
                    "reason": "no supporting thermal prior or calibration evidence",
                }
            )
        return self._build(
            mode=RemovalModelMode.RECONSTRUCTED,
            kernel=kernel,
            threshold=threshold,
            incubation=incubation,
            delta=max(delta, 1e-6),
            alpha=alpha_binding[0] if alpha_binding else 0.0,
            thermal=thermal_binding[0] if thermal_binding else 0.0,
            semantics={
                "F_th_eff": threshold_semantics,
                "incubation_S": incubation_semantics,
                "delta_eff": delta_semantics,
                "alpha_defocus": alpha_binding[1] if alpha_binding else ParameterSemantics.PROVISIONAL,
                "thermal_memory_eff": (
                    thermal_binding[1] if thermal_binding else ParameterSemantics.PROVISIONAL
                ),
            },
            bindings=bindings,
            inactive_mechanisms=inactive_mechanisms,
            status=ScientificStatus.PARTIAL,
            refs=refs,
            assumptions=[
                (
                    "critical parameters are bound from calibration or priors; "
                    "unresolved optional mechanisms are INACTIVE, never defaulted"
                ),
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
        kernel = (
            empirical_kernel
            if isinstance(empirical_kernel, RemovalKernel)
            else RemovalKernel.model_validate(empirical_kernel)
        )
        reconstructed = self.reconstructed(
            calibration=calibration,
            parameter_priors=parameter_priors,
            mechanism_priors=mechanism_priors,
            beam_radius_um=float(kernel.radius_um),
            allow_computational_defaults=False,
            input_refs=input_refs,
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
            bindings=reconstructed.parameter_bindings,
            inactive_mechanisms=reconstructed.inactive_mechanisms,
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
        bindings: list[ParameterBinding] | None = None,
        inactive_mechanisms: list[dict[str, str]] | None = None,
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
            parameter_bindings=list(bindings or []),
            inactive_mechanisms=list(inactive_mechanisms or []),
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
