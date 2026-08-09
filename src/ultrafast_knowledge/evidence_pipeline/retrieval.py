"""Two-level retrieval: papers first, semantic evidence blocks second."""

from __future__ import annotations

import hashlib
import math
from collections import Counter

from ultrafast_knowledge.evidence_pipeline.query import RequirementQueryCompiler, tokenize
from ultrafast_knowledge.evidence_pipeline.schemas import (
    EvidenceWindow,
    PaperCandidate,
    RequirementQuery,
    SemanticBlock,
    StructuredScientificPaper,
)
from ultrafast_requirements.schemas import Requirement


class TwoLevelEvidenceRetriever:
    def __init__(self, query_compiler: RequirementQueryCompiler | None = None) -> None:
        self.query_compiler = query_compiler or RequirementQueryCompiler()

    def retrieve(
        self,
        requirement: Requirement,
        papers: list[StructuredScientificPaper],
        *,
        paper_top_k: int = 5,
        window_top_k: int = 8,
        context_blocks: int = 1,
    ) -> tuple[list[PaperCandidate], list[EvidenceWindow]]:
        query = self.query_compiler.compile(requirement)
        candidates = self.retrieve_papers(query, papers, top_k=paper_top_k)
        selected_ids = {item.paper_id for item in candidates}
        windows: list[EvidenceWindow] = []
        for paper in papers:
            if paper.paper_id not in selected_ids:
                continue
            windows.extend(
                self.retrieve_in_paper(
                    requirement,
                    query,
                    paper,
                    top_k=window_top_k,
                    context_blocks=context_blocks,
                )
            )
        windows.sort(key=lambda item: item.score, reverse=True)
        return candidates, windows[:window_top_k]

    def retrieve_papers(
        self,
        query: RequirementQuery,
        papers: list[StructuredScientificPaper],
        *,
        top_k: int = 5,
    ) -> list[PaperCandidate]:
        ranked: list[PaperCandidate] = []
        for paper in papers:
            metadata_text = " ".join(
                str(value) for value in paper.metadata.values() if value is not None
            )
            tokens = tokenize(f"{paper.title} {paper.abstract} {metadata_text}")
            score, matched = self._score_tokens(query, tokens, metadata=True)
            # A one-paper explicit corpus is still a valid candidate even if its
            # metadata is incomplete; stage two must decide whether evidence exists.
            if score > 0 or len(papers) == 1:
                ranked.append(PaperCandidate(paper_id=paper.paper_id, score=score, matched_terms=matched))
        return sorted(ranked, key=lambda item: item.score, reverse=True)[:top_k]

    def retrieve_in_paper(
        self,
        requirement: Requirement,
        query: RequirementQuery,
        paper: StructuredScientificPaper,
        *,
        top_k: int = 8,
        context_blocks: int = 1,
    ) -> list[EvidenceWindow]:
        del requirement
        scored: list[tuple[float, list[str], int, SemanticBlock]] = []
        document_frequency: Counter[str] = Counter()
        block_tokens: list[list[str]] = []
        for block in paper.blocks:
            tokens = tokenize(block.text)
            block_tokens.append(tokens)
            document_frequency.update(set(tokens))
        count = max(1, len(paper.blocks))
        for index, (block, tokens) in enumerate(zip(paper.blocks, block_tokens, strict=True)):
            score, matched = self._score_tokens(query, tokens, metadata=False)
            for term in matched:
                score += math.log((count + 1) / (document_frequency[term] + 1)) * 0.2
            if block.section_type == "references":
                score *= 0.15
            if score > 0:
                scored.append((score, matched, index, block))
        scored.sort(key=lambda item: item[0], reverse=True)
        windows: list[EvidenceWindow] = []
        used_centers: set[str] = set()
        for score, matched, index, block in scored:
            if block.block_id in used_centers:
                continue
            start = max(0, index - max(0, context_blocks))
            end = min(len(paper.blocks), index + max(0, context_blocks) + 1)
            members = list(paper.blocks[start:end])
            related_ids = set(block.related_block_ids)
            for candidate in paper.blocks:
                if candidate.block_id in related_ids and candidate not in members:
                    members.append(candidate)
            reading_order = {item.block_id: position for position, item in enumerate(paper.blocks)}
            members.sort(key=lambda item: reading_order[item.block_id])
            digest = hashlib.sha256(
                f"{query.requirement_id}\n{paper.paper_id}\n{block.block_id}".encode()
            ).hexdigest()[:16]
            windows.append(
                EvidenceWindow(
                    window_id=f"window-{digest}",
                    requirement_id=query.requirement_id,
                    paper_id=paper.paper_id,
                    center_block_id=block.block_id,
                    blocks=members,
                    score=round(score, 6),
                    matched_terms=matched,
                )
            )
            used_centers.add(block.block_id)
            if len(windows) >= top_k:
                break
        return windows

    @staticmethod
    def _score_tokens(
        query: RequirementQuery,
        tokens: list[str],
        *,
        metadata: bool,
    ) -> tuple[float, list[str]]:
        counts = Counter(tokens)
        matched: list[str] = []
        score = 0.0
        for term in query.core_terms:
            if counts[term]:
                matched.append(term)
                score += (2.2 if metadata else 3.0) * min(2, counts[term])
        for term in query.condition_terms:
            if counts[term]:
                matched.append(term)
                score += 1.8 * min(2, counts[term])
        for term in query.unit_terms:
            if counts[term]:
                matched.append(term)
                score += 0.7
        return score, list(dict.fromkeys(matched))
