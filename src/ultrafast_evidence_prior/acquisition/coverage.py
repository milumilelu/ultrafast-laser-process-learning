"""Compile operational evidence facets and assess validated EvidenceIR coverage."""

from __future__ import annotations

import re
from typing import Literal

from ultrafast_evidence_prior.schemas import (
    CoverageFacetResult,
    CoverageFacetSpec,
    CoverageGap,
    EvidenceCoverageReport,
    EvidenceIRV2,
    KnowledgeRequirementType,
    KnowledgeRequirementV1,
    MaterialIdentityContent,
    MechanismContent,
    ParameterEffectContent,
    ParameterRangeContent,
    ParameterValueContent,
    ProcessMethodContent,
    ProcessObservationContent,
    ReportedOptimumContent,
    RequirementCoverageSpec,
    ResolvedTaskV1,
    ValidationState,
)

_QUERY_HINTS: dict[KnowledgeRequirementType, tuple[str, ...]] = {
    KnowledgeRequirementType.MATERIAL_PROPERTY: ("reported", "value", "table"),
    KnowledgeRequirementType.PROCESS_OBSERVATION: ("measured", "results", "experimental"),
    KnowledgeRequirementType.PARAMETER_EFFECT: (
        "effect",
        "influence",
        "dependence",
        "threshold",
        "optimum",
    ),
    KnowledgeRequirementType.REPORTED_OPTIMUM: ("optimum", "optimal", "best", "recommended"),
    KnowledgeRequirementType.MECHANISM: (
        "mechanism",
        "discussion",
        "incubation",
        "thermal accumulation",
        "plasma shielding",
    ),
    KnowledgeRequirementType.PROCESS_METHOD: (
        "experimental setup",
        "processing method",
        "scan strategy",
    ),
}


class RequirementCoverageSpecCompiler:
    version = "requirement-coverage-spec-v1"

    def compile(
        self,
        task: ResolvedTaskV1,
        requirement: KnowledgeRequirementV1,
    ) -> RequirementCoverageSpec:
        requirement_type = requirement.requirement_type
        if requirement_type == KnowledgeRequirementType.MATERIAL_IDENTITY:
            facets = [self._facet(requirement, "material_identity", task.material)]
            if task.material_grade:
                facets.append(self._facet(requirement, "material_grade", task.material_grade))
            minimum_core = len(facets)
            target_coverage = 1.0
        elif requirement_type == KnowledgeRequirementType.MATERIAL_PROPERTY:
            facets = [
                self._facet(
                    requirement,
                    "material_property",
                    target,
                    required_condition_keys=["material"],
                )
                for target in requirement.coverage_targets
            ]
            minimum_core = 1
            target_coverage = 1.0
        elif requirement_type == KnowledgeRequirementType.PROCESS_OBSERVATION:
            facets = [
                self._facet(
                    requirement,
                    "process_observation",
                    requirement.target_metric.value,
                    required_condition_keys=["material"],
                )
            ]
            minimum_core = 1
            target_coverage = 1.0
        elif requirement_type == KnowledgeRequirementType.PARAMETER_EFFECT:
            core_targets = self._active_parameters(task)
            targets = requirement.coverage_targets or sorted(core_targets)
            facets = [
                self._facet(
                    requirement,
                    "parameter_effect",
                    target,
                    importance="CORE" if target in core_targets else "OPTIONAL",
                    required_condition_keys=["material"],
                )
                for target in targets
            ]
            if facets and not any(item.importance == "CORE" for item in facets):
                facets[0] = facets[0].model_copy(update={"importance": "CORE"})
            minimum_core = 1
            target_coverage = 0.6
        elif requirement_type == KnowledgeRequirementType.REPORTED_OPTIMUM:
            facets = [
                self._facet(
                    requirement,
                    "reported_optimum",
                    "multi_parameter_region",
                    required_condition_keys=["material"],
                )
            ]
            minimum_core = 1
            target_coverage = 1.0
        elif requirement_type == KnowledgeRequirementType.MECHANISM:
            facets = [self._facet(requirement, "mechanism", "explicit_mechanism")]
            minimum_core = 1
            target_coverage = 1.0
        else:
            facets = [
                self._facet(requirement, "process_method", "processing_method"),
                self._facet(
                    requirement,
                    "scan_strategy",
                    "scan_strategy",
                    importance="OPTIONAL",
                ),
                self._facet(
                    requirement,
                    "experimental_configuration",
                    "experimental_configuration",
                    importance="OPTIONAL",
                ),
            ]
            minimum_core = 1
            target_coverage = 0.67
        if not facets:
            facets = [self._facet(requirement, requirement_type.value.casefold(), None)]
        return RequirementCoverageSpec(
            requirement_id=requirement.requirement_id,
            facets=facets,
            minimum_core_facets=minimum_core,
            target_coverage=target_coverage,
        )

    @staticmethod
    def _facet(
        requirement: KnowledgeRequirementV1,
        kind: str,
        target: str | None,
        *,
        importance: Literal["CORE", "OPTIONAL"] = "CORE",
        required_condition_keys: list[str] | None = None,
    ) -> CoverageFacetSpec:
        target_key = _canonical(target or "any").replace(" ", "-")
        return CoverageFacetSpec(
            facet_id=f"{requirement.requirement_id}:{kind}:{target_key}",
            kind=kind,
            canonical_target=target,
            importance=importance,
            required_condition_keys=required_condition_keys or [],
        )

    @staticmethod
    def _active_parameters(task: ResolvedTaskV1) -> set[str]:
        equipment = task.equipment
        active: set[str] = set()
        if equipment.effective_max_power_W is not None or equipment.rated_max_power_W is not None:
            active.add("average power")
        if equipment.pulse_width_min_fs is not None:
            active.add("pulse duration")
        if equipment.frequency_min_kHz is not None:
            active.add("repetition rate")
        if equipment.scan_speed_min_mm_s is not None:
            active.add("scan speed")
        return active


class EvidenceCoverageAssessor:
    def assess(
        self,
        requirement: KnowledgeRequirementV1,
        spec: RequirementCoverageSpec,
        evidence: list[EvidenceIRV2],
    ) -> EvidenceCoverageReport:
        relevant = [item for item in evidence if item.requirement_id == requirement.requirement_id]
        valid = [item for item in relevant if item.validation_state == ValidationState.VALIDATED]
        rejected = [
            item.evidence_id
            for item in relevant
            if item.validation_state != ValidationState.VALIDATED
        ]
        results: list[CoverageFacetResult] = []
        gaps: list[CoverageGap] = []
        for facet in spec.facets:
            matches = [item for item in valid if self._matches(facet, item)]
            supported, missing_conditions = self._support_state(facet, matches)
            status: Literal["SUPPORTED", "PARTIAL", "MISSING", "CONFLICT"] = (
                "SUPPORTED" if supported else ("PARTIAL" if matches else "MISSING")
            )
            result = CoverageFacetResult(
                facet_id=facet.facet_id,
                status=status,
                evidence_ids=[item.evidence_id for item in matches],
                paper_ids=list(dict.fromkeys(item.paper_id for item in matches)),
                missing_condition_keys=missing_conditions,
            )
            results.append(result)
            if status != "SUPPORTED":
                gaps.append(
                    CoverageGap(
                        facet_id=facet.facet_id,
                        missing_fields=missing_conditions,
                        reason_codes=[
                            "no_matching_validated_evidence"
                            if not matches
                            else "required_conditions_not_validated"
                        ],
                        suggested_terms=[
                            *([facet.canonical_target] if facet.canonical_target else []),
                            *_QUERY_HINTS.get(requirement.requirement_type, ()),
                        ],
                    )
                )
        weights = [
            1.0 if item.status == "SUPPORTED" else 0.5 if item.status == "PARTIAL" else 0.0
            for item in results
        ]
        coverage_ratio = sum(weights) / len(weights) if weights else 0.0
        result_by_id = {item.facet_id: item for item in results}
        core_supported = sum(
            result_by_id[facet.facet_id].status == "SUPPORTED"
            for facet in spec.facets
            if facet.importance == "CORE"
        )
        operationally_sufficient = core_supported >= spec.minimum_core_facets
        return EvidenceCoverageReport(
            requirement_id=requirement.requirement_id,
            coverage_ratio=round(coverage_ratio, 4),
            operationally_sufficient=operationally_sufficient,
            facets=results,
            gaps=gaps,
            rejected_evidence_ids=rejected,
        )

    @staticmethod
    def _support_state(
        facet: CoverageFacetSpec,
        matches: list[EvidenceIRV2],
    ) -> tuple[bool, list[str]]:
        if len(matches) < facet.minimum_claims:
            return False, list(facet.required_condition_keys)
        papers = {item.paper_id for item in matches}
        if len(papers) < facet.minimum_papers:
            return False, list(facet.required_condition_keys)
        missing_by_item = [
            [key for key in facet.required_condition_keys if key not in item.validated_conditions]
            for item in matches
        ]
        if any(not missing for missing in missing_by_item):
            return True, []
        missing = sorted({key for keys in missing_by_item for key in keys})
        return not facet.required_condition_keys, missing

    @staticmethod
    def _matches(facet: CoverageFacetSpec, evidence: EvidenceIRV2) -> bool:
        content = evidence.content
        target = facet.canonical_target or ""
        if facet.kind == "material_identity":
            return isinstance(content, MaterialIdentityContent) and _same_term(
                content.material, target
            )
        if facet.kind == "material_grade":
            return (
                isinstance(content, MaterialIdentityContent)
                and content.material_grade is not None
                and _same_term(content.material_grade, target)
            )
        if facet.kind == "material_property":
            return isinstance(
                content, (ParameterValueContent, ParameterRangeContent)
            ) and _same_term(content.parameter, target)
        if facet.kind == "process_observation":
            return (
                isinstance(content, ProcessObservationContent)
                and content.measured_value is not None
                and content.target_metric is not None
                and _same_term(content.target_metric, target)
            )
        if facet.kind == "parameter_effect":
            return isinstance(content, ParameterEffectContent) and _same_term(
                content.parameter, target
            )
        if facet.kind == "reported_optimum":
            return isinstance(content, ReportedOptimumContent) and bool(content.parameters)
        if facet.kind == "mechanism":
            return isinstance(content, MechanismContent)
        if not isinstance(content, ProcessMethodContent):
            return False
        method_text = f"{content.method} {content.statement}"
        if facet.kind == "process_method":
            return True
        if facet.kind == "scan_strategy":
            return any(term in _canonical(method_text) for term in ("scan", "raster", "hatch"))
        if facet.kind == "experimental_configuration":
            return bool(
                set(evidence.validated_conditions)
                & {
                    "wavelength_nm",
                    "pulse_width_fs",
                    "frequency_kHz",
                    "average_power_W",
                    "scan_speed_mm_s",
                }
            ) or any(term in _canonical(method_text) for term in ("setup", "configuration"))
        return False


def _canonical(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", str(value).casefold()).strip()


def _same_term(left: str, right: str) -> bool:
    left_value = _canonical(left)
    right_value = _canonical(right)
    return left_value == right_value or left_value in right_value or right_value in left_value
