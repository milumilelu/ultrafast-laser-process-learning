"""Target-specific V1 knowledge requirements.

The compiler asks concrete scientific questions.  It does not expand a model
dependency graph and does not manufacture a requirement from a downstream
exception.
"""

from __future__ import annotations

import hashlib
import json

from ultrafast_evidence_prior.schemas import (
    EvidenceType,
    KnowledgeRequirementType,
    KnowledgeRequirementV1,
    ResolvedTaskV1,
    TargetMetric,
)
from ultrafast_requirements.schemas import (
    KnowledgeRequirement,
    RequirementCategory,
    RequirementSource,
    RequirementStatus,
    VariableSemantic,
)

_TARGETS = {
    TargetMetric.DEPTH_UM: {
        "label": "laser ablation or material-removal depth",
        "aliases": [
            "ablation depth",
            "material removal depth",
            "machining depth",
            "removal rate",
        ],
        "parameters": [
            "fluence",
            "pulse energy",
            "average power",
            "pulse duration",
            "repetition rate",
            "scan speed",
            "pulse overlap",
            "hatch spacing",
            "number of passes",
            "focus offset",
        ],
        "properties": [
            "ablation threshold",
            "incubation coefficient",
            "optical penetration depth",
        ],
    },
    TargetMetric.ROUGHNESS_UM: {
        "label": "laser-processed surface roughness (Ra, Sa, Rq or equivalent)",
        "aliases": [
            "surface roughness",
            "roughness Ra",
            "roughness Sa",
            "surface quality",
        ],
        "parameters": [
            "fluence",
            "pulse energy",
            "average power",
            "pulse duration",
            "repetition rate",
            "scan speed",
            "pulse overlap",
            "hatch spacing",
            "number of passes",
            "focus offset",
        ],
        "properties": [
            "ablation threshold",
            "melting threshold",
            "thermal accumulation",
        ],
    },
}


class KnowledgeRequirementTemplateCompiler:
    version = "knowledge-requirement-template-v1"

    def compile(self, task: ResolvedTaskV1) -> list[KnowledgeRequirementV1]:
        target = _TARGETS[task.target_metric]
        material = task.material
        grade = f" grade {task.material_grade}" if task.material_grade else ""
        target_label = str(target["label"])
        parameters = ", ".join(target["parameters"])
        properties = ", ".join(target["properties"])
        common = [material, *target["aliases"]]
        conditions = {
            "material": task.material,
            "target_metric": task.target_metric.value,
        }
        if task.material_grade:
            conditions["material_grade"] = task.material_grade

        specs = [
            (
                KnowledgeRequirementType.MATERIAL_IDENTITY,
                (
                    f"Does the paper directly identify the processed material as {material}{grade}? "
                    "Extract only the identity stated by the paper."
                ),
                [EvidenceType.MATERIAL_IDENTITY],
                [material, task.material_grade or "", "material", "sample"],
                "HIGH",
            ),
            (
                KnowledgeRequirementType.MATERIAL_PROPERTY,
                (
                    f"Which directly reported numeric material or process constants for {material} "
                    f"are relevant to {target_label}, specifically {properties}?"
                ),
                [EvidenceType.PARAMETER_VALUE, EvidenceType.PARAMETER_RANGE],
                [*common, *target["properties"]],
                "HIGH",
            ),
            (
                KnowledgeRequirementType.PROCESS_OBSERVATION,
                (
                    f"Which measured {target_label} observations are directly reported for {material}, "
                    "and under which explicit laser and scanning conditions?"
                ),
                [EvidenceType.PROCESS_OBSERVATION],
                [*common, "measured", "experimental results"],
                "HIGH",
            ),
            (
                KnowledgeRequirementType.PARAMETER_EFFECT,
                (
                    "What explicit direction, threshold, optimum, or non-monotonic effect do "
                    f"{parameters} have on {target_label} for {material}?"
                ),
                [EvidenceType.PARAMETER_EFFECT],
                [*common, *target["parameters"], "effect", "influence"],
                "HIGH",
            ),
            (
                KnowledgeRequirementType.REPORTED_OPTIMUM,
                (
                    "Which numeric parameter values or multi-parameter regions are directly reported "
                    f"as best, optimum, or recommended for {target_label} of {material}?"
                ),
                [EvidenceType.REPORTED_OPTIMUM, EvidenceType.PARAMETER_RANGE],
                [*common, *target["parameters"], "optimum", "optimal", "best", "recommended"],
                "HIGH",
            ),
            (
                KnowledgeRequirementType.MECHANISM,
                (
                    "Which mechanism does the paper explicitly propose to explain changes in "
                    f"{target_label} for {material}?"
                ),
                [EvidenceType.MECHANISM],
                [*common, "mechanism", "incubation", "thermal accumulation", "plasma"],
                "MEDIUM",
            ),
            (
                KnowledgeRequirementType.PROCESS_METHOD,
                (
                    "Which laser-processing method, scan strategy, and experimental configuration "
                    f"were used to produce the reported {target_label} for {material}?"
                ),
                [EvidenceType.PROCESS_METHOD],
                [*common, "experimental setup", "processing method", "scan strategy"],
                "MEDIUM",
            ),
        ]
        return [
            KnowledgeRequirementV1(
                requirement_id=self._id(task, requirement_type),
                requirement_type=requirement_type,
                scientific_question=question,
                target_metric=task.target_metric,
                evidence_types=evidence_types,
                query_terms=list(dict.fromkeys(term for term in query_terms if term)),
                conditions=conditions,
                priority=priority,
                compiler_version=self.version,
            )
            for requirement_type, question, evidence_types, query_terms, priority in specs
        ]

    def _id(
        self,
        task: ResolvedTaskV1,
        requirement_type: KnowledgeRequirementType,
    ) -> str:
        payload = {
            "material": task.material,
            "material_grade": task.material_grade,
            "target_metric": task.target_metric.value,
            "type": requirement_type.value,
            "version": self.version,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:16]
        return f"kreq-{digest}"


def as_retrieval_requirement(requirement: KnowledgeRequirementV1) -> KnowledgeRequirement:
    """Project a V1 question into the existing dual-index retrieval contract."""

    return KnowledgeRequirement(
        requirement_id=requirement.requirement_id,
        quantity=requirement.requirement_type.value.lower(),
        role=requirement.scientific_question,
        required_by=[requirement.target_metric.value],
        acceptable_sources=[
            RequirementSource.STRUCTURED_KNOWLEDGE,
            RequirementSource.LITERATURE,
        ],
        expected_unit=requirement.expected_unit,
        conditions=requirement.conditions,
        resolution_policy="retrieve_per_paper_then_extract_typed_evidence",
        status=RequirementStatus.MISSING,
        category=RequirementCategory.KNOWLEDGE_REQUIREMENT,
        query_terms=requirement.query_terms,
        variable_semantic=VariableSemantic.MODEL_PARAMETER,
    )


def requirement_signature(requirement: KnowledgeRequirementV1) -> str:
    payload = requirement.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
