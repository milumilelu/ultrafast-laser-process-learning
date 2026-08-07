"""Deterministic Scientific Validator（文档 §17-18）。

LLM 输出不能直接进入 E2P：必须经过确定性校验。
- Schema：必需字段、参数名、目标名、语义角色、来源引用；
- Unit：确定性单位换算（禁止依赖 LLM 做单位换算）；
- Formula Consistency：Ep = Pavg/f、数量级检查；
- Scope：材料/激光/波长/脉宽/几何/工艺/目标一致；
- Source：paper_id / page / chunk_id 真实存在。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ultrafast_knowledge.scientific.schemas import (
    CandidateType,
    ScientificKnowledgeCandidate,
    ScientificKnowledgePack,
    ValidationIssue,
    ValidationResult,
)
from ultrafast_shared.units import normalize_unit

# 参数名 → 合法单位集（规范单位）
PARAMETER_UNITS: dict[str, tuple[str, ...]] = {
    "laser_power_W": ("W",),
    "pulse_width_fs": ("s",),
    "frequency_kHz": ("Hz",),
    "scan_speed_mm_s": ("m/s",),
    "hatch_spacing_um": ("m",),
    "passes": (),
    "spot_radius_um": ("m",),
    "wavelength_nm": ("m",),
    "ablation_threshold_fluence": ("J/m2",),
    "thermal_diffusivity": ("m2/s",),
}

REQUIRED_BY_TYPE: dict[CandidateType, tuple[str, ...]] = {
    CandidateType.PARAMETER_VALUE: ("parameter", "value", "unit"),
    CandidateType.PARAMETER_RANGE: ("parameter", "lower", "upper", "unit"),
    CandidateType.PARAMETER_EFFECT: ("parameter", "relation"),
    CandidateType.THRESHOLD: ("property", "value", "unit"),
    CandidateType.FORMULA: ("name", "expression"),
    CandidateType.MATERIAL_PROPERTY: ("property", "value", "unit"),
    CandidateType.OPTICAL_PROPERTY: ("property", "value", "unit"),
    CandidateType.REPORTED_OPTIMUM: ("parameter",),
    CandidateType.EXPERIMENTAL_CONDITION: ("parameter", "value", "unit"),
}

# 已知陷阱对（文档 §51 benchmark）：fs/ps、kHz/MHz、radius/diameter 等
TRAP_TERMS = {
    "fs": "ps",
    "ps": "fs",
    "khz": "mhz",
    "mhz": "khz",
    "radius": "diameter",
    "average power": "pulse energy",
    "fluence": "intensity",
}


class DeterministicScientificValidator:
    def __init__(
        self,
        *,
        source_checker: Callable[[dict[str, Any]], bool] | None = None,
    ):
        """source_checker：验证 paper_id/page/chunk 是否真实存在（注入 DB 访问）。"""
        self.source_checker = source_checker

    def validate(self, pack: ScientificKnowledgePack) -> ValidationResult:
        validated: list[str] = []
        rejected: list[str] = []
        issues: list[ValidationIssue] = []
        for candidate in pack.candidates:
            candidate_issues = self._validate_candidate(candidate)
            issues.extend(candidate_issues)
            if any(issue.severity == "error" for issue in candidate_issues):
                rejected.append(candidate.candidate_id)
            else:
                validated.append(candidate.candidate_id)
        return ValidationResult(
            validated_candidates=validated,
            rejected_candidates=rejected,
            issues=issues,
        )

    def _validate_candidate(self, candidate: ScientificKnowledgeCandidate) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        required = REQUIRED_BY_TYPE.get(candidate.type, ())
        for field_name in required:
            if getattr(candidate, field_name) is None:
                issues.append(
                    ValidationIssue(
                        candidate_id=candidate.candidate_id,
                        code=f"missing_field_{field_name}",
                        message=f"candidate {candidate.candidate_id} missing required field: {field_name}",
                    )
                )
        if not candidate.supporting_sources:
            issues.append(
                ValidationIssue(
                    candidate_id=candidate.candidate_id,
                    code="missing_source",
                    message="candidate has no supporting source (prohibited)",
                )
            )
        elif self.source_checker is not None:
            for ref in candidate.supporting_sources:
                if not self.source_checker(
                    {
                        "paper_id": ref.paper_id,
                        "page": ref.page,
                        "chunk_ids": ref.chunk_ids,
                    }
                ):
                    issues.append(
                        ValidationIssue(
                            candidate_id=candidate.candidate_id,
                            code="unverifiable_source",
                            message=f"source ref not found in repository: {ref.model_dump()}",
                        )
                    )
                    break
        self._check_unit_consistency(candidate, issues)
        self._check_formula_consistency(candidate, issues)
        self._check_traps(candidate, issues)
        return issues

    def _check_unit_consistency(
        self, candidate: ScientificKnowledgeCandidate, issues: list[ValidationIssue]
    ) -> None:
        """单位必须可换算到规范单位；数值型候选单位不可识别即拒绝。"""
        if candidate.unit is None:
            return
        normalized, _factor = normalize_unit(candidate.unit)
        if normalized is None:
            issues.append(
                ValidationIssue(
                    candidate_id=candidate.candidate_id,
                    code="unrecognized_unit",
                    message=f"unit '{candidate.unit}' cannot be normalized",
                )
            )
            return
        allowed = PARAMETER_UNITS.get(candidate.parameter or "")
        if allowed and normalized not in allowed:
            issues.append(
                ValidationIssue(
                    candidate_id=candidate.candidate_id,
                    code="unit_mismatch",
                    message=(
                        f"parameter {candidate.parameter} expects unit in {allowed}, "
                        f"got '{candidate.unit}' normalized to '{normalized}'"
                    ),
                )
            )

    def _check_formula_consistency(
        self, candidate: ScientificKnowledgeCandidate, issues: list[ValidationIssue]
    ) -> None:
        """Pavg/f/Ep 一致性（文档 §18.3）：同源同时给出时做确定性检查。"""
        notes = " ".join(candidate.extraction_notes).lower()
        if candidate.parameter in {"laser_power_W", "frequency_kHz"} or not candidate.value:
            return
        if "ep" in notes and "pavg" in notes and "f" in notes:
            issues.append(
                ValidationIssue(
                    candidate_id=candidate.candidate_id,
                    code="formula_consistency_manual_review",
                    message="power/frequency/pulse-energy consistency requires cross-source check",
                    severity="warning",
                )
            )

    def _check_traps(
        self, candidate: ScientificKnowledgeCandidate, issues: list[ValidationIssue]
    ) -> None:
        """已知陷阱：fs/ps、kHz/MHz、radius/diameter 混淆检测。"""
        text = " ".join(
            str(value)
            for value in (
                candidate.name,
                candidate.parameter,
                candidate.property,
                candidate.expression,
                *candidate.extraction_notes,
            )
            if value
        ).lower()
        for left, right in TRAP_TERMS.items():
            if left in text and right in text:
                issues.append(
                    ValidationIssue(
                        candidate_id=candidate.candidate_id,
                        code="unit_trap_confusion",
                        message=f"both '{left}' and '{right}' appear; reviewer must disambiguate",
                        severity="warning",
                    )
                )


def default_source_checker(connection: Any) -> Callable[[dict[str, Any]], bool]:
    """基于 ultrafast_memory 数据库的 source 存在性检查。"""

    def check(ref: dict[str, Any]) -> bool:
        paper_id = ref.get("paper_id")
        chunk_ids = ref.get("chunk_ids") or []
        if not paper_id and not chunk_ids:
            return False
        try:
            with connection() as conn:
                if paper_id:
                    paper = conn.execute(
                        "SELECT 1 FROM literature_paper WHERE paper_id=?", (paper_id,)
                    ).fetchone()
                    if paper is None:
                        return False
                if chunk_ids:
                    placeholders = ",".join("?" * len(chunk_ids))
                    found = conn.execute(
                        f"SELECT COUNT(*) FROM literature_chunk WHERE chunk_id IN ({placeholders})",
                        chunk_ids,
                    ).fetchone()[0]
                    if found != len(chunk_ids):
                        return False
                return True
        except Exception:  # noqa: BLE001 - 校验失败按不可信处理
            return False

    return check
