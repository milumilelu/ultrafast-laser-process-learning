"""Requirement-specific paper Map, structured knowledge ingestion and Reduce."""

from __future__ import annotations

import hashlib
from typing import Any

from ultrafast_knowledge.evidence_pipeline.aggregation import (
    CrossPaperEvidenceAggregator,
)
from ultrafast_knowledge.evidence_pipeline.extraction import RequirementEvidenceExtractor
from ultrafast_knowledge.evidence_pipeline.repository import (
    PersistentScientificPaperRepository,
)
from ultrafast_knowledge.evidence_pipeline.schemas import (
    EvidenceWindow,
    ExtractionStatus,
    PaperCandidate,
    PaperEvidence,
    RequirementEvidence,
    RequirementEvidenceRun,
)
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore
from ultrafast_requirements.schemas import (
    CalibrationRequirement,
    Requirement,
    RequirementCategory,
    RequirementSet,
    RequirementSource,
    RequirementStatus,
    ResolutionStatus,
    ResolutionStep,
)

EXTRACTION_SCHEMA_VERSION = "requirement-evidence-v2"


class RequirementEvidencePipeline:
    def __init__(
        self,
        extractor: RequirementEvidenceExtractor,
        *,
        repository: PersistentScientificPaperRepository,
        store: ScientificIndexStore,
        aggregator: CrossPaperEvidenceAggregator | None = None,
    ) -> None:
        self.extractor = extractor
        self.repository = repository
        self.store = store
        self.aggregator = aggregator or CrossPaperEvidenceAggregator()

    def analyze(
        self,
        requirement_set: RequirementSet,
        *,
        paper_top_k: int = 5,
        window_top_k: int = 8,
    ) -> RequirementEvidenceRun:
        digest = hashlib.sha256(requirement_set.requirement_set_id.encode()).hexdigest()[:16]
        run = RequirementEvidenceRun(
            run_id=f"evidence-{digest}",
            requirement_set_id=requirement_set.requirement_set_id,
        )
        for requirement in self._literature_requirements(requirement_set):
            candidates, windows_by_paper = self.repository.retrieve(
                requirement,
                paper_top_k=paper_top_k,
                windows_per_paper=window_top_k,
            )
            run.paper_candidates[requirement.requirement_id] = candidates
            run.evidence_windows[requirement.requirement_id] = [
                window
                for candidate in candidates
                for window in windows_by_paper.get(self._candidate_key(candidate), [])
            ]
            mapped = self._map_papers(requirement, candidates, windows_by_paper)
            run.paper_evidence[requirement.requirement_id] = mapped
            self._ingest_valid_findings(requirement, mapped)

            knowledge = self.repository.structured_knowledge(requirement)
            reducible = self._knowledge_evidence(requirement, knowledge)
            reducible.extend(
                item
                for item in mapped
                if item.evidence.status != ExtractionStatus.FOUND
            )
            result = self.aggregator.aggregate(requirement, reducible)
            run.results.append(result)
            self._append_governance_warnings(run, requirement, knowledge)
            if result.status in {
                ExtractionStatus.NOT_FOUND,
                ExtractionStatus.INSUFFICIENT,
            }:
                fallback = self._calibration_fallback(requirement, result.status)
                run.fallback_requirements.append(fallback.model_dump(mode="json"))
        return run

    @staticmethod
    def _literature_requirements(requirement_set: RequirementSet) -> list[Requirement]:
        return [
            item
            for item in requirement_set.requirements
            if item.category == RequirementCategory.KNOWLEDGE_REQUIREMENT
            and RequirementSource.LITERATURE in item.acceptable_sources
        ]

    def _map_papers(
        self,
        requirement: Requirement,
        candidates: list[PaperCandidate],
        windows_by_paper: dict[str, list[EvidenceWindow]],
    ) -> list[PaperEvidence]:
        return [
            PaperEvidence(
                paper_id=candidate.paper_id,
                document_version_id=candidate.document_version_id,
                evidence=self.extractor.extract(
                    requirement,
                    windows_by_paper.get(self._candidate_key(candidate), []),
                ),
            )
            for candidate in candidates
        ]

    @staticmethod
    def _candidate_key(candidate: PaperCandidate) -> str:
        return f"{candidate.paper_id}::{candidate.document_version_id}"

    def _ingest_valid_findings(
        self,
        requirement: Requirement,
        mapped: list[PaperEvidence],
    ) -> None:
        for item in mapped:
            if not item.evidence.valid or item.evidence.status != ExtractionStatus.FOUND:
                continue
            item.knowledge_id = self.store.upsert_knowledge(
                requirement,
                item.evidence,
                paper_id=item.paper_id,
                document_version_id=item.document_version_id,
                extractor_model=self.extractor.model,
                extraction_schema_version=EXTRACTION_SCHEMA_VERSION,
            )

    @staticmethod
    def _knowledge_evidence(
        requirement: Requirement,
        rows: list[dict[str, Any]],
    ) -> list[PaperEvidence]:
        output: list[PaperEvidence] = []
        for row in rows:
            evidence = RequirementEvidence(
                requirement_id=requirement.requirement_id,
                quantity=str(row["quantity"]),
                status=str(row["extraction_status"]),
                value=row.get("value"),
                lower=row.get("lower"),
                upper=row.get("upper"),
                unit=row.get("unit"),
                conditions=dict(row.get("conditions") or {}),
                semantic_role=row.get("semantic_role"),
                source_block_refs=list(row.get("source_block_refs") or []),
                confidence=float(row.get("confidence") or 0.0),
                evidence_quote=row.get("evidence_quote"),
                validation_state=str(row.get("validation_state") or "pending"),
                governance_status=str(row.get("governance_status") or "unreviewed"),
                prompt_version=str(row.get("prompt_version") or "unknown"),
            )
            output.append(
                PaperEvidence(
                    paper_id=str(row["paper_id"]),
                    document_version_id=str(row["document_version_id"]),
                    evidence=evidence,
                    route="structured_knowledge",
                    knowledge_id=str(row["knowledge_id"]),
                )
            )
        return output

    @staticmethod
    def _append_governance_warnings(
        run: RequirementEvidenceRun,
        requirement: Requirement,
        rows: list[dict[str, Any]],
    ) -> None:
        statuses = sorted(
            {
                str(row.get("governance_status") or "unreviewed")
                for row in rows
                if str(row.get("governance_status") or "unreviewed") != "approved"
            }
        )
        if statuses:
            run.governance_warnings.append(
                f"{requirement.requirement_id}: structured knowledge governance="
                f"{','.join(statuses)}; retrieval and extraction were not restricted"
            )

    @staticmethod
    def _calibration_fallback(
        requirement: Requirement,
        result_status: ExtractionStatus,
    ) -> CalibrationRequirement:
        reason = f"literature_resolution_{result_status.value.lower()}"
        steps: list[ResolutionStep] = []
        for source in (RequirementSource.STRUCTURED_KNOWLEDGE, RequirementSource.LITERATURE):
            steps.append(
                ResolutionStep(
                    order=len(steps) + 1,
                    source=source,
                    status=ResolutionStatus.FAILED,
                    failure_reason=reason,
                )
            )
        steps.extend(
            [
                ResolutionStep(
                    order=len(steps) + 1,
                    source=RequirementSource.CALIBRATION,
                ),
                ResolutionStep(
                    order=len(steps) + 2,
                    source=RequirementSource.UNRESOLVED,
                ),
            ]
        )
        digest = hashlib.sha256(f"{requirement.requirement_id}:calibration".encode()).hexdigest()
        return CalibrationRequirement(
            **{
                **requirement.model_dump(
                    exclude={
                        "requirement_id",
                        "category",
                        "acceptable_sources",
                        "resolution_policy",
                        "resolution_chain",
                        "current_resolution_step",
                    }
                ),
                "requirement_id": f"calibration-{digest[:16]}",
                "acceptable_sources": [
                    RequirementSource.CALIBRATION,
                    RequirementSource.UNRESOLVED,
                ],
                "resolution_policy": "run_targeted_calibration_then_mark_unresolved",
                "status": RequirementStatus.MISSING,
                "resolution_chain": steps,
                "current_resolution_step": 2,
            }
        )
