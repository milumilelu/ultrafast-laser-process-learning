"""Gleaning pass (O5) - contract §7.

Glean results NEVER enter the ledger directly: they re-run grounding and
anchor dedupe before becoming ScientificCandidates (a second pass must not
become a hallucination backdoor).
"""

from __future__ import annotations

from ultrafast_ingestion.discovery.backend import DiscoveryBackend
from ultrafast_ingestion.discovery.discoverer import (
    DiscoveredSkeleton,
    DiscoveryBatchBuilder,
    run_discovery,
)
from ultrafast_ingestion.discovery.models import (
    CandidateSkeleton,
    DiscoveryBatch,
)
from ultrafast_ingestion.models.document import ScientificDocument


def run_glean(
    document: ScientificDocument,
    batch: DiscoveryBatch,
    backend: DiscoveryBackend,
    existing: list[CandidateSkeleton],
) -> list[DiscoveredSkeleton]:
    """Pass 3: backend returns ONLY_NEW skeletons; binding is identical to Pass 1."""
    skeletons = backend.glean(batch, existing)
    ref_to_id = dict(zip(batch.window_refs, batch.window_ids))
    out: list[DiscoveredSkeleton] = []
    for skeleton in skeletons:
        ref = skeleton.window_local_ref
        if ref not in ref_to_id:
            raise ValueError(
                f"unknown window_local_ref {ref!r} in glean batch {batch.batch_id}"
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


def glean_over_document(
    document: ScientificDocument,
    backend: DiscoveryBackend,
    config=None,
    regions=None,
) -> list[DiscoveredSkeleton]:
    """Pass 1 then Pass 3 over every batch; return only gleaned skeletons.

    Pass 1 results of each batch form the `existing` list (deterministic
    order guarantees stable recorded replay).
    """
    batches = DiscoveryBatchBuilder(config, regions).build(document)
    first_pass = run_discovery(document, backend, config=config, regions=regions)
    by_batch: dict[str, list[CandidateSkeleton]] = {}
    for d in first_pass:
        by_batch.setdefault(d.batch_id, []).append(d.skeleton)
    gleaned: list[DiscoveredSkeleton] = []
    for batch in batches:
        existing = by_batch.get(batch.batch_id, [])
        gleaned.extend(run_glean(document, batch, backend, existing))
    return gleaned
