"""One deterministic physics transform for literature and target machine states."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from packages.scientific_computation.contracts import (
    ArtifactRef,
    AvailabilityStatus,
    CanonicalPhysicsState,
    PhysicsQuantity,
    ProvenanceRecord,
    ScientificStatus,
)


def _stable_id(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"canonical-physics-{hashlib.sha256(raw).hexdigest()[:16]}"


class PhysicsCanonicalizer:
    """Convert verified raw settings to comparable mechanism coordinates."""

    REQUIRED = (
        "average_power_W",
        "frequency_kHz",
        "pulse_width_ps",
        "scan_speed_mm_s",
        "hatch_spacing_um",
        "beam_radius_um",
        "passes",
    )

    def canonicalize(
        self,
        inputs: dict[str, float | int | None],
        *,
        input_refs: list[ArtifactRef] | None = None,
        verified_inputs: set[str] | None = None,
    ) -> CanonicalPhysicsState:
        values = dict(inputs)
        if values.get("average_power_W") is None:
            values["average_power_W"] = values.get("actual_power_W")
        if values.get("beam_radius_um") is None:
            values["beam_radius_um"] = values.get("spot_radius_um")
        missing = [name for name in self.REQUIRED if values.get(name) is None]
        verified = set(verified_inputs or ())

        def availability(*names: str) -> AvailabilityStatus:
            return (
                AvailabilityStatus.AVAILABLE
                if all(name in verified for name in names)
                else AvailabilityStatus.UNVERIFIED
            )

        quantities: dict[str, PhysicsQuantity] = {}
        power = values.get("average_power_W")
        frequency = values.get("frequency_kHz")
        speed = values.get("scan_speed_mm_s")
        radius = values.get("beam_radius_um")
        passes = values.get("passes")
        threshold_key = "F_th_J_cm2" if values.get("F_th_J_cm2") is not None else "F_th_eff_J_cm2"
        threshold = values.get(threshold_key)

        if power is not None and frequency is not None and float(frequency) > 0:
            pulse_energy_j = float(power) / (float(frequency) * 1000.0)
            quantities["pulse_energy"] = PhysicsQuantity(
                value=pulse_energy_j * 1e6,
                unit="uJ",
                status=availability("average_power_W", "frequency_kHz"),
            )
            if radius is not None and float(radius) > 0:
                radius_cm = float(radius) * 1e-4
                peak_fluence = 2.0 * pulse_energy_j / (math.pi * radius_cm**2)
                quantities["peak_fluence"] = PhysicsQuantity(
                    value=peak_fluence,
                    unit="J/cm2",
                    status=availability("average_power_W", "frequency_kHz", "beam_radius_um"),
                )
                if threshold is not None and float(threshold) > 0:
                    quantities["normalized_fluence"] = PhysicsQuantity(
                        value=peak_fluence / float(threshold),
                        unit="dimensionless",
                        status=availability(
                            "average_power_W",
                            "frequency_kHz",
                            "beam_radius_um",
                            threshold_key,
                        ),
                    )
        if speed is not None and frequency is not None and float(frequency) > 0:
            pulse_spacing = float(speed) / float(frequency)
            quantities["pulse_spacing"] = PhysicsQuantity(
                value=pulse_spacing,
                unit="um",
                status=availability("scan_speed_mm_s", "frequency_kHz"),
            )
            if radius is not None and float(radius) > 0:
                effective_pulses = max(0.0, 2.0 * float(radius) / pulse_spacing)
                if passes is not None:
                    effective_pulses *= float(passes)
                quantities["effective_pulses"] = PhysicsQuantity(
                    value=effective_pulses,
                    unit="count",
                    status=availability(
                        "scan_speed_mm_s", "frequency_kHz", "beam_radius_um", "passes"
                    ),
                )
                quantities["pulse_overlap"] = PhysicsQuantity(
                    value=max(0.0, min(1.0, 1.0 - pulse_spacing / (2.0 * float(radius)))),
                    unit="fraction",
                    status=availability("scan_speed_mm_s", "frequency_kHz", "beam_radius_um"),
                )
        if "peak_fluence" in quantities and "effective_pulses" in quantities:
            quantities["accumulated_fluence_proxy"] = PhysicsQuantity(
                value=(quantities["peak_fluence"].value * quantities["effective_pulses"].value),
                unit="J/cm2",
                status=(
                    AvailabilityStatus.AVAILABLE
                    if quantities["peak_fluence"].status == AvailabilityStatus.AVAILABLE
                    and quantities["effective_pulses"].status == AvailabilityStatus.AVAILABLE
                    else AvailabilityStatus.UNVERIFIED
                ),
            )
        payload = {
            "inputs": values,
            "verified": sorted(verified),
            "quantities": {
                name: value.model_dump(mode="json") for name, value in quantities.items()
            },
        }
        return CanonicalPhysicsState(
            state_id=_stable_id(payload),
            input_refs=list(input_refs or []),
            quantities=quantities,
            missing_inputs=missing,
            status=(
                ScientificStatus.KNOWN
                if quantities
                and all(item.status == AvailabilityStatus.AVAILABLE for item in quantities.values())
                and not missing
                else ScientificStatus.PARTIAL
                if quantities
                else ScientificStatus.UNKNOWN
            ),
            provenance=[
                ProvenanceRecord(
                    source_type="DETERMINISTIC_COMPUTATION",
                    source_ref="PhysicsCanonicalizer:v1",
                    role="shared_source_target_transform",
                )
            ],
        )
