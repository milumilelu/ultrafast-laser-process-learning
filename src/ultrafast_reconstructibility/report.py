"""M6-3: SourceReconstructibilityReport + SourcePhysicsReadiness aggregation."""

from __future__ import annotations

from ultrafast_reconstructibility.coordinates import CoordinateEvaluator
from ultrafast_reconstructibility.models import (
    CoordinateStatus,
    FieldStatus,
    ReconstructibilityStatus,
    SourceConditionSpec,
    SourcePhysicsReadiness,
    SourceReconstructibilityReport,
)


def build_report(spec: SourceConditionSpec) -> SourceReconstructibilityReport:
    evaluator = CoordinateEvaluator()
    coordinates = evaluator.evaluate(spec)
    report = SourceReconstructibilityReport(
        paper_id=spec.paper_id,
        condition_id=spec.condition_id,
    )
    for field in spec.fields:
        if field.field_status == FieldStatus.REPORTED_CLEAR:
            report.reported_fields.append(field.parameter)
        else:
            report.ambiguous_fields.append(field.parameter)
    missing_params = _missing_params(spec)
    if spec.coverage_status.value != "TEXT_COVERAGE_OK":
        report.coverage_blocked_fields.extend(missing_params)
    else:
        report.missing_fields.extend(missing_params)
    for result in coordinates:
        if result.status == CoordinateStatus.RECONSTRUCTIBLE:
            report.computable_coordinates.append(result)
        else:
            report.blocked_coordinates.append(result)
            report.blocking_dependencies.extend(result.missing_inputs)
    report.blocking_dependencies = sorted(set(report.blocking_dependencies))
    report.reconstructibility_status = _overall_status(report)
    if report.ambiguous_fields:
        report.warnings.append(
            f"ambiguous fields: {sorted(report.ambiguous_fields)}"
        )
    return report


def build_readiness(reports: list[SourceReconstructibilityReport]) -> SourcePhysicsReadiness:
    readiness = SourcePhysicsReadiness()
    readiness.reported_field_count = sum(len(r.reported_fields) for r in reports)
    readiness.ambiguous_field_count = sum(len(r.ambiguous_fields) for r in reports)
    readiness.missing_field_count = sum(len(r.missing_fields) for r in reports)
    readiness.coverage_blocked_field_count = sum(len(r.coverage_blocked_fields) for r in reports)
    readiness.computable_coordinate_count = sum(len(r.computable_coordinates) for r in reports)
    readiness.blocked_coordinate_count = sum(len(r.blocked_coordinates) for r in reports)
    status_counts: dict[str, int] = {}
    for r in reports:
        for result in r.computable_coordinates + r.blocked_coordinates:
            status_counts[result.status.value] = status_counts.get(result.status.value, 0) + 1
        if r.reconstructibility_status in (
            ReconstructibilityStatus.FULL,
            ReconstructibilityStatus.PARTIAL,
        ):
            readiness.reconstructible_conditions += 1
    readiness.coordinate_status = status_counts
    readiness.total_conditions = len(reports)
    return readiness


def _missing_params(spec: SourceConditionSpec) -> list[str]:
    present = {f.parameter for f in spec.fields}
    return sorted(set(_EXPECTED_PARAMS) - present)


_EXPECTED_PARAMS = {
    "frequency",
    "pulse_width",
    "scan_speed",
    "hatch_spacing",
    "passes",
    "pulse_energy",
    "average_power",
    "spot_size",
    "fluence",
    "accumulated_dose",
}


def _overall_status(report: SourceReconstructibilityReport) -> ReconstructibilityStatus:
    if report.computable_coordinates:
        if not report.blocked_coordinates:
            return ReconstructibilityStatus.FULL
        return ReconstructibilityStatus.PARTIAL
    return ReconstructibilityStatus.BLOCKED
