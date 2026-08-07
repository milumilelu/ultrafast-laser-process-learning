from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ultrafast_knowledge.literature.extraction import (
    EXTRACTION_METHODS,
    EXTRACTION_STATUSES,
    EXTRACTION_VERSION,
    ExtractionStatus,
    MaterialRole,
    ProcessRole,
)

MentionKind = Literal["material", "process"]


class MaterialMention(BaseModel):
    raw_text: str
    canonical_material_id: str
    material_grade: str = ""
    role: MaterialRole = MaterialRole.UNKNOWN
    page: int | None = None
    section_id: str | None = None
    section_type: str = ""
    evidence_span: tuple[int, int] | None = None
    extraction_method: str = "rule"
    confidence: float = 0.0

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, value: Any) -> MaterialRole:
        if value in (None, "", "unknown"):
            return MaterialRole.UNKNOWN
        try:
            return MaterialRole(str(value))
        except ValueError:
            return MaterialRole.UNKNOWN

    @field_validator("extraction_method", mode="before")
    @classmethod
    def _coerce_method(cls, value: Any) -> str:
        text = str(value or "rule")
        return text if text in EXTRACTION_METHODS else "rule"

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def as_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        if data.get("evidence_span") is not None:
            data["evidence_span"] = [int(data["evidence_span"][0]), int(data["evidence_span"][1])]
        return data


class ProcessMention(BaseModel):
    raw_text: str
    canonical_process_id: str
    role: ProcessRole = ProcessRole.UNKNOWN
    page: int | None = None
    section_id: str | None = None
    section_type: str = ""
    evidence_span: tuple[int, int] | None = None
    extraction_method: str = "rule"
    confidence: float = 0.0

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, value: Any) -> ProcessRole:
        if value in (None, "", "unknown"):
            return ProcessRole.UNKNOWN
        try:
            return ProcessRole(str(value))
        except ValueError:
            return ProcessRole.UNKNOWN

    @field_validator("extraction_method", mode="before")
    @classmethod
    def _coerce_method(cls, value: Any) -> str:
        text = str(value or "rule")
        return text if text in EXTRACTION_METHODS else "rule"

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def as_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        if data.get("evidence_span") is not None:
            data["evidence_span"] = [int(data["evidence_span"][0]), int(data["evidence_span"][1])]
        return data


class NumericEvidence(BaseModel):
    value: float
    unit: str = ""
    raw_evidence: str = ""
    page: int | None = None


class PaperMetadata(BaseModel):
    paper_id: str
    primary_material: list[str] = Field(default_factory=list)
    primary_material_grade: dict[str, str] = Field(default_factory=dict)
    primary_process: str = ""
    laser_type: str = ""
    wavelength_nm: NumericEvidence | None = None
    pulse_width: NumericEvidence | None = None
    geometry: str = ""
    material_mentions: list[MaterialMention] = Field(default_factory=list)
    process_mentions: list[ProcessMention] = Field(default_factory=list)
    extraction_status: str = "rule_only_abstained"
    extractor_version: str = EXTRACTION_VERSION
    warnings: list[str] = Field(default_factory=list)
    llm_usage: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extraction_status", mode="before")
    @classmethod
    def _coerce_status(cls, value: Any) -> str:
        text = str(value or ExtractionStatus.RULE_ONLY_ABSTAINED.value)
        return text if text in EXTRACTION_STATUSES else ExtractionStatus.FAILED.value

    def as_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["material_mentions"] = [item.as_dict() for item in self.material_mentions]
        data["process_mentions"] = [item.as_dict() for item in self.process_mentions]
        data["wavelength_nm"] = self.wavelength_nm.model_dump(mode="json") if self.wavelength_nm else None
        data["pulse_width"] = self.pulse_width.model_dump(mode="json") if self.pulse_width else None
        return data

    def mention_roles(self) -> dict[str, str]:
        """canonical id → 首个非 unknown role（RAG chunk 级过滤用）。"""
        roles: dict[str, str] = {}
        for mention in self.material_mentions:
            if mention.role != MaterialRole.UNKNOWN and mention.canonical_material_id not in roles:
                roles[mention.canonical_material_id] = str(mention.role.value)
        return roles

    def process_roles(self) -> dict[str, str]:
        roles: dict[str, str] = {}
        for mention in self.process_mentions:
            if mention.role != ProcessRole.UNKNOWN and mention.canonical_process_id not in roles:
                roles[mention.canonical_process_id] = str(mention.role.value)
        return roles
