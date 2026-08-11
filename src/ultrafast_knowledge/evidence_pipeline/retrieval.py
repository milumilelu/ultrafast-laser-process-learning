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
    SemanticBlock,
    SemanticBlockType,
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
        return self.retrieve_query(
            requirement,
            query.query_text,
            paper_top_k=paper_top_k,
            global_block_top_k=global_block_top_k,
            windows_per_paper=windows_per_paper,
            context_blocks=context_blocks,
        )

    def retrieve_query(
        self,
        requirement: Requirement,
        query_text: str,
        *,
        paper_top_k: int = 5,
        global_block_top_k: int = 40,
        windows_per_paper: int = 8,
        context_blocks: int = 1,
    ) -> tuple[list[PaperCandidate], dict[str, list[EvidenceWindow]]]:
        """Execute an explicit query without changing Requirement semantics."""

        if not query_text.strip():
            raise ValueError("query_text must not be empty")
        paper_hits = self.index.query("paper", query_text, top_k=max(paper_top_k * 3, paper_top_k))
        global_blocks = self.index.query(
            "block", query_text, top_k=max(global_block_top_k, paper_top_k)
        )
        candidates = self._candidate_union(paper_hits, global_blocks, paper_top_k)
        windows: dict[str, list[EvidenceWindow]] = {}
        for candidate in candidates:
            hits = self.index.query(
                "block",
                query_text,
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
        paper_title, paper_metadata = self.store.paper_context(document_version_id)
        by_id = {item.block_id: item for item in blocks}
        order = {item.block_id: index for index, item in enumerate(blocks)}
        windows: list[EvidenceWindow] = []
        for hit in hits:
            if not hit.block_id or hit.block_id not in by_id:
                continue
            center = by_id[hit.block_id]
            index = order[center.block_id]
            if center.block_type == SemanticBlockType.TABLE and center.table_id:
                members = self._table_window(center, blocks, by_id)
            else:
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
                    paper_title=paper_title,
                    paper_metadata=paper_metadata,
                    matched_terms=[],
                )
            )
        return sorted(windows, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _table_window(
        center: SemanticBlock,
        blocks: list[SemanticBlock],
        by_id: dict[str, SemanticBlock],
    ) -> list[SemanticBlock]:
        same_table = [item for item in blocks if item.table_id == center.table_id]
        summaries = [item for item in same_table if item.table_role == "summary"]
        rows = sorted(
            (item for item in same_table if item.table_role == "row"),
            key=lambda item: item.table_row_index if item.table_row_index is not None else -1,
        )
        selected_rows: list[SemanticBlock] = []
        if center.table_role == "row" and center in rows:
            row_position = rows.index(center)
            selected_rows = rows[max(0, row_position - 1) : row_position + 2]
        elif rows:
            selected_rows = rows[:2]
        captions = [
            by_id[related_id]
            for related_id in center.related_block_ids
            if related_id in by_id
            and by_id[related_id].block_type == SemanticBlockType.TABLE_CAPTION
        ]
        output: list[SemanticBlock] = []
        seen: set[str] = set()
        for item in [*captions[:1], *summaries[:1], *selected_rows]:
            if item.block_id not in seen:
                output.append(item)
                seen.add(item.block_id)
        return output

    @staticmethod
    def _candidate_key(candidate: PaperCandidate) -> str:
        return f"{candidate.paper_id}::{candidate.document_version_id}"
