"""Scientific Metadata Extractor V2 编排（P0-A 主链中间层）。

    Sections → Rule Candidates → LLM Semantic Roles → Ontology/Validator
              → PaperMetadata（material/process mentions + primary 字段）

无 LLM 时角色 abstain（unknown），primary 保持空——允许 unknown，禁止猜。
"""

from __future__ import annotations

from typing import Any

from ultrafast_knowledge.literature.extraction import EXTRACTION_VERSION, ExtractionStatus
from ultrafast_knowledge.literature.extraction.candidates import (
    detect_geometry,
    detect_grades,
    detect_laser_type,
    detect_material_candidates,
    detect_process_candidates,
    detect_pulse_width,
    detect_wavelength,
)
from ultrafast_knowledge.literature.extraction.schemas import PaperMetadata
from ultrafast_knowledge.literature.extraction.semantic_roles import (
    apply_llm_roles,
    extract_llm_fields,
    run_llm_role_extraction,
)
from ultrafast_knowledge.literature.extraction.validator import finalize


def build_extraction_llm_client() -> Any | None:
    """真实 LLM client；未配置/无 Key → None（abstain，不使用 mock 做语义裁决）。"""
    try:
        from ultrafast_memory.core.llm_config import get_llm_config, restore_api_key_from_store
        from ultrafast_memory.llm.factory import create_llm_client
        from ultrafast_memory.llm.mock import MockLLMClient
    except (ImportError, ModuleNotFoundError):
        return None
    try:
        restore_api_key_from_store()
        config = get_llm_config()
    except Exception:  # noqa: BLE001 — LLM 基础设施不可用时 abstain，不阻断文献批量摄入
        return None
    client = create_llm_client(config)
    if isinstance(client, MockLLMClient):
        return None
    return client


def extract_paper_metadata(
    paper_id: str,
    sections: list[Any],
    *,
    page_count: int | None = None,
    llm_client: Any | None = None,
    paper_title: str = "",
    temperature: float | None = None,
) -> PaperMetadata:
    full_text = "\n\n".join((section.text or "") for section in sections)
    material_candidates = detect_material_candidates(sections)
    process_candidates = detect_process_candidates(sections)

    metadata = PaperMetadata(
        paper_id=paper_id,
        material_mentions=material_candidates,
        process_mentions=process_candidates,
        laser_type=detect_laser_type(full_text),
        wavelength_nm=detect_wavelength(full_text),
        pulse_width=detect_pulse_width(full_text),
        primary_material_grade=detect_grades(full_text),
        geometry=detect_geometry(full_text),
        extractor_version=EXTRACTION_VERSION,
        extraction_status=ExtractionStatus.RULE_ONLY_ABSTAINED.value,
    )
    if metadata.wavelength_nm is not None:
        metadata.wavelength_nm.page = _evidence_page(sections, metadata.wavelength_nm.raw_evidence)
    if metadata.pulse_width is not None:
        metadata.pulse_width.page = _evidence_page(sections, metadata.pulse_width.raw_evidence)

    section_dicts = [
        {"text": section.text, "section_type": section.section_type, "page_start": section.page_start}
        for section in sections
    ]
    if llm_client is not None:
        payload, usage, llm_error = run_llm_role_extraction(
            llm_client,
            paper_title=paper_title,
            sections=section_dicts,
            material_candidates=material_candidates,
            process_candidates=process_candidates,
            temperature=temperature,
        )
        if payload:
            apply_llm_roles(material_candidates, process_candidates, payload)
            fields = extract_llm_fields(payload)
            # A usable semantic response is authoritative for semantic fields.
            # Explicit unknown/null must clear rule guesses rather than silently
            # retaining a regex hit that the model could not confirm.
            metadata.laser_type = fields["laser_type"]
            metadata.wavelength_nm = (
                _numeric_evidence(fields["wavelength_nm"], "nm")
                if fields["wavelength_nm"] is not None
                else None
            )
            metadata.pulse_width = None
            if fields["pulse_width"] is not None:
                metadata.pulse_width = _numeric_evidence(
                    fields["pulse_width"]["value"], fields["pulse_width"]["unit"], fields["pulse_width"]["raw_evidence"]
                )
            metadata.primary_material_grade = fields["material_grade"]
            metadata.geometry = fields["geometry"]
            metadata.extraction_status = ExtractionStatus.EXTRACTED_WITH_LLM.value
            metadata.llm_usage = usage
        else:
            metadata.warnings.append(
                f"LLM role extraction failed after retries: {llm_error or 'no usable payload'}; roles abstained as unknown"
            )

    return finalize(
        metadata,
        page_count=page_count if page_count and page_count > 0 else (max((s.page_end or 1) for s in sections) if sections else 1),
    )


def _numeric_evidence(value: float, unit: str, evidence: str = "") -> Any:
    from ultrafast_knowledge.literature.extraction.schemas import NumericEvidence

    return NumericEvidence(value=value, unit=unit, raw_evidence=evidence)


def _evidence_page(sections: list[Any], raw_evidence: str) -> int | None:
    for section in sections:
        if raw_evidence and raw_evidence in (section.text or ""):
            return section.page_start
    return None
