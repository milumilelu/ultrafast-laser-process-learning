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
    "kj/cm2": "kJ/cm2",
    "kj/cm²": "kJ/cm2",
    "mm/s": "mm/s",
    "m/s": "m/s",
    "mm s-1": "mm/s",
    "um": "um",
    "µm": "um",
    "μm": "um",
    "mm": "mm",
    "cm": "cm",
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
    UnitSpec(("kJ/cm2", "kj/cm2", "kj/cm²"), "kJ/cm2", ("accumulated_dose",)),
    UnitSpec(("mm/s", "mm s-1"), "mm/s", ("scan_speed",)),
    UnitSpec(("m/s",), "m/s", ("scan_speed",)),
    UnitSpec(("um", "µm", "μm"), "um", ("length",)),  # spot/hatch/pitch unresolved
    UnitSpec(("mm",), "mm", ("length",)),
    UnitSpec(("cm",), "cm", ("length",)),
    # dimensionless sentinels (patterns.py)
    UnitSpec(("NA", "na"), "NA", ("na",)),
    UnitSpec(("M2", "m2", "M²"), "M2", ("m2",)),
    UnitSpec(("MAG", "mag"), "MAG", ("magnification",)),
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
    if key in {"na"}:
        return "NA"
    if key in {"m2", "m²"}:
        return "M2"
    if key in {"mag", "x", "×"}:
        return "MAG"
    return _ALIASES.get(key)


def spec_for_unit(canonical: str) -> UnitSpec | None:
    return _CANON_MAP.get(canonical)


def infer_parameter(canonical_unit: str, context_window: str, pos: int = 0) -> str:
    """Context-disambiguated parameter inference.

    For ambiguous units (length), picks the NEAREST context word mapping
    to a parameter (e.g. '5 um apart' -> pitch, '2 um depths' -> depth).
    Falls back to the unit's canonical candidate.
    """
    spec = _CANON_MAP.get(canonical_unit)
    if spec is None:
        return "unknown"
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
        "apart": "pitch",
        "depth": "depth",
        "defocus": "focus_offset",
    }
    best: tuple[int, str] | None = None
    if spec.parameter_candidates[0] == "length":
        # word-map disambiguation only for length-family units
        for word, param in word_map.items():
            i = lower.find(word)
            while i != -1:
                d = abs(i - pos)
                if best is None or d < best[0]:
                    best = (d, param)
                i = lower.find(word, i + 1)
    if best is not None:
        return best[1]
    return spec.parameter_candidates[0]


# parameter-table label mapping: "Spot diameter (um) 19" -> spot_size
LABEL_PARAM_MAP: dict[str, str] = {
    "wavelength": "wavelength",
    "pulse width": "pulse_width",
    "pulse duration": "pulse_width",
    "pulse repetition rate": "frequency",
    "repetition rate": "frequency",
    "frequency": "frequency",
    "average power": "average_power",
    "power": "average_power",
    "pulse energy": "pulse_energy",
    "fluence": "fluence",
    "fluence range": "fluence",
    "spot diameter": "spot_size",
    "spot size": "spot_size",
    "beam diameter": "spot_size",
    "scanning speed": "scan_speed",
    "scan speed": "scan_speed",
    "speed": "scan_speed",
    "hatch spacing": "hatch_spacing",
    "passes": "passes",
    "depth": "depth",
}


def parameter_from_label(label: str) -> str:
    lower = label.strip().lower()
    for key, param in LABEL_PARAM_MAP.items():
        if key in lower:
            return param
    return "unknown"
