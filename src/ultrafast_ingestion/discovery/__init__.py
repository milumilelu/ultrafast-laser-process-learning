"""Open Scientific Discovery V0.1 (O1-O3: windows, batches, recorded backend,
deterministic grounding).

Contract: docs/contracts/OPEN_SCIENTIFIC_DISCOVERY_V0_1.md (FROZEN).
"""

from __future__ import annotations

from ultrafast_ingestion.discovery.backend import (
    DiscoveryBackend,
    RecordedDiscoveryBackend,
)
from ultrafast_ingestion.discovery.discoverer import (
    DiscoveredSkeleton,
    DiscoveryBatchBuilder,
    run_discovery,
)
from ultrafast_ingestion.discovery.filler import (
    CandidateFiller,
    GateFailError,
    scientific_candidate_from,
)
from ultrafast_ingestion.discovery.gleaner import glean_over_document, run_glean
from ultrafast_ingestion.discovery.grounder import CandidateGrounder
from ultrafast_ingestion.discovery.merge import (
    ledger_with_discovered,
    merge_into_ledger,
    route_ledger,
)
from ultrafast_ingestion.discovery.models import (
    WINDOW_CONFIG_VERSION,
    CandidateDetail,
    CandidateSkeleton,
    CandidateVerification,
    DiscoveryBatch,
    DiscoveryWindow,
    DiscoveryWindowConfig,
    GroundingConfig,
    GroundingMatchType,
    GroundingResult,
    SourceSemantics,
)
from ultrafast_ingestion.discovery.schema_gap import gap_report, schema_gaps
from ultrafast_ingestion.discovery.verifier import (
    CandidateVerifier,
    apply_verification,
    tier_for,
)
from ultrafast_ingestion.discovery.windows import DiscoveryWindowBuilder

__all__ = [
    "WINDOW_CONFIG_VERSION",
    "CandidateDetail",
    "CandidateFiller",
    "CandidateGrounder",
    "CandidateSkeleton",
    "CandidateVerification",
    "CandidateVerifier",
    "DiscoveredSkeleton",
    "DiscoveryBackend",
    "DiscoveryBatch",
    "DiscoveryBatchBuilder",
    "DiscoveryWindow",
    "DiscoveryWindowBuilder",
    "DiscoveryWindowConfig",
    "GateFailError",
    "GroundingConfig",
    "GroundingMatchType",
    "GroundingResult",
    "RecordedDiscoveryBackend",
    "SourceSemantics",
    "apply_verification",
    "gap_report",
    "glean_over_document",
    "ledger_with_discovered",
    "merge_into_ledger",
    "route_ledger",
    "run_discovery",
    "run_glean",
    "schema_gaps",
    "scientific_candidate_from",
    "tier_for",
]
