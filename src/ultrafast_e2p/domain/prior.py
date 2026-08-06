"""PriorSpec / PriorConflictReport / E2PRun —— E2P 的确定性产物与追溯结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RangePreference:
    claim_id: str
    parameter: str
    lower: float
    upper: float
    strength: str  # strong | medium | weak
    fixed_weight: float
    semantic_role: str = "unspecified"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PriorSpec:
    prior_spec_version: str
    range_preferences: list[RangePreference] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "prior_spec_version": self.prior_spec_version,
            "range_preferences": [item.as_dict() for item in self.range_preferences],
        }


@dataclass
class PriorConflictReport:
    """Evidence 先验与真实观测一致性检查（观察后更新 λ_E 的依据）。"""

    evidence_id: str
    parameter: str
    evidence_lower: float
    evidence_upper: float
    observed_good_ratio_inside: float  # 观测到的好点在先验区间内的比例
    conflict_level: str = "none"  # none | weak | strong
    suggested_weight_multiplier: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class E2PRun:
    e2p_run_id: str
    task_scope: dict[str, Any]
    evidence_ids: list[str] = field(default_factory=list)
    prior_spec_id: str | None = None
    timestamp: str | None = None
    model_policy_id: str | None = None
    optimization_run_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
