"""E2P 输出对象：FeatureSpec / E2PDecision（文档 §24-25、§41）。

E2P 是本系统唯一的"治理后科学知识 → 可执行科学对象"编译入口；
FeatureSpec 描述一个可由 Physics Feature Engine 计算的派生特征。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

UncertaintyMode = Literal["none", "range_propagation", "monte_carlo"]


class FeatureSpec(BaseModel):
    """派生特征规范（文档 §25）。"""

    feature_id: str
    feature_name: str
    formula_id: str | None = None
    required_inputs: list[str] = Field(default_factory=list)
    required_properties: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    applicability: dict[str, Any] = Field(default_factory=dict)
    source_knowledge_ids: list[str] = Field(default_factory=list)
    uncertainty_mode: UncertaintyMode = "none"
    version: str = "feature-spec-v1"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ModelPolicySpec(BaseModel):
    model_policy_version: str = "e2p-model-policy-v1"
    candidate_models: list[str] = Field(default_factory=list)
    requirements: dict[str, Any] = Field(default_factory=dict)
    source_knowledge_ids: list[str] = Field(default_factory=list)


class ConstraintSpec(BaseModel):
    constraint_id: str
    constraint_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    threshold: float | None = None
    formula: str | None = None
    hard: bool = True
    source_knowledge_ids: list[str] = Field(default_factory=list)


class E2PDecision(BaseModel):
    """Knowledge Action Router 输出（文档 §41）。"""

    e2p_run_id: str
    task_scope: dict[str, Any]
    feature_specs: list[FeatureSpec] = Field(default_factory=list)
    prior_specs: list[dict[str, Any]] = Field(default_factory=list)
    model_policy: ModelPolicySpec | None = None
    constraint_specs: list[ConstraintSpec] = Field(default_factory=list)
    knowledge_used: list[str] = Field(default_factory=list)
    knowledge_rejected: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    # E2P 主动请求知识（审阅 §5）：FeatureSpec 必需输入中当前缺失者
    missing_inputs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
