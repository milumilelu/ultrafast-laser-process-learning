"""Prior 编译的唯一权威：approved prior / EvidenceBundle → GovernedPriorArtifact。

BO 只消费 GovernedPriorArtifact；任何"知识→先验"的转换都必须经过本模块，
禁止在建模/BO 内部自行编译知识（approval_id / review_status / RAG chunk
均为 E2P 上游概念）。

治理保障（P0：封死裸 PriorSpec 绕过）：
- 每个 approved prior 必须携带 approval_id，否则不编译；
- 提供 approval_verifier 时，approval_id 必须在 approval repository 中存在
  且有效，否则标记 ignored_unverified；
- scope 明确冲突（material/laser/process/geometry/target）的 prior 不编译；
- 编译产物是内容哈希绑定的 GovernedPriorArtifact，调用方无法手工伪造
  approval 链。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ultrafast_e2p.application.prior_artifact import (
    REPOSITORY_VERIFIED,
    SELF_ATTESTED,
    GovernedPriorArtifact,
    compute_prior_content_hash,
)
from ultrafast_e2p.application.soft_prior import (
    PRIOR_SPEC_VERSION,
)
from ultrafast_e2p.application.soft_prior import (
    compile_prior_spec as compile_from_bundle,
)
from ultrafast_e2p.domain.evidence import EvidenceBundle

__all__ = ["PRIOR_SPEC_VERSION", "compile_from_approved_priors", "compile_from_bundle"]

# scope 键：与任务 scope 冲突判定使用 canonical 值比较
_SCOPE_KEYS = ("material", "laser_type", "process_type", "geometry_type", "target")

STRENGTH_WEIGHTS = {"strong": 1.0, "medium": 0.5, "weak": 0.25}


def compile_from_approved_priors(
    bounds: dict[str, list[float]],
    priors: list[dict[str, Any]],
    *,
    scope: dict[str, Any] | None = None,
    approval_verifier: Callable[[str], bool] | None = None,
) -> GovernedPriorArtifact:
    """approved prior（治理对象）→ GovernedPriorArtifact。

    只编译与机器边界有交集的区间偏好；先验只影响候选排序，
    绝不删除合法机器空间（与 E2P Soft Prior 原则一致）。
    """
    scope = {key: value for key, value in (scope or {}).items() if value is not None}
    preferences = []
    approval_ids: list[str] = []
    evidence_ids: list[str] = []
    trace: list[dict[str, Any]] = []
    verification = SELF_ATTESTED if approval_verifier is None else REPOSITORY_VERIFIED
    for prior in priors:
        approval_id = prior.get("approval_id")
        parameter = prior.get("parameter_name")
        if not approval_id:
            trace.append({"step": "knowledge_prior", "status": "ignored_unapproved"})
            continue
        conflict = _scope_conflict(prior, scope)
        if conflict:
            trace.append(
                {
                    "step": "knowledge_prior",
                    "status": "ignored_scope_conflict",
                    "approval_id": approval_id,
                    "conflict": conflict,
                }
            )
            continue
        if approval_verifier is not None and not approval_verifier(str(approval_id)):
            trace.append(
                {
                    "step": "knowledge_prior",
                    "status": "ignored_unverified",
                    "approval_id": approval_id,
                }
            )
            continue
        if parameter not in bounds:
            trace.append(
                {
                    "step": "knowledge_prior",
                    "status": "ignored_unknown_parameter",
                    "approval_id": approval_id,
                }
            )
            continue
        try:
            lower = float(prior["lower_bound"])
            upper = float(prior["upper_bound"])
        except (KeyError, TypeError, ValueError):
            trace.append(
                {
                    "step": "knowledge_prior",
                    "status": "ignored_invalid",
                    "approval_id": approval_id,
                }
            )
            continue
        machine_lower, machine_upper = bounds[parameter]
        intersection = [max(machine_lower, lower), min(machine_upper, upper)]
        if intersection[0] > intersection[1]:
            trace.append(
                {
                    "step": "knowledge_prior",
                    "status": "ignored_outside_machine_bounds",
                    "approval_id": approval_id,
                    "parameter": parameter,
                }
            )
            continue
        # approval ≠ strength：审批只是权限门（permission），
        # 转移强度（epistemic confidence）必须独立提供；
        # 未提供时使用中性 medium（0.5），绝不默认 strong。
        strength = prior.get("transfer_strength") or "medium"
        weight = STRENGTH_WEIGHTS.get(strength, 0.5)
        preferences.append(
            {
                "claim_id": str(approval_id),
                "parameter": parameter,
                "lower": float(intersection[0]),
                "upper": float(intersection[1]),
                "strength": strength,
                "fixed_weight": weight,
                "semantic_role": "approved_prior",
            }
        )
        approval_ids.append(str(approval_id))
        prior_evidence = prior.get("evidence_ids")
        if isinstance(prior_evidence, (list, tuple)):
            evidence_ids.extend(str(item) for item in prior_evidence)
        trace.append(
            {
                "step": "knowledge_prior",
                "status": "applied_soft",
                "approval_id": approval_id,
                "parameter": parameter,
                "intersection": intersection,
            }
        )
    prior_spec = {
        "prior_spec_version": PRIOR_SPEC_VERSION,
        "range_preferences": preferences,
    }
    content_hash = compute_prior_content_hash(
        prior_spec, approval_ids, scope, PRIOR_SPEC_VERSION
    )
    return GovernedPriorArtifact(
        prior_spec=prior_spec,
        approval_ids=tuple(dict.fromkeys(approval_ids)),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        source_trace=tuple(trace),
        compiler_version=PRIOR_SPEC_VERSION,
        scope=scope,
        content_hash=content_hash,
        verification=verification,
    )


def _scope_conflict(prior: dict[str, Any], scope: dict[str, Any]) -> str | None:
    """prior 元数据与任务 scope 的明确冲突检测（canonical 值比较）。

    只判定"明确不匹配"（如 prior=SiC vs scope=CFRP）；未提供的维度不判定。
    模糊/未知维度由下游 applicability 与证据强度决定。
    """
    for key in _SCOPE_KEYS:
        prior_value = prior.get(key) or prior.get(f"{key}_id")
        task_value = scope.get(key)
        if not prior_value or not task_value:
            continue
        if _canonical(key, str(prior_value)) != _canonical(key, str(task_value)):
            return f"{key}:{prior_value}!=scope:{task_value}"
    return None


def _canonical(key: str, value: str) -> str:
    # 本地规范化（不依赖 ontology 包，e2p 保持 leaf）：只判定"明确不等"；
    # 别名级等价（CFRP == 碳纤维复合板）由下游 applicability 层完成。
    return re.sub(r"[\s\-_/]+", " ", value.strip().lower())
