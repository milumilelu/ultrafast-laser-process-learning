"""Independent Requirement Compiler + Literature Evidence Pipeline service."""

from __future__ import annotations

import hashlib

from ultrafast_knowledge.evidence_pipeline.extraction import RequirementEvidenceExtractor
from ultrafast_knowledge.evidence_pipeline.repository import DatabaseScientificPaperRepository
from ultrafast_knowledge.evidence_pipeline.retrieval import TwoLevelEvidenceRetriever
from ultrafast_knowledge.evidence_pipeline.schemas import (
    RequirementEvidenceRun,
    StructuredScientificPaper,
)
from ultrafast_requirements.schemas import (
    RequirementCategory,
    RequirementSet,
    RequirementSource,
)


class RequirementEvidencePipeline:
    def __init__(
        self,
        extractor: RequirementEvidenceExtractor,
        *,
        retriever: TwoLevelEvidenceRetriever | None = None,
        repository: DatabaseScientificPaperRepository | None = None,
    ) -> None:
        self.extractor = extractor
        self.retriever = retriever or TwoLevelEvidenceRetriever()
        self.repository = repository

    def analyze(
        self,
        requirement_set: RequirementSet,
        *,
        papers: list[StructuredScientificPaper] | None = None,
        paper_top_k: int = 5,
        window_top_k: int = 8,
    ) -> RequirementEvidenceRun:
        digest = hashlib.sha256(requirement_set.requirement_set_id.encode("utf-8")).hexdigest()[:16]
        run = RequirementEvidenceRun(
            run_id=f"evidence-{digest}",
            requirement_set_id=requirement_set.requirement_set_id,
        )
        literature_requirements = [
            item
            for item in requirement_set.requirements
            if item.category == RequirementCategory.KNOWLEDGE_REQUIREMENT
            and RequirementSource.LITERATURE in item.acceptable_sources
        ]
        for requirement in literature_requirements:
            current_papers = papers
            if current_papers is None:
                if self.repository is None:
                    raise ValueError("papers or a scientific paper repository is required")
                current_papers, warnings = self.repository.load_for_requirement(
                    requirement, top_k=paper_top_k
                )
                run.warnings.extend(warnings)
            candidates, windows = self.retriever.retrieve(
                requirement,
                current_papers,
                paper_top_k=paper_top_k,
                window_top_k=window_top_k,
            )
            run.paper_candidates[requirement.requirement_id] = candidates
            run.evidence_windows[requirement.requirement_id] = windows
            run.results.append(self.extractor.extract(requirement, windows))
        return run
