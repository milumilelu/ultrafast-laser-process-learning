"""Deterministic Evidence scope applicability rules.

输出逐维度匹配 + transfer_class，而不是单个置信度数字。
"""

from __future__ import annotations

from typing import Any

from ultrafast_e2p.domain.evidence import ApplicabilityReport, EvidenceClaim


def _match(task_value: str | None, evidence_value: str | None) -> bool | None:
    if evidence_value is None:
        return None
    return task_value == evidence_value


def assess_applicability(
    task: dict[str, Any],
    claim: EvidenceClaim,
) -> ApplicabilityReport:
    scope = claim.scope or {}
    report = ApplicabilityReport(
        claim_id=claim.claim_id,
        material_match=_match(task.get("material_id"), scope.get("material_id")),
        laser_type_match=_match(task.get("laser_type"), scope.get("laser_type")),
        process_type_match=_match(task.get("process_type"), scope.get("process_type")),
        geometry_match=_match(task.get("geometry_type"), scope.get("geometry_type")),
        equipment_match=_match(task.get("equipment_id"), scope.get("equipment_id")),
        target_metric_match=_match(task.get("target_metric"), scope.get("target_metric")),
    )
    incompatible = any(
        getattr(report, key) is False
        for key in (
            "material_match",
            "laser_type_match",
            "process_type_match",
            "geometry_match",
            "target_metric_match",
        )
    )
    if incompatible:
        transfer = "none"
    elif all(
        getattr(report, key) is True
        for key in (
            "material_match",
            "laser_type_match",
            "process_type_match",
            "geometry_match",
            "equipment_match",
            "target_metric_match",
        )
    ):
        transfer = "strong"
    elif (
        report.material_match is True
        and report.laser_type_match is True
        and (report.process_type_match in (True, None))
        and report.geometry_match in (True, None)
    ):
        transfer = "medium" if report.equipment_match is False else "strong"
    else:
        transfer = "weak"
    report.transfer_class = transfer
    return report
