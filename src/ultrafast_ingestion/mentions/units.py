"""Unit normalization and parameter inference (Layer 2)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ALIASES: dict[str, str] = {
    "nm": "nm",
    "khz": "kHz",
    "mhz": "MHz",
    "ghz": "GHz",
    "hz": "Hz",
    "ps": "ps",
    "fs": "fs",
    "ns": "ns",
    "w": "W",
    "mw": "mW",
    "mj": "mJ",
    "uj": "uJ",
    "µj": "uJ",
    "nj": "nJ",
    "j/cm2": "J/cm2",
    "j cm-2": "J/cm2",
    "j/cm²": "J/cm2",
    "mm/s": "mm/s",
    "m/s": "m/s",
    "mm s-1": "mm/s",
    "um": "um",
    "µm": "um",
    "μm": "um",
    "mm": "mm",
    "cm": "cm",
    "µm": "um",
}


@dataclass(frozen=True, slots=True)
class UnitSpec:
    aliases: tuple[str, ...]
    canonical: str
    parameter_candidates: tuple[str, ...]  # ordered; first = default


UNIT_SPECS: tuple[UnitSpec, ...] = (
    UnitSpec(("kHz", "khz"), "kHz", ("frequency",)),
    UnitSpec(("MHz", "mhz"), "MHz", ("frequency",)),
    UnitSpec(("GHz", "ghz"), "GHz", ("frequency",)),
    UnitSpec(("Hz", "hz"), "Hz", ("frequency",)),
    UnitSpec(("fs",), "fs", ("pulse_width",)),
    UnitSpec(("ps",), "ps", ("pulse_width",)),
    UnitSpec(("ns",), "ns", ("pulse_width",)),
    UnitSpec(("nm",), "nm", ("wavelength",)),
    UnitSpec(("W", "w"), "W", ("average_power",)),
    UnitSpec(("mW", "mw"), "mW", ("average_power",)),
    UnitSpec(("mJ", "mj"), "mJ", ("pulse_energy",)),
    UnitSpec(("uJ", "uj", "µj"), "uJ", ("pulse_energy",)),
    UnitSpec(("nJ", "nj"), "nJ", ("pulse_energy",)),
    UnitSpec(("J/cm2", "j/cm2", "j cm-2", "j/cm²"), "J/cm2", ("fluence",)),
    UnitSpec(("mm/s", "mm s-1"), "mm/s", ("scan_speed",)),
    UnitSpec(("m/s",), "m/s", ("scan_speed",)),
    UnitSpec(("um", "µm", "μm"), "um", ("length",)),  # spot/hatch/pitch unresolved
    UnitSpec(("mm",), "mm", ("length",)),
    UnitSpec(("cm",), "cm", ("length",)),
)

# canonical -> spec
_CANON_MAP: dict[str, UnitSpec] = {s.canonical: s for s in UNIT_SPECS}

# sorted longest-first for regex alternation
UNIT_PATTERN = re.compile(
    "|".join(re.escape(a) for s in UNIT_SPECS for a in s.aliases),
    re.IGNORECASE,
)


def normalize_unit(raw: str) -> str | None:
    key = raw.strip().lower().replace(" ", "")
    return _ALIASES.get(key)


def spec_for_unit(canonical: str) -> UnitSpec | None:
    return _CANON_MAP.get(canonical)


def infer_parameter(canonical_unit: str, context_window: str) -> str:
    spec = _CANON_MAP.get(canonical_unit)
    if spec is None:
        return "unknown"
    candidates = spec.parameter_candidates
    if len(candidates) == 1:
        return candidates[0]
    # multi-candidate (length): disambiguate by context words
    lower = context_window.lower()
    word_map = {
        "spot": "spot_size",
        "beam": "spot_size",
        "diameter": "spot_size",
        "radius": "spot_size",
        "hatch": "hatch_spacing",
        "pitch": "pitch",
        "spacing": "pitch",
        "distance": "pitch",
        "depth": "depth",
        "defocus": "focus_offset",
    }
    for word, param in word_map.items():
        if word in lower:
            return param
    return "length"
