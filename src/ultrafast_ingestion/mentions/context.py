"""Context classification for mentions (F3).

Decides acceptance_status and context_class from the text window around
a mention. Does NOT decide condition membership (linking is out of scope).
"""

from __future__ import annotations

import re

from ultrafast_ingestion.mentions.models import (
    AcceptanceStatus,
    ContextClass,
)
from ultrafast_ingestion.mentions.units import infer_parameter

_MODEL_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9+()]+)+")

_CAPABILITY_WORDS = (
    "up to", "can reach", "capability", "capable",
    "rated", "maximum pulse energy", "maximum power",
    "maximum repetition rate",
)
_EMISSION_WORDS = (
    "emission", "zpl", "zero phonon", "zero-phonon", "peak", "peaks",
    "fluorescence line", "detected at", "luminescence", "emitters",
    "pl1", "pl2", "pl3", "pl4", "pl5", "pl6", "pl7", "resonance line",
    "on-axis", "off-axis", "c-axis", "basal plane", "zpls",
    "divacanc", "defect", "colour centre", "color center", "colour centers",
    "colour centres", "color centers", "center", "centre", "ensemble",
)
_MEASUREMENT_WORDS = (
    "excitation", "excite", "detector", "spectrometer", "dichroic",
    "longpass", "shortpass", "filter", "objective", "confocal",
    "photodiode", "apd", "snspd", "camera",
)
_NON_PROCESS_EQUIPMENT_WORDS = (
    "amplifier", "amplified", "microwave", "signal generator", "copper wire",
    "counter", "correlator", "timeharp", "whiteLase".lower(), "supercontinuum",
)
_SPIN_FREQUENCY_WORDS = (
    "zero field splitting", "odmr", "rabi", "ramsey", "spin echo", "spin coherence",
    "microwave sequence", "splitting", "resonance frequency",
)
_LASER_WORDS = ("laser", "laser beam", "wavelength", "pulse", "repetition rate",
                "energy", "fluence", "power", "fluence ", "scanning speed",
                "repetition", "polarization", "polarized")


def _is_inside_model_token(text: str, start: int, end: int) -> bool:
    """True if the mention is embedded in a hyphenated alphanumeric token
    (e.g. ZHL-25W-272+, SSG-6000)."""
    token = _MODEL_TOKEN_RE.search(text, max(0, start - 8), end + 8)
    return token is not None and token.start() < start and token.end() > end


def _nearest(text: str, pos: int, words: tuple[str, ...]) -> int | None:
    best: int | None = None
    for w in words:
        i = text.find(w)
        while i != -1:
            d = abs(i - pos)
            if best is None or d < best:
                best = d
            i = text.find(w, i + 1)
    return best


def classify(
    raw_text: str,
    unit: str,
    start: int,
    end: int,
    *,
    window: str = "",
    parameter_hint: str = "",
) -> tuple[AcceptanceStatus, ContextClass, str, str]:
    """Return (status, context_class, parameter, rejection_reason)."""
    lower = window.lower()
    param = parameter_hint or infer_parameter(unit, window, start)

    # F3 hard rules -------------------------------------------------------
    if _is_inside_model_token(window, start, end) or any(
        w in lower for w in _NON_PROCESS_EQUIPMENT_WORDS
    ) and param == "average_power":
        return (
            AcceptanceStatus.REJECTED_CONTEXT,
            ContextClass.EQUIPMENT_MODEL,
            param,
            "equipment model / non-process power",
        )

    if param in ("frequency", "na", "m2") and any(w in lower for w in _SPIN_FREQUENCY_WORDS):
        return (
            AcceptanceStatus.REJECTED_CONTEXT,
            ContextClass.EQUIPMENT_MODEL,
            param,
            "ODMR/spin resonance frequency, not laser parameter",
        )

    if param == "wavelength" and any(w in lower for w in _EMISSION_WORDS):
        # reject when the nearest keyword to the mention is an emission word
        # (e.g. "PL6 divacancies (1038 nm)"); keep when the nearest is the
        # laser itself (e.g. "515 nm laser")
        d_em = _nearest(lower, start, _EMISSION_WORDS)
        d_laser = _nearest(lower, start, ("laser",))
        if d_em is not None and (d_laser is None or d_em < d_laser):
            return (
                AcceptanceStatus.REJECTED_CONTEXT,
                ContextClass.EMISSION_WAVELENGTH,
                param,
                "emission/ZPL wavelength, not laser parameter",
            )

    cap_dist = _nearest(lower, start, _CAPABILITY_WORDS)
    if cap_dist is not None and cap_dist <= 60:
        return (
            AcceptanceStatus.AMBIGUOUS_CONTEXT,
            ContextClass.CAPABILITY_SPEC,
            param,
            "capability/system spec, usage unconfirmed",
        )

    if any(w in lower for w in _MEASUREMENT_WORDS) and not any(
        w in lower for w in _LASER_WORDS
    ):
        return (
            AcceptanceStatus.ACCEPTED,
            ContextClass.MEASUREMENT_OPTICS,
            param,
            "",
        )

    if any(w in lower for w in _LASER_WORDS):
        return (AcceptanceStatus.ACCEPTED, ContextClass.PROCESS_CONTEXT, param, "")

    return (AcceptanceStatus.ACCEPTED, ContextClass.UNCLEAR, param, "")
