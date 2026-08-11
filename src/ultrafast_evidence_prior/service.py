"""Synchronous V1 orchestration: equipment + task → evidence → beliefs → priors."""

from __future__ import annotations

import uuid
from typing import Any

from ultrafast_app.services.scientific_pipeline import build_llm_client
from ultrafast_evidence_prior.acquisition import EvidenceAcquisitionSession
from ultrafast_evidence_prior.e2p import compile_beliefs, compile_priors
from ultrafast_evidence_prior.extraction import TypedEvidenceExtractor
from ultrafast_evidence_prior.knowledge_store import StructuredKnowledgeStoreV2
from ultrafast_evidence_prior.requirements import (
    KnowledgeRequirementTemplateCompiler,
)
from ultrafast_evidence_prior.schemas import (
    EquipmentContext,
    EvidenceIRSetV2,
    EvidencePriorAnalysisResult,
    ResolvedTaskV1,
    TaskRequestV1,
    ValidationState,
)
from ultrafast_knowledge.evidence_pipeline import (
    PersistentScientificPaperRepository,
    ScientificIndexStore,
)
from ultrafast_memory.equipment.power import resolve_effective_max_power
from ultrafast_memory.equipment.service import get_equipment_profile_revision


class EvidencePriorAnalysisService:
    def __init__(
        self,
        client: Any | None = None,
        *,
        connection: Any = None,
        paper_top_k: int = 3,
        windows_per_paper: int = 8,
        llm_timeout: float = 180.0,
    ) -> None:
        self.client = client or build_llm_client()
        self.model = str(getattr(self.client, "model", "unknown"))
        self.paper_top_k = paper_top_k
        self.windows_per_paper = windows_per_paper
        self.store = ScientificIndexStore(connection=connection)
        self.repository = PersistentScientificPaperRepository(self.store)
        self.knowledge_store = StructuredKnowledgeStoreV2(self.store)
        self.extractor = TypedEvidenceExtractor(
            self.client,
            model=self.model,
            timeout=llm_timeout,
            max_windows=windows_per_paper,
        )
        self.acquisition = EvidenceAcquisitionSession(
            repository=self.repository,
            knowledge_store=self.knowledge_store,
            extractor=self.extractor,
            paper_top_k=paper_top_k,
            windows_per_paper=windows_per_paper,
        )
        self.requirement_compiler = KnowledgeRequirementTemplateCompiler()

    def analyze(
        self,
        request: TaskRequestV1,
        *,
        force_reextract: bool = False,
    ) -> EvidencePriorAnalysisResult:
        task = resolve_task(request)
        requirements = self.requirement_compiler.compile(task)
        run_id = f"evidence-prior-{uuid.uuid4().hex}"
        items = []
        misses = []
        candidates_by_requirement: dict[str, list[dict[str, Any]]] = {}
        acquisition_traces = {}
        knowledge_reused = 0
        llm_calls = 0

        for requirement in requirements:
            acquisition = self.acquisition.run(
                task,
                requirement,
                force_reextract=force_reextract,
            )
            candidates_by_requirement[requirement.requirement_id] = [
                candidate.model_dump(mode="json") for candidate in acquisition.candidates
            ]
            acquisition_traces[requirement.requirement_id] = acquisition.trace
            items.extend(acquisition.items)
            misses.extend(acquisition.misses)
            knowledge_reused += acquisition.knowledge_reused_count
            llm_calls += acquisition.llm_call_count

        evidence_set = EvidenceIRSetV2(
            evidence_set_id=f"evidence-set-{uuid.uuid4().hex}",
            items=items,
            misses=misses,
            paper_candidates=candidates_by_requirement,
            acquisition_traces=acquisition_traces,
            knowledge_reused_count=knowledge_reused,
            llm_call_count=llm_calls,
        )
        belief_set = compile_beliefs(task, evidence_set)
        prior_set = compile_priors(evidence_set, belief_set)
        warnings = _warnings(task, requirements, evidence_set, belief_set.beliefs, prior_set.priors)
        return EvidencePriorAnalysisResult(
            analysis_run_id=run_id,
            task=task,
            requirements=requirements,
            evidence=evidence_set,
            beliefs=belief_set,
            priors=prior_set,
            warnings=[*warnings, *prior_set.warnings],
        )


def resolve_task(request: TaskRequestV1) -> ResolvedTaskV1:
    snapshot = get_equipment_profile_revision(
        request.equipment_profile_id,
        request.equipment_revision_id,
    )
    laser = dict(snapshot.get("laser_source") or {})
    optical = dict(snapshot.get("optical_setup") or {})
    motion = dict(snapshot.get("motion_system") or {})
    pulse_fixed = _float(laser.get("pulse_width_fixed_fs"))
    pulse_min = pulse_fixed if pulse_fixed is not None else _float(laser.get("pulse_width_min_fs"))
    pulse_max = pulse_fixed if pulse_fixed is not None else _float(laser.get("pulse_width_max_fs"))
    rated = _float(laser.get("rated_max_power_W"))
    measured = _float(laser.get("measured_max_power_W"))
    transmission = _float(laser.get("power_transmission_ratio"))
    effective, effective_source = resolve_effective_max_power(laser)
    values = {
        "pulse_width_min_fs": pulse_min,
        "pulse_width_max_fs": pulse_max,
        "frequency_min_kHz": _float(laser.get("frequency_min_kHz")),
        "frequency_max_kHz": _float(laser.get("frequency_max_kHz")),
        "scan_speed_min_mm_s": _float(motion.get("scan_speed_min_mm_s")),
        "scan_speed_max_mm_s": _float(motion.get("scan_speed_max_mm_s")),
        "rated_max_power_W": rated,
    }
    missing = [key for key, value in values.items() if value is None]
    equipment = EquipmentContext(
        equipment_profile_id=request.equipment_profile_id,
        equipment_revision_id=request.equipment_revision_id,
        profile_name=str(snapshot.get("profile_name") or request.equipment_profile_id),
        wavelength_nm=_float(laser.get("wavelength_nm")),
        pulse_width_min_fs=pulse_min,
        pulse_width_max_fs=pulse_max,
        frequency_min_kHz=values["frequency_min_kHz"],
        frequency_max_kHz=values["frequency_max_kHz"],
        scan_speed_min_mm_s=values["scan_speed_min_mm_s"],
        scan_speed_max_mm_s=values["scan_speed_max_mm_s"],
        spot_diameter_um=_float(optical.get("spot_diameter_um")),
        rated_max_power_W=rated,
        measured_max_power_W=measured,
        power_transmission_ratio=transmission,
        effective_max_power_W=effective,
        effective_max_power_source=effective_source,
        missing_fields=missing,
    )
    return ResolvedTaskV1(
        material=request.material.strip(),
        material_grade=request.material_grade.strip() if request.material_grade else None,
        target_metric=request.target_metric,
        equipment=equipment,
    )


def _warnings(
    task: ResolvedTaskV1,
    requirements: list[Any],
    evidence_set: EvidenceIRSetV2,
    beliefs: list[Any],
    priors: list[Any],
) -> list[str]:
    warnings: list[str] = []
    if task.equipment.missing_fields:
        warnings.append(
            "设备档案缺少以下 V1 能力字段，相关适用性维度记为 UNKNOWN："
            + ", ".join(task.equipment.missing_fields)
        )
    valid_requirement_ids = {
        item.requirement_id
        for item in evidence_set.items
        if item.validation_state == ValidationState.VALIDATED
    }
    missing_requirements = [
        item.requirement_type.value
        for item in requirements
        if item.requirement_id not in valid_requirement_ids
    ]
    if missing_requirements:
        warnings.append("未获得机械校验通过的证据：" + ", ".join(missing_requirements))
    rejected = sum(item.validation_state == ValidationState.REJECTED for item in evidence_set.items)
    if rejected:
        warnings.append(f"{rejected} 条 LLM 抽取未通过机械校验，未进入 belief/prior。")
    governance = sorted(
        {
            item.governance_status
            for item in evidence_set.items
            if item.validation_state == ValidationState.VALIDATED
            and item.governance_status.casefold()
            not in {
                "approved",
                "accepted",
                "accepted_to_rag",
                "accepted_as_literature_evidence",
                "governed",
            }
        }
    )
    if governance:
        warnings.append(
            "治理提醒：结果包含 "
            + ", ".join(governance)
            + " 状态的结构化知识；治理状态未限制本次检索、抽取或 E2P。"
        )
    if not beliefs:
        warnings.append("没有可形成 EvidenceBelief 的已验证证据。")
    if not priors:
        warnings.append("没有形成可执行软先验；证据可能仅用于材料身份判断。")
    return warnings


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
