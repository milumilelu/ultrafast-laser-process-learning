from __future__ import annotations

from typing import Any

NON_NEGATIVE_FIELDS = {
    "wavelength_nm",
    "pulse_width_min_fs",
    "pulse_width_max_fs",
    "pulse_width_fixed_fs",
    "average_power_min_W",
    "average_power_max_W",
    "rated_max_power_W",
    "measured_max_power_W",
    "power_transmission_ratio",
    "actual_max_power_W",
    "workpiece_incident_power_min_W",
    "workpiece_incident_power_max_W",
    "frequency_min_kHz",
    "frequency_max_kHz",
    "pulse_energy_max_uJ",
    "beam_quality_M2",
    "objective_NA",
    "focal_length_mm",
    "spot_diameter_um",
    "working_distance_mm",
    "galvo_max_speed_mm_s",
    "stage_max_speed_mm_s",
    "scan_speed_min_mm_s",
    "scan_speed_max_mm_s",
    "positioning_accuracy_um",
    "repeatability_um",
    "work_area_x_mm",
    "work_area_y_mm",
    "work_area_z_mm",
    "passes_min",
    "passes_max",
    "hatch_spacing_min_um",
    "hatch_spacing_max_um",
    "layer_step_min_um",
    "layer_step_max_um",
}

RANGE_PAIRS = (
    ("pulse_width_min_fs", "pulse_width_max_fs"),
    ("average_power_min_W", "average_power_max_W"),
    ("workpiece_incident_power_min_W", "workpiece_incident_power_max_W"),
    ("frequency_min_kHz", "frequency_max_kHz"),
    ("focus_offset_min_um", "focus_offset_max_um"),
    ("scan_speed_min_mm_s", "scan_speed_max_mm_s"),
    ("passes_min", "passes_max"),
    ("hatch_spacing_min_um", "hatch_spacing_max_um"),
    ("layer_step_min_um", "layer_step_max_um"),
)


def validate_equipment_payload(
    laser_source: dict[str, Any] | None = None,
    optical_setup: dict[str, Any] | None = None,
    motion_system: dict[str, Any] | None = None,
    process_capability: dict[str, Any] | None = None,
    field_verification: dict[str, str] | None = None,
    require_active_minimum: bool = False,
) -> None:
    sections = [
        laser_source or {},
        optical_setup or {},
        motion_system or {},
        process_capability or {},
    ]
    merged: dict[str, Any] = {}
    for section in sections:
        merged.update(section)
        for key, value in section.items():
            if key in NON_NEGATIVE_FIELDS and value is not None and float(value) < 0:
                raise ValueError(f"{key} cannot be negative")
    for lower_key, upper_key in RANGE_PAIRS:
        lower = merged.get(lower_key)
        upper = merged.get(upper_key)
        if lower is not None and upper is not None and float(lower) > float(upper):
            raise ValueError(f"{lower_key} cannot be greater than {upper_key}")
    fixed = merged.get("pulse_width_fixed_fs")
    min_width = merged.get("pulse_width_min_fs")
    max_width = merged.get("pulse_width_max_fs")
    if (
        fixed is not None
        and min_width is not None
        and max_width is not None
        and (float(fixed) < float(min_width) or float(fixed) > float(max_width))
    ):
        raise ValueError("pulse_width_fixed_fs conflicts with pulse_width_min/max_fs")
    transmission = merged.get("power_transmission_ratio")
    if transmission is not None and not 0 < float(transmission) <= 1:
        raise ValueError("power_transmission_ratio must be in (0, 1]")
    verification = field_verification or {}
    missing_provenance = sorted(
        key
        for key, value in merged.items()
        if key in NON_NEGATIVE_FIELDS and value is not None and not verification.get(key)
    )
    if missing_provenance:
        raise ValueError(
            "equipment physical fields missing field verification: " + ", ".join(missing_provenance)
        )
    if require_active_minimum:
        pulse_available = (laser_source or {}).get("pulse_width_fixed_fs") is not None or (
            (laser_source or {}).get("pulse_width_min_fs") is not None
            and (laser_source or {}).get("pulse_width_max_fs") is not None
        )
        required = {
            "rated_max_power_W": laser_source or {},
            "frequency_min_kHz": laser_source or {},
            "frequency_max_kHz": laser_source or {},
            "scan_speed_min_mm_s": motion_system or {},
            "scan_speed_max_mm_s": motion_system or {},
        }
        missing = [key for key, section in required.items() if section.get(key) is None]
        if not pulse_available:
            missing.append("pulse_width_fs")
        if missing:
            raise ValueError(
                "active equipment profile missing required fields: " + ", ".join(missing)
            )

        positive_fields = {
            "rated_max_power_W": (laser_source or {}).get("rated_max_power_W"),
            "frequency_max_kHz": (laser_source or {}).get("frequency_max_kHz"),
            "scan_speed_max_mm_s": (motion_system or {}).get("scan_speed_max_mm_s"),
        }
        non_positive = [key for key, value in positive_fields.items() if float(value) <= 0]
        if non_positive:
            raise ValueError(
                "active equipment profile fields must be positive: " + ", ".join(non_positive)
            )
        verification_keys = [
            "rated_max_power_W",
            "frequency_min_kHz",
            "frequency_max_kHz",
            "scan_speed_min_mm_s",
            "scan_speed_max_mm_s",
        ]
        if (laser_source or {}).get("pulse_width_fixed_fs") is not None:
            verification_keys.append("pulse_width_fixed_fs")
        else:
            verification_keys.extend(["pulse_width_min_fs", "pulse_width_max_fs"])
        missing_verification = [key for key in verification_keys if not verification.get(key)]
        if missing_verification:
            raise ValueError(
                "active equipment profile missing field verification: "
                + ", ".join(missing_verification)
            )
        measured_power = (laser_source or {}).get("measured_max_power_W")
        if (
            measured_power is not None
            and str(verification.get("measured_max_power_W") or "").upper() != "MEASURED"
        ):
            raise ValueError("measured_max_power_W requires MEASURED field verification")


def validate_override_within_bounds(
    machine_bounds: dict[str, list[float | int]],
    override: dict[str, list[float | int]],
    reason: str | None,
) -> dict[str, Any]:
    if not reason:
        raise ValueError("override_reason is required")
    for key, value in override.items():
        if key not in machine_bounds:
            raise ValueError(f"{key} is not available in active machine_bounds")
        if len(value) != 2:
            raise ValueError(f"{key} override must be [min, max]")
        lower, upper = float(value[0]), float(value[1])
        physical_lower, physical_upper = (
            float(machine_bounds[key][0]),
            float(machine_bounds[key][1]),
        )
        if lower < physical_lower or upper > physical_upper:
            raise ValueError(f"{key} override exceeds physical machine bounds")
        if lower > upper:
            raise ValueError(f"{key} override min cannot exceed max")
    merged = {**machine_bounds, **override}
    return {
        "machine_bounds": merged,
        "audit_trace": [
            {"step": "task_level_machine_bounds_override", "status": "applied", "reason": reason}
        ],
    }
