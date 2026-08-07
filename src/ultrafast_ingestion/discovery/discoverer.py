"""Discovery pass orchestration (O2): batch builder + skeleton binding.

Contract: OPEN_SCIENTIFIC_DISCOVERY_V0_1 §2 (skeleton batch) / §4 (skeleton).

O2 scope: window -> batch aggregation and LLM response binding only.
No grounding (O3), no ledger ingestion (O4).
"""

from __future__ import annotations

from dataclasses import dataclass

from ultrafast_ingestion.discovery.backend import DiscoveryBackend
from ultrafast_ingestion.discovery.models import (
    CandidateSkeleton,
    DiscoveryBatch,
    DiscoveryWindowConfig,
)
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder
from ultrafast_ingestion.models.document import ScientificDocument
from ultrafast_ingestion.models.provenance import stable_hash
from ultrafast_ingestion.tables.models import TableRegion

LOCAL_REF_PREFIX = "w"


@dataclass(frozen=True, slots=True)
class DiscoveredSkeleton:
    """Skeleton bound to its window by code (LLM never returns ids, D5)."""

    skeleton: CandidateSkeleton
    paper_id: str
    document_version_id: str
    window_id: str
    batch_id: str


def _words(text: str) -> int:
    return len(text.split())


class DiscoveryBatchBuilder:
    """Aggregate windows into skeleton batches (contract §2)."""

    def __init__(
        self,
        config: DiscoveryWindowConfig | None = None,
        regions: list[TableRegion] | None = None,
    ) -> None:
        self.config = config or DiscoveryWindowConfig()
        self.window_builder = DiscoveryWindowBuilder(self.config, regions)

    def build(self, document: ScientificDocument) -> list[DiscoveryBatch]:
        windows = self.window_builder.build(document)
        batches: list[DiscoveryBatch] = []
        current: list = []
        current_words = 0
        target = self.config.target_batch_tokens
        max_tokens = self.config.max_batch_tokens

        def flush() -> None:
            nonlocal current, current_words
            if current:
                batches.append(self._batch_from_windows(document, current))
                current = []
                current_words = 0

        for window in windows:
            words = _words(window.text)
            if words > max_tokens:
                flush()
                batches.append(self._batch_from_windows(document, [window]))
                continue
            if current and current_words + words > target:
                flush()
            current.append(window)
            current_words += words
        flush()
        return batches

    def _batch_from_windows(
        self,
        document: ScientificDocument,
        windows: list,
    ) -> DiscoveryBatch:
        window_ids = tuple(w.window_id for w in windows)
        refs = tuple(f"{LOCAL_REF_PREFIX}{i}" for i in range(len(windows)))
        parts = [f"[{ref}]\n{w.text}" for ref, w in zip(refs, windows)]
        return DiscoveryBatch(
            batch_id=stable_hash(
                document.document_version_id,
                *window_ids,
                self.config.config_version(),
            ),
            paper_id=document.paper_id,
            document_version_id=document.document_version_id,
            window_config_version=self.config.config_version(),
            window_refs=refs,
            window_ids=window_ids,
            text="\n\n".join(parts),
        )


def run_discovery(
    document: ScientificDocument,
    backend: DiscoveryBackend,
    config: DiscoveryWindowConfig | None = None,
    regions: list[TableRegion] | None = None,
) -> list[DiscoveredSkeleton]:
    """Run Pass 1 over all batches; bind window_local_ref -> window_id (G: local refs only)."""
    batches = DiscoveryBatchBuilder(config, regions).build(document)
    out: list[DiscoveredSkeleton] = []
    for batch in batches:
        ref_to_id = dict(zip(batch.window_refs, batch.window_ids))
        skeletons = backend.discover(batch)
        for skeleton in skeletons:
            ref = skeleton.window_local_ref
            if ref not in ref_to_id:
                raise ValueError(
                    f"unknown window_local_ref {ref!r} in batch {batch.batch_id} "
                    f"(known: {list(ref_to_id)})"
                )
            out.append(
                DiscoveredSkeleton(
                    skeleton=skeleton,
                    paper_id=document.paper_id,
                    document_version_id=document.document_version_id,
                    window_id=ref_to_id[ref],
                    batch_id=batch.batch_id,
                )
            )
    return out
