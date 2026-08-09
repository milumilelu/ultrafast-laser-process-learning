"""Canonical equipment resource contract (M1).

MachineProfileSnapshot is the single resource identity consumed by every
downstream scientific computation.  All physics stages read this snapshot
only - they never read raw task_spec injection or device_properties dicts.

Source qualities:
- RESEARCH_AGENT : resolved from the agent equipment archive (HTTP).
- DEMO_FIXTURE   : resolved from the pre-installed fixture store (same shape).
- TASK_OVERRIDE  : resolved from task_spec.machine_profile - allowed only in
                   SANDBOX execution mode, every product is provisional.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

EQUIPMENT_SCHEMA_VERSION = "machine-profile-snapshot-v1"

FieldStatus = Literal["VERIFIED", "DERIVED", "UNVERIFIED", "MISSING"]
FieldVerification = Literal[
    "REPOSITORY_VERIFIED",
    "MEASURED",
    "MANUFACTURER_SPEC",
    "ESTIMATED",
    "DEMO_FIXTURE_DECLARED",
    "DERIVED_FROM_VERIFIED_INPUT",
    "UNVERIFIED",
    "MISSING",
]
SourceQuality = Literal[
    "RESEARCH_AGENT",
    "DEMO_FIXTURE",
    "TASK_OVERRIDE",
    "UNRESOLVED",
]
ResourceStatus = Literal["READY", "PARTIAL", "BLOCKED"]

# canonical physics fields with their units (order defines canonical key set)
CANONICAL_EQUIPMENT_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("wavelength_nm", "nm"),
    ("workpiece_incident_power_min_W", "W"),
    ("workpiece_incident_power_max_W", "W"),
    ("beam_radius_um", "um"),
    ("pulse_width_min_fs", "fs"),
    ("pulse_width_max_fs", "fs"),
    ("frequency_min_kHz", "kHz"),
    ("frequency_max_kHz", "kHz"),
    ("scan_speed_min_mm_s", "mm/s"),
    ("scan_speed_max_mm_s", "mm/s"),
)

# fields the physics chain cannot compute without (Gate A)
REQUIRED_PHYSICS_FIELDS = (
    "wavelength_nm",
    "workpiece_incident_power_min_W",
    "workpiece_incident_power_max_W",
    "beam_radius_um",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EquipmentFieldState(BaseModel):
    parameter: str
    value: float | None = None
    unit: str | None = None
    status: FieldStatus = "MISSING"
    verification_status: FieldVerification = "MISSING"
    provenance: list[str] = Field(default_factory=list)


class MachineProfileSnapshot(BaseModel):
    schema_version: str = EQUIPMENT_SCHEMA_VERSION
    equipment_profile_id: str
    revision_id: str | None = None
    source_quality: SourceQuality
    fields: dict[str, EquipmentFieldState] = Field(default_factory=dict)
    machine_bounds: dict[str, dict[str, float]] = Field(default_factory=dict)
    resource_status: ResourceStatus = "BLOCKED"
    missing_required: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)

    def value(self, parameter: str) -> float | None:
        state = self.fields.get(parameter)
        return state.value if state else None

    def present_values(self) -> dict[str, float]:
        return {
            name: state.value
            for name, state in self.fields.items()
            if state.value is not None
        }

    def verified_values(self) -> dict[str, float]:
        return {
            name: state.value
            for name, state in self.fields.items()
            if state.value is not None and state.status != "MISSING"
        }


def build_blocked_snapshot(
    equipment_profile_id: str, reason: str
) -> MachineProfileSnapshot:
    """Fail-closed snapshot: nothing resolved, resource BLOCKED."""
    fields = {
        name: EquipmentFieldState(
            parameter=name, unit=unit, status="MISSING", provenance=[reason]
        )
        for name, unit in CANONICAL_EQUIPMENT_FIELDS
    }
    return MachineProfileSnapshot(
        equipment_profile_id=equipment_profile_id,
        source_quality="UNRESOLVED",
        fields=fields,
        resource_status="BLOCKED",
        missing_required=list(REQUIRED_PHYSICS_FIELDS),
        warnings=[reason],
    )


def _finish_snapshot(
    snapshot: MachineProfileSnapshot,
    *,
    explicit_warnings: list[str] | None = None,
) -> MachineProfileSnapshot:
    """Derive resource_status and missing_required from field states."""
    missing = [
        name
        for name in REQUIRED_PHYSICS_FIELDS
        if snapshot.fields.get(name) is None
        or snapshot.fields[name].status in {"MISSING", "UNVERIFIED"}
        or snapshot.fields[name].value is None
    ]
    present = {
        name
        for name, state in snapshot.fields.items()
        if state.value is not None
    }
    if missing:
        snapshot.missing_required = missing
        snapshot.resource_status = "PARTIAL" if present else "BLOCKED"
        snapshot.warnings = list(explicit_warnings or [])
        snapshot.warnings.append(
            f"missing required physics fields: {', '.join(missing)}"
        )
    else:
        snapshot.missing_required = []
        snapshot.resource_status = "READY"
        snapshot.warnings = list(explicit_warnings or [])
    return snapshot


def snapshot_from_profile(
    profile: dict[str, Any], *, source_quality: SourceQuality
) -> MachineProfileSnapshot:
    """Build the canonical snapshot from an equipment profile dict.

    Both the agent archive (RESEARCH_AGENT) and the fixture store
    (DEMO_FIXTURE) produce the same profile shape:
    {equipment_profile_id, revision_id, laser_source{}, optical_setup{},
     motion_system{}, process_capability{}}.
    """
    laser = profile.get("laser_source") or {}
    optical = profile.get("optical_setup") or {}
    motion = profile.get("motion_system") or {}
    provenance_root = f"equipment_profile:{profile.get('equipment_profile_id')}"
    if source_quality == "RESEARCH_AGENT":
        provenance = [
            provenance_root,
            f"revision:{profile.get('revision_id') or 'latest'}",
        ]
    else:
        provenance = [provenance_root, f"source:{source_quality}"]

    def field_state(
        parameter: str,
        value: float | None,
        unit: str | None,
        *,
        derived: bool = False,
        verification_key: str | None = None,
        note: list[str] | None = None,
    ) -> EquipmentFieldState:
        verification_map = profile.get("field_verification") or {}
        verification_value = verification_map.get(verification_key or parameter, False)
        raw_verification = (
            str(verification_value.get("status") or "").upper()
            if isinstance(verification_value, dict)
            else "VERIFIED"
            if verification_value is True
            else str(verification_value or "").upper()
        )
        explicitly_verified = (
            raw_verification
            in {"VERIFIED", "MEASURED", "MANUFACTURER_SPEC", "APPROVED"}
        )
        if source_quality == "DEMO_FIXTURE":
            status: FieldStatus = "DERIVED" if derived else (
                "VERIFIED" if value is not None else "MISSING"
            )
            verification_status: FieldVerification = (
                "DERIVED_FROM_VERIFIED_INPUT"
                if derived and value is not None
                else "DEMO_FIXTURE_DECLARED"
                if value is not None
                else "MISSING"
            )
        elif derived and value is not None and explicitly_verified:
            status = "DERIVED"
            verification_status = "DERIVED_FROM_VERIFIED_INPUT"
        elif value is not None and explicitly_verified:
            status = "VERIFIED"
            verification_status = (
                raw_verification
                if raw_verification in {"MEASURED", "MANUFACTURER_SPEC"}
                else "REPOSITORY_VERIFIED"
            )
        elif value is not None:
            status = "UNVERIFIED"
            verification_status = (
                "ESTIMATED" if raw_verification == "ESTIMATED" else "UNVERIFIED"
            )
        else:
            status = "MISSING"
            verification_status = "MISSING"
        return EquipmentFieldState(
            parameter=parameter,
            value=value,
            unit=unit,
            status=status,
            verification_status=verification_status,
            provenance=[*(provenance if value is not None else []), *(note or [])],
        )

    spot_diameter = optical.get("spot_diameter_um")
    explicit_beam_radius = optical.get("beam_radius_um")
    beam_radius = (
        float(explicit_beam_radius)
        if explicit_beam_radius is not None
        else float(spot_diameter) / 2.0
        if spot_diameter is not None
        else None
    )
    beam_is_derived = explicit_beam_radius is None and spot_diameter is not None
    warnings: list[str] = []

    pulse_min = laser.get("pulse_width_min_fs")
    pulse_max = laser.get("pulse_width_max_fs")
    if pulse_min is None and laser.get("pulse_width_fixed_fs") is not None:
        pulse_min = pulse_max = laser.get("pulse_width_fixed_fs")

    fields = {
        "wavelength_nm": field_state(
            "wavelength_nm",
            _as_float(laser.get("wavelength_nm")),
            "nm",
        ),
        "workpiece_incident_power_min_W": field_state(
            "workpiece_incident_power_min_W",
            _as_float(laser.get("workpiece_incident_power_min_W")),
            "W",
        ),
        "workpiece_incident_power_max_W": field_state(
            "workpiece_incident_power_max_W",
            _as_float(laser.get("workpiece_incident_power_max_W")),
            "W",
        ),
        "beam_radius_um": field_state(
            "beam_radius_um",
            beam_radius,
            "um",
            derived=beam_is_derived,
            verification_key=("spot_diameter_um" if beam_is_derived else "beam_radius_um"),
            note=(["derived from spot_diameter_um/2"] if beam_is_derived else []),
        ),
        "pulse_width_min_fs": field_state(
            "pulse_width_min_fs",
            _as_float(pulse_min),
            "fs",
            derived=laser.get("pulse_width_min_fs") is None and pulse_min is not None,
            verification_key=(
                "pulse_width_fixed_fs"
                if laser.get("pulse_width_min_fs") is None
                else "pulse_width_min_fs"
            ),
        ),
        "pulse_width_max_fs": field_state(
            "pulse_width_max_fs",
            _as_float(pulse_max),
            "fs",
            derived=laser.get("pulse_width_max_fs") is None and pulse_max is not None,
            verification_key=(
                "pulse_width_fixed_fs"
                if laser.get("pulse_width_max_fs") is None
                else "pulse_width_max_fs"
            ),
        ),
        "frequency_min_kHz": field_state(
            "frequency_min_kHz", _as_float(laser.get("frequency_min_kHz")), "kHz"
        ),
        "frequency_max_kHz": field_state(
            "frequency_max_kHz", _as_float(laser.get("frequency_max_kHz")), "kHz"
        ),
        "scan_speed_min_mm_s": field_state(
            "scan_speed_min_mm_s",
            _as_float(motion.get("scan_speed_min_mm_s")),
            "mm/s",
        ),
        "scan_speed_max_mm_s": field_state(
            "scan_speed_max_mm_s",
            _as_float(motion.get("scan_speed_max_mm_s")),
            "mm/s",
        ),
    }

    bounds: dict[str, dict[str, float]] = {}
    if fields["frequency_min_kHz"].value is not None and fields[
        "frequency_max_kHz"
    ].value is not None:
        bounds["frequency_kHz"] = {
            "lower": fields["frequency_min_kHz"].value,
            "upper": fields["frequency_max_kHz"].value,
        }
    if fields["scan_speed_min_mm_s"].value is not None and fields[
        "scan_speed_max_mm_s"
    ].value is not None:
        bounds["scan_speed_mm_s"] = {
            "lower": fields["scan_speed_min_mm_s"].value,
            "upper": fields["scan_speed_max_mm_s"].value,
        }
    if fields["pulse_width_min_fs"].value is not None and fields[
        "pulse_width_max_fs"
    ].value is not None:
        bounds["pulse_width_ps"] = {
            "lower": fields["pulse_width_min_fs"].value / 1000.0,
            "upper": fields["pulse_width_max_fs"].value / 1000.0,
        }
    if fields["workpiece_incident_power_min_W"].value is not None and fields[
        "workpiece_incident_power_max_W"
    ].value is not None:
        bounds["laser_power_W"] = {
            "lower": fields["workpiece_incident_power_min_W"].value,
            "upper": fields["workpiece_incident_power_max_W"].value,
        }
    if spot_diameter is not None:
        bounds["spot_diameter_um"] = {
            "lower": float(spot_diameter),
            "upper": float(spot_diameter),
        }
    if beam_radius is not None:
        bounds["beam_radius_um"] = {"lower": beam_radius, "upper": beam_radius}

    snapshot = MachineProfileSnapshot(
        equipment_profile_id=str(profile.get("equipment_profile_id")),
        revision_id=profile.get("revision_id"),
        source_quality=source_quality,
        fields=fields,
        machine_bounds=bounds,
    )
    return _finish_snapshot(snapshot, explicit_warnings=warnings)


def snapshot_from_task_override(
    machine_profile: dict[str, Any],
    *,
    equipment_profile_id: str,
) -> MachineProfileSnapshot:
    """SANDBOX-only: build a provisional snapshot from task_spec injection.

    Every field carries TASK_OVERRIDE provenance and the snapshot is marked
    provisional; no research run may consume it.
    """
    warnings: list[str] = ["SANDBOX task_override machine profile（provisional）"]

    def field_state(
        parameter: str, value: float | None, unit: str | None
    ) -> EquipmentFieldState:
        explicit_verified = bool(machine_profile.get(f"{parameter}_verified", True))
        return EquipmentFieldState(
            parameter=parameter,
            value=value,
            unit=unit,
            status="VERIFIED" if value is not None and explicit_verified else "MISSING",
            verification_status=(
                "REPOSITORY_VERIFIED"
                if value is not None and explicit_verified
                else "MISSING"
            ),
            provenance=["task_override:sandbox"],
        )

    spot_radius = machine_profile.get("beam_radius_um") or machine_profile.get(
        "spot_radius_um"
    )
    fields = {
        "wavelength_nm": field_state(
            "wavelength_nm", _as_float(machine_profile.get("wavelength_nm")), "nm"
        ),
        "workpiece_incident_power_min_W": field_state(
            "workpiece_incident_power_min_W",
            _as_float(machine_profile.get("workpiece_incident_power_min_W")),
            "W",
        ),
        "workpiece_incident_power_max_W": field_state(
            "workpiece_incident_power_max_W",
            _as_float(machine_profile.get("workpiece_incident_power_max_W")),
            "W",
        ),
        "beam_radius_um": field_state(
            "beam_radius_um", _as_float(spot_radius), "um"
        ),
        "pulse_width_min_fs": field_state(
            "pulse_width_min_fs",
            _as_float(machine_profile.get("pulse_width_min_fs")),
            "fs",
        ),
        "pulse_width_max_fs": field_state(
            "pulse_width_max_fs",
            _as_float(machine_profile.get("pulse_width_max_fs")),
            "fs",
        ),
        "frequency_min_kHz": field_state(
            "frequency_min_kHz",
            _as_float(machine_profile.get("frequency_min_kHz")),
            "kHz",
        ),
        "frequency_max_kHz": field_state(
            "frequency_max_kHz",
            _as_float(machine_profile.get("frequency_max_kHz")),
            "kHz",
        ),
        "scan_speed_min_mm_s": field_state(
            "scan_speed_min_mm_s",
            _as_float(machine_profile.get("scan_speed_min_mm_s")),
            "mm/s",
        ),
        "scan_speed_max_mm_s": field_state(
            "scan_speed_max_mm_s",
            _as_float(machine_profile.get("scan_speed_max_mm_s")),
            "mm/s",
        ),
    }
    snapshot = MachineProfileSnapshot(
        equipment_profile_id=equipment_profile_id,
        source_quality="TASK_OVERRIDE",
        fields=fields,
        warnings=warnings,
    )
    return _finish_snapshot(snapshot, explicit_warnings=warnings)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
