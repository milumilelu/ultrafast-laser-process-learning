"""Canonical task scope and data profile shared by E2P and downstream science."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class TaskScope:
    """Canonical task scope. All ids are canonical; free text never enters here."""

    material_id: str | None = None
    material_grade: str | None = None
    laser_type: str | None = None  # fs | ps
    process_type: str | None = None
    geometry_type: str | None = None
    equipment_id: str | None = None
    target_metric: str | None = None  # depth_um | roughness_um | Sa_um ...

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TaskScope:
        allowed = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value.get(key) for key in allowed})


@dataclass
class DataProfile:
    n_samples: int = 0
    n_unique_designs: int = 0
    n_features: int = 0
    replicate_ratio: float = 0.0
    missing_rate: float = 0.0
    batch_count: int = 0
    equipment_count: int = 0
    coverage_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DataProfile:
        allowed = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value.get(key) for key in allowed})
