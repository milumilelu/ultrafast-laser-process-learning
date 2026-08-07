"""Data profile calculation based on independent parameter designs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from packages.process_contracts.schemas import CORE_PARAMETER_NAMES, DataProfile

from .versioning import canonical_hash


def ensure_parameter_combination_id(row: Mapping[str, Any]) -> str:
    explicit = row.get("parameter_combination_id")
    if explicit:
        return str(explicit)
    parameters = row.get("parameters", row)
    values = {name: parameters.get(name) for name in CORE_PARAMETER_NAMES}
    return f"pc-{canonical_hash(values)[:16]}"


def build_data_profile(rows: Sequence[Mapping[str, Any]]) -> DataProfile:
    if not rows:
        return DataProfile(
            n_samples=0,
            n_unique_designs=0,
            n_features=len(CORE_PARAMETER_NAMES),
            replicate_ratio=0,
            missing_rate=0,
            batch_count=0,
            equipment_count=0,
            coverage_score=None,
        )
    flat = []
    for row in rows:
        params = row.get("parameters", row)
        scope = row.get("scope", row)
        flat.append(
            {
                **{name: params.get(name) for name in CORE_PARAMETER_NAMES},
                "parameter_combination_id": ensure_parameter_combination_id(row),
                "experiment_batch_id": row.get("experiment_batch_id"),
                "equipment_id": scope.get("equipment_id"),
            }
        )
    frame = pd.DataFrame(flat)
    n_samples = len(frame)
    n_unique = int(frame["parameter_combination_id"].nunique(dropna=True))
    missing_rate = float(frame[list(CORE_PARAMETER_NAMES)].isna().mean().mean())
    populated_features = sum(frame[name].notna().any() for name in CORE_PARAMETER_NAMES)
    return DataProfile(
        n_samples=n_samples,
        n_unique_designs=n_unique,
        n_features=int(populated_features),
        replicate_ratio=float(max(0, n_samples - n_unique) / n_samples),
        missing_rate=missing_rate,
        batch_count=int(frame["experiment_batch_id"].nunique(dropna=True)),
        equipment_count=int(frame["equipment_id"].nunique(dropna=True)),
        coverage_score=float(
            (populated_features / len(CORE_PARAMETER_NAMES)) * (1 - missing_rate)
        ),
    )
