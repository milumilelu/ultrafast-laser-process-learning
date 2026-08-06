"""Canonical task scope and data profile shared by E2P and downstream science."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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


@dataclass
class ApplicabilityReport:
    """逐维度适用性，而不是一个神秘的置信度数字。"""

    claim_id: str
    material_match: bool | None = None
    laser_type_match: bool | None = None
    process_type_match: bool | None = None
    geometry_match: bool | None = None
    equipment_match: bool | None = None
    target_metric_match: bool | None = None
    transfer_class: str = "none"  # strong | medium | weak | none

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Type alias: 语义角色 —— 解决"正则抓到什么数字都混在一起"的问题
SEMANTIC_ROLES = (
    "experimental_condition",  # 实验固定/对照条件
    "searched_range",  # 扫描范围边界
    "reported_optimum",  # 报告的最优条件
    "recommended_range",  # 作者推荐区间
    "observed_relation",  # 观测到的关系（方向/相对重要性）
    "unspecified",  # 无法判定
)

CLAIM_TYPES = (
    "parameter_direction",
    "range_preference",  # 与 Topic2 契约枚举一致
    "preferred_range",  # 别名
    "relative_importance",
    "historical_dataset",
    "historical_model",
    "functional_shape",
)

PREFERRED_RANGE_CLAIM_TYPES = {"range_preference", "preferred_range"}


@dataclass
class EvidenceClaim:
    """RAG chunk 与概率模型之间的唯一正式桥梁。"""

    claim_id: str
    claim_type: str = "preferred_range"
    parameter: str | None = None
    target: str | None = None
    value: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    semantic_role: str = "unspecified"
    source: dict[str, Any] = field(default_factory=dict)
    review_status: str = "pending"
    version: str = "1"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvidenceClaim:
        allowed = {name for name in cls.__dataclass_fields__}
        return cls(**{key: value.get(key) for key in allowed})


@dataclass
class EvidenceBundle:
    candidates: list[EvidenceClaim] = field(default_factory=list)
    accepted: list[EvidenceClaim] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    applicability_results: list[dict[str, Any]] = field(default_factory=list)
    version: str = "evidence-bundle-v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "candidates": [item.as_dict() for item in self.candidates],
            "accepted": [item.as_dict() for item in self.accepted],
            "rejected": list(self.rejected),
            "applicability_results": list(self.applicability_results),
        }
