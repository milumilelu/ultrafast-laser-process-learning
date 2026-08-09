"""Dual-index retrieval with global-block recall fallback and in-paper windows."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from ultrafast_knowledge.evidence_pipeline.hybrid_index import HybridScientificIndex
from ultrafast_knowledge.evidence_pipeline.query import RequirementQueryCompiler
from ultrafast_knowledge.evidence_pipeline.schemas import (
    EvidenceWindow,
    HybridIndexHit,
    PaperCandidate,
)
from ultrafast_knowledge.evidence_pipeline.store import ScientificIndexStore
from ultrafast_requirements.schemas import Requirement


class TwoLevelEvidenceRetriever:
    """Paper Index + Global Block Index → candidates → in-paper Block Index."""

    def __init__(
        self,
        store: ScientificIndexStore,
        *,
        index: HybridScientificIndex | None = None,
        query_compiler: RequirementQueryCompiler | None = None,
    ) -> None:
        self.store = store
        self.index = index or HybridScientificIndex(store)
        self.query_compiler = query_compiler or RequirementQueryCompiler()

    def retrieve(
        self,
        requirement: Requirement,
        *,
        paper_top_k: int = 5,
        global_block_top_k: int = 40,
        windows_per_paper: int = 8,
        context_blocks: int = 1,
    ) -> tuple[list[PaperCandidate], dict[str, list[EvidenceWindow]]]:
        query = self.query_compiler.compile(requirement)
        paper_hits = self.index.query(
            "paper", query.query_text, top_k=max(paper_top_k * 3, paper_top_k)
        )
        global_blocks = self.index.query(
            "block", query.query_text, top_k=max(global_block_top_k, paper_top_k)
        )
        candidates = self._candidate_union(paper_hits, global_blocks, paper_top_k)
        windows: dict[str, list[EvidenceWindow]] = {}
        for candidate in candidates:
            hits = self.index.query(
                "block",
                query.query_text,
                top_k=windows_per_paper,
                document_version_ids={candidate.document_version_id},
            )
            windows[self._candidate_key(candidate)] = self._windows_for_paper(
                requirement,
                candidate.paper_id,
                candidate.document_version_id,
                hits,
                context_blocks=context_blocks,
            )
        return candidates, windows

    @staticmethod
    def _candidate_union(
        paper_hits: list[HybridIndexHit],
        block_hits: list[HybridIndexHit],
        top_k: int,
    ) -> list[PaperCandidate]:
        scores: defaultdict[tuple[str, str], float] = defaultdict(float)
        paper_scores: defaultdict[tuple[str, str], float] = defaultdict(float)
        block_scores: defaultdict[tuple[str, str], float] = defaultdict(float)
        routes: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
        for rank, hit in enumerate(paper_hits, 1):
            key = (hit.paper_id, hit.document_version_id)
            scores[key] += 1.0 / (60 + rank)
            paper_scores[key] = max(paper_scores[key], hit.rerank_score)
            routes[key].append("paper_index")
        seen_block_papers: set[tuple[str, str]] = set()
        for rank, hit in enumerate(block_hits, 1):
            key = (hit.paper_id, hit.document_version_id)
            if key not in seen_block_papers:
                scores[key] += 1.0 / (60 + rank)
                seen_block_papers.add(key)
            block_scores[key] = max(block_scores[key], hit.rerank_score)
            routes[key].append("global_block_index")
        output = [
            PaperCandidate(
                paper_id=key[0],
                document_version_id=key[1],
                score=score,
                paper_index_score=paper_scores[key],
                global_block_score=block_scores[key],
                retrieval_routes=list(dict.fromkeys(routes[key])),
            )
            for key, score in scores.items()
        ]
        return sorted(output, key=lambda item: item.score, reverse=True)[:top_k]

    def _windows_for_paper(
        self,
        requirement: Requirement,
        paper_id: str,
        document_version_id: str,
        hits: list[HybridIndexHit],
        *,
        context_blocks: int,
    ) -> list[EvidenceWindow]:
        blocks = self.store.blocks(document_version_id=document_version_id)
        by_id = {item.block_id: item for item in blocks}
        order = {item.block_id: index for index, item in enumerate(blocks)}
        windows: list[EvidenceWindow] = []
        for hit in hits:
            if not hit.block_id or hit.block_id not in by_id:
                continue
            center = by_id[hit.block_id]
            index = order[center.block_id]
            members = list(
                blocks[
                    max(0, index - context_blocks) : min(
                        len(blocks), index + context_blocks + 1
                    )
                ]
            )
            for related_id in center.related_block_ids:
                related = by_id.get(related_id)
                if related is not None and related not in members:
                    members.append(related)
            members.sort(key=lambda item: order[item.block_id])
            score = hit.rerank_score * (0.15 if center.section_type == "references" else 1.0)
            digest = hashlib.sha256(
                f"{requirement.requirement_id}\n{paper_id}\n{center.block_id}".encode()
            ).hexdigest()[:16]
            windows.append(
                EvidenceWindow(
                    window_id=f"window-{digest}",
                    requirement_id=requirement.requirement_id,
                    paper_id=paper_id,
                    center_block_id=center.block_id,
                    blocks=members,
                    score=score,
                    matched_terms=[],
                )
            )
        return sorted(windows, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _candidate_key(candidate: PaperCandidate) -> str:
        return f"{candidate.paper_id}::{candidate.document_version_id}"
