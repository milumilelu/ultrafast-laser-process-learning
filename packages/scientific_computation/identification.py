"""Bounded deterministic parameter identification with identifiability audit."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from typing import Any, ClassVar

import numpy as np
from scipy.optimize import differential_evolution, least_squares

from packages.process_contracts.prior_objects import ParameterPrior
from packages.scientific_computation.contracts import (
    ArtifactRef,
    CalibrationResult,
    CalibrationStatus,
    EvidenceOrigin,
    FitMetrics,
    IdentifiabilityReport,
    IdentifiabilityStatus,
    ParameterEstimate,
    ParameterIdentifiability,
    ParameterObservation,
    ParameterSemantics,
    ProvenanceRecord,
    ScientificStatus,
)


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:16]}"


def cumulative_ablation_depth(
    peak_fluence_J_cm2: float,
    pulse_count: int,
    F_th_eff: float,
    incubation_S: float,
    delta_eff_um: float,
) -> float:
    """Reduced pulse-recursive logarithmic ablation model."""
    total = 0.0
    for pulse_index in range(1, pulse_count + 1):
        threshold = F_th_eff * pulse_index ** (incubation_S - 1.0)
        if peak_fluence_J_cm2 > threshold:
            total += delta_eff_um * math.log(peak_fluence_J_cm2 / threshold)
    return total


class ParameterIdentificationEngine:
    """Identify F_th_eff/S/delta_eff without claiming unsupported constants."""

    PARAMETER_BOUNDS: ClassVar[dict[str, tuple[float, float, str]]] = {
        "F_th_eff": (0.01, 20.0, "J/cm2"),
        "incubation_S": (0.2, 1.2, "dimensionless"),
        "delta_eff": (0.001, 100.0, "um"),
    }

    def identify(
        self,
        observations: Iterable[ParameterObservation | dict[str, Any]],
        *,
        parameter_priors: Iterable[ParameterPrior | dict[str, Any]] = (),
        requested_parameters: Iterable[str] = (
            "F_th_eff",
            "incubation_S",
            "delta_eff",
            "thermal_diffusivity",
        ),
        random_seed: int = 42,
        input_refs: list[ArtifactRef] | None = None,
    ) -> tuple[IdentifiabilityReport, CalibrationResult]:
        obs = [
            item
            if isinstance(item, ParameterObservation)
            else ParameterObservation.model_validate(item)
            for item in observations
        ]
        refs = list(input_refs or [])
        requested = list(dict.fromkeys(requested_parameters))
        finite_abs = [item for item in obs if item.peak_fluence_J_cm2 is not None]
        unique_fluence = {round(float(item.peak_fluence_J_cm2 or 0.0), 10) for item in finite_abs}
        unique_pulses = {item.pulse_count for item in finite_abs}
        jointly_identifiable = (
            len(finite_abs) == len(obs)
            and len(finite_abs) >= 8
            and len(unique_fluence) >= 3
            and len(unique_pulses) >= 3
        )
        weakly_identifiable = (
            len(finite_abs) == len(obs)
            and len(finite_abs) >= 4
            and len(unique_fluence) >= 2
            and len(unique_pulses) >= 2
        )

        ident_items: list[ParameterIdentifiability] = []
        for name in requested:
            if name == "thermal_diffusivity":
                ident_items.append(
                    ParameterIdentifiability(
                        parameter=name,
                        status=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                        reason_codes=["terminal_depth_has_no_time_resolved_temperature"],
                        required_observations=["time-resolved thermal measurement"],
                    )
                )
            elif name in self.PARAMETER_BOUNDS and jointly_identifiable:
                ident_items.append(
                    ParameterIdentifiability(
                        parameter=name,
                        status=IdentifiabilityStatus.IDENTIFIABLE,
                        reason_codes=["fluence_and_pulse_count_excitation_sufficient"],
                        required_observations=[],
                    )
                )
            elif name in self.PARAMETER_BOUNDS and weakly_identifiable:
                ident_items.append(
                    ParameterIdentifiability(
                        parameter=name,
                        status=IdentifiabilityStatus.WEAKLY_IDENTIFIABLE,
                        reason_codes=["limited_excitation_or_sample_count"],
                        required_observations=["additional fluence and pulse-count levels"],
                    )
                )
            else:
                ident_items.append(
                    ParameterIdentifiability(
                        parameter=name,
                        status=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                        reason_codes=["absolute_fluence_or_excitation_missing"],
                        required_observations=["absolute fluence", "multiple pulse-count levels"],
                    )
                )

        report_payload = {
            "observations": [item.model_dump(mode="json") for item in obs],
            "identifiability": [item.model_dump(mode="json") for item in ident_items],
        }
        ident_report = IdentifiabilityReport(
            report_id=_stable_id("identifiability", report_payload),
            input_refs=refs,
            parameters=ident_items,
            observation_type="pulse_resolved_depth" if finite_abs else "terminal_depth_only",
            status=(
                ScientificStatus.KNOWN
                if jointly_identifiable
                else ScientificStatus.PARTIAL
                if obs
                else ScientificStatus.UNKNOWN
            ),
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="ParameterIdentificationEngine:v1",
                    role="identifiability_assessment",
                )
            ],
        )

        prior_rows = [
            item if isinstance(item, ParameterPrior) else ParameterPrior.model_validate(item)
            for item in parameter_priors
        ]
        status_by_name = {item.parameter: item.status for item in ident_items}
        fit_names = [
            name
            for name in ("F_th_eff", "incubation_S", "delta_eff")
            if name in requested
            and status_by_name.get(name) != IdentifiabilityStatus.NOT_IDENTIFIABLE
        ]
        estimates: list[ParameterEstimate] = []
        predictions = np.zeros(len(obs), dtype=float)

        if len(fit_names) == 3:
            x = np.asarray(
                [[float(item.peak_fluence_J_cm2 or 0.0), float(item.pulse_count)] for item in obs],
                dtype=float,
            )
            y = np.asarray([item.depth_um for item in obs], dtype=float)
            bounds = [self.PARAMETER_BOUNDS[name][:2] for name in fit_names]
            matching_priors = {
                prior.parameter: prior for prior in prior_rows if prior.parameter in fit_names
            }

            def data_residual(theta: np.ndarray) -> np.ndarray:
                values = dict(zip(fit_names, theta, strict=True))
                pred = np.asarray(
                    [
                        cumulative_ablation_depth(
                            peak_fluence_J_cm2=row[0],
                            pulse_count=int(row[1]),
                            F_th_eff=values["F_th_eff"],
                            incubation_S=values["incubation_S"],
                            delta_eff_um=values["delta_eff"],
                        )
                        for row in x
                    ],
                    dtype=float,
                )
                scale = max(float(np.std(y)), 1e-6)
                residual = list((pred - y) / scale)
                # Priors regularize only outside their ranges and remain much
                # weaker than target observations.
                for name, prior in matching_priors.items():
                    value = values[name]
                    width = max(prior.upper - prior.lower, 1e-9)
                    if value < prior.lower:
                        residual.append(0.05 * (value - prior.lower) / width)
                    elif value > prior.upper:
                        residual.append(0.05 * (value - prior.upper) / width)
                return np.asarray(residual, dtype=float)

            def objective(theta: np.ndarray) -> float:
                residual = data_residual(theta)
                return float(np.dot(residual, residual))

            global_fit = differential_evolution(
                objective,
                bounds=bounds,
                seed=random_seed,
                polish=False,
                tol=1e-9,
                updating="immediate",
            )
            local_fit = least_squares(
                data_residual,
                x0=global_fit.x,
                bounds=(np.asarray([b[0] for b in bounds]), np.asarray([b[1] for b in bounds])),
                max_nfev=5000,
            )
            theta = local_fit.x
            values = dict(zip(fit_names, theta, strict=True))
            predictions = np.asarray(
                [
                    cumulative_ablation_depth(
                        float(item.peak_fluence_J_cm2 or 0.0),
                        item.pulse_count,
                        values["F_th_eff"],
                        values["incubation_S"],
                        values["delta_eff"],
                    )
                    for item in obs
                ]
            )
            intervals = self._intervals(local_fit.jac, y, predictions, theta, bounds)
            all_experimental = all(
                item.origin == EvidenceOrigin.EXPERIMENTAL_OBSERVATION for item in obs
            )
            for index, name in enumerate(fit_names):
                prior = matching_priors.get(name)
                estimates.append(
                    ParameterEstimate(
                        parameter=name,
                        estimate=float(theta[index]),
                        lower=float(intervals[index][0]),
                        upper=float(intervals[index][1]),
                        unit=self.PARAMETER_BOUNDS[name][2],
                        identifiability=status_by_name[name],
                        parameter_semantics=(
                            ParameterSemantics.PHYSICAL
                            if all_experimental
                            else ParameterSemantics.PROVISIONAL
                        ),
                        prior_refs=[ArtifactRef(type="ParameterPrior", id=prior.prior_id)]
                        if prior
                        else [],
                        data_refs=[
                            ArtifactRef(type="Observation", id=item.data_ref) for item in obs
                        ],
                        assumptions=["reduced logarithmic ablation with power-law incubation"],
                    )
                )

        for item in ident_items:
            if item.parameter not in {estimate.parameter for estimate in estimates}:
                unit = self.PARAMETER_BOUNDS.get(item.parameter, (0, 0, "m2/s"))[2]
                estimates.append(
                    ParameterEstimate(
                        parameter=item.parameter,
                        estimate=None,
                        unit=unit,
                        identifiability=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                        parameter_semantics=ParameterSemantics.PHYSICAL,
                        data_refs=[
                            ArtifactRef(type="Observation", id=value.data_ref) for value in obs
                        ],
                        assumptions=[
                            "no value emitted because current observations do not identify this parameter"
                        ],
                    )
                )

        y_values = np.asarray([item.depth_um for item in obs], dtype=float)
        if (
            len(y_values)
            and len(predictions) == len(y_values)
            and any(est.estimate is not None for est in estimates)
        ):
            error = predictions - y_values
            rmse = float(np.sqrt(np.mean(error**2)))
            mae = float(np.mean(np.abs(error)))
            denominator = float(np.sum((y_values - np.mean(y_values)) ** 2))
            r2 = 1.0 - float(np.sum(error**2)) / denominator if denominator > 0 else None
        else:
            rmse = mae = 0.0
            r2 = None
        calibration = CalibrationResult(
            calibration_id=_stable_id(
                "calibration",
                {
                    "report": ident_report.report_id,
                    "estimates": [item.model_dump(mode="json") for item in estimates],
                },
            ),
            input_refs=refs
            + [ArtifactRef(type="IdentifiabilityReport", id=ident_report.report_id)],
            parameters=estimates,
            fit_metrics=FitMetrics(
                rmse=rmse, mae=mae, r2=r2, target_unit="um", n_observations=len(obs)
            ),
            status=(
                CalibrationStatus.CALIBRATED
                if any(
                    item.identifiability == IdentifiabilityStatus.IDENTIFIABLE for item in estimates
                )
                else CalibrationStatus.NOT_YET_CALIBRATED
            ),
            validation_data_refs=[],
            assumptions=[
                "fit metrics are in-sample calibration metrics, not independent validation",
                "literature priors regularize but never replace target observations",
            ],
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="ParameterIdentificationEngine:v1",
                    role="bounded_multistart_calibration",
                )
            ],
        )
        return ident_report, calibration

    def identify_from_macro_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        input_refs: list[ArtifactRef] | None = None,
    ) -> tuple[IdentifiabilityReport, CalibrationResult]:
        """Honest fallback for current terminal-depth CSV data.

        Only an effective removal scale is estimated.  Absolute threshold and
        thermal diffusivity remain NOT_IDENTIFIABLE.
        """
        refs = list(input_refs or [])
        depths = np.asarray(
            [float(row["depth_um"]) for row in rows if row.get("depth_um") is not None],
            dtype=float,
        )
        passes = np.asarray(
            [
                max(float(row.get("passes") or 1), 1.0)
                for row in rows
                if row.get("depth_um") is not None
            ],
            dtype=float,
        )
        values = depths / passes if len(depths) else np.asarray([], dtype=float)
        delta = float(np.median(np.abs(values))) if len(values) else None
        low = float(np.quantile(np.abs(values), 0.1)) if len(values) else None
        high = float(np.quantile(np.abs(values), 0.9)) if len(values) else None
        ident = [
            ParameterIdentifiability(
                parameter="F_th_eff",
                status=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                reason_codes=["absolute_power_and_beam_radius_missing"],
                required_observations=["absolute fluence", "crater morphology"],
            ),
            ParameterIdentifiability(
                parameter="incubation_S",
                status=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                reason_codes=["terminal_macro_depth_confounds_overlap_and_incubation"],
                required_observations=["pulse-resolved crater series"],
            ),
            ParameterIdentifiability(
                parameter="delta_eff",
                status=(
                    IdentifiabilityStatus.WEAKLY_IDENTIFIABLE
                    if delta is not None and delta > 0
                    else IdentifiabilityStatus.NOT_IDENTIFIABLE
                ),
                reason_codes=["effective_scale_from_depth_per_pass"],
                required_observations=["local crater profile for physical interpretation"],
            ),
            ParameterIdentifiability(
                parameter="thermal_diffusivity",
                status=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                reason_codes=["terminal_depth_has_no_time_resolved_temperature"],
                required_observations=["time-resolved thermal measurement"],
            ),
            ParameterIdentifiability(
                parameter="thermal_memory_eff",
                status=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                reason_codes=["frequency_effect_confounded_in_terminal_macro_data"],
                required_observations=["controlled repetition-rate morphology series"],
            ),
        ]
        report = IdentifiabilityReport(
            report_id=_stable_id(
                "identifiability",
                {"rows": len(rows), "ident": [item.model_dump(mode="json") for item in ident]},
            ),
            input_refs=refs,
            parameters=ident,
            observation_type="terminal_macro_depth_only",
            status=ScientificStatus.PARTIAL if rows else ScientificStatus.UNKNOWN,
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="ParameterIdentificationEngine:v1",
                    role="macro_identifiability_audit",
                )
            ],
        )
        estimates = [
            ParameterEstimate(
                parameter="F_th_eff",
                unit="J/cm2",
                identifiability=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                parameter_semantics=ParameterSemantics.PHYSICAL,
                data_refs=refs,
                assumptions=["absolute value intentionally withheld"],
            ),
            ParameterEstimate(
                parameter="incubation_S",
                unit="dimensionless",
                identifiability=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                parameter_semantics=ParameterSemantics.PHYSICAL,
                data_refs=refs,
                assumptions=["value intentionally withheld"],
            ),
            ParameterEstimate(
                parameter="delta_eff",
                estimate=delta if delta and delta > 0 else None,
                lower=low if delta and delta > 0 else None,
                upper=high if delta and delta > 0 else None,
                unit="um/pass",
                identifiability=(
                    IdentifiabilityStatus.WEAKLY_IDENTIFIABLE
                    if delta and delta > 0
                    else IdentifiabilityStatus.NOT_IDENTIFIABLE
                ),
                parameter_semantics=ParameterSemantics.EFFECTIVE,
                data_refs=refs,
                assumptions=["macro terminal depth per pass; not a physical penetration depth"],
            ),
            ParameterEstimate(
                parameter="thermal_diffusivity",
                unit="m2/s",
                identifiability=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                parameter_semantics=ParameterSemantics.PHYSICAL,
                data_refs=refs,
                assumptions=["value intentionally withheld"],
            ),
            ParameterEstimate(
                parameter="thermal_memory_eff",
                unit="dimensionless",
                identifiability=IdentifiabilityStatus.NOT_IDENTIFIABLE,
                parameter_semantics=ParameterSemantics.EFFECTIVE,
                data_refs=refs,
                assumptions=["value intentionally withheld"],
            ),
        ]
        fit_rmse = float(np.std(depths)) if len(depths) else 0.0
        calibration = CalibrationResult(
            calibration_id=_stable_id("calibration", {"report": report.report_id, "delta": delta}),
            input_refs=refs + [ArtifactRef(type="IdentifiabilityReport", id=report.report_id)],
            parameters=estimates,
            fit_metrics=FitMetrics(
                rmse=fit_rmse,
                mae=float(np.mean(np.abs(depths - np.median(depths)))) if len(depths) else 0.0,
                r2=None,
                target_unit="um",
                n_observations=len(depths),
            ),
            status=CalibrationStatus.NOT_YET_CALIBRATED,
            validation_data_refs=[],
            assumptions=[
                "terminal macro data supports effective calibration only",
                "negative reference-surface values are preserved",
            ],
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="ParameterIdentificationEngine:v1",
                    role="effective_macro_calibration",
                )
            ],
        )
        return report, calibration

    @staticmethod
    def _intervals(
        jacobian: np.ndarray,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        theta: np.ndarray,
        bounds: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        try:
            dof = max(len(y_true) - len(theta), 1)
            variance = float(np.sum((y_true - y_pred) ** 2) / dof)
            covariance = np.linalg.pinv(jacobian.T @ jacobian) * variance
            standard = np.sqrt(np.maximum(np.diag(covariance), 0))
        except (ValueError, np.linalg.LinAlgError):
            standard = np.maximum(np.abs(theta) * 0.1, 1e-9)
        intervals = []
        for value, sigma, bound in zip(theta, standard, bounds, strict=True):
            width = max(float(1.96 * sigma), abs(float(value)) * 0.01, 1e-9)
            intervals.append(
                (max(bound[0], float(value) - width), min(bound[1], float(value) + width))
            )
        return intervals
