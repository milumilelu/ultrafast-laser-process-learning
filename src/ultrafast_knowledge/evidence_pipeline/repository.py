"""Online repository over persistent scientific indexes and structured knowledge."""

from __future__ import annotations

from ultrafast_knowledge.evidence_pipeline.retrieval import TwoLevelEvidenceRetriever
from ultrafast_knowledge.evidence_pipeline.schemas import EvidenceWindow, PaperCandidate
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore
from ultrafast_requirements.schemas import Requirement


class PersistentScientificPaperRepository:
    def __init__(
        self,
        store: ScientificIndexStore,
        *,
        retriever: TwoLevelEvidenceRetriever | None = None,
    ) -> None:
        self.store = store
        self.retriever = retriever or TwoLevelEvidenceRetriever(store)

    def retrieve(
        self,
        requirement: Requirement,
        *,
        paper_top_k: int = 5,
        windows_per_paper: int = 8,
    ) -> tuple[list[PaperCandidate], dict[str, list[EvidenceWindow]]]:
        return self.retriever.retrieve(
            requirement,
            paper_top_k=paper_top_k,
            windows_per_paper=windows_per_paper,
        )

    def retrieve_query(
        self,
        requirement: Requirement,
        query_text: str,
        *,
        paper_top_k: int = 5,
        windows_per_paper: int = 8,
    ) -> tuple[list[PaperCandidate], dict[str, list[EvidenceWindow]]]:
        return self.retriever.retrieve_query(
            requirement,
            query_text,
            paper_top_k=paper_top_k,
            windows_per_paper=windows_per_paper,
        )

    def structured_knowledge(self, requirement: Requirement) -> list[dict]:
        return self.store.query_knowledge(requirement)
