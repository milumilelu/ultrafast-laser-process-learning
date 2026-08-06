"""Canonical governed soft-prior container shared by Topic2 and Agent adapters.

Migrated from legacy `packages/e2p/application/prior_artifact.py` (V2 §2:
MIGRATE). The legacy `ultrafast_e2p` copy was a sys.path-injecting shim and
is replaced by this canonical implementation (GAP-06 resolution).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

SELF_ATTESTED = "self_attested"
REPOSITORY_VERIFIED = "repository_verified"
COMPILER_VERSION_KEY = "prior_compiler_version"


@dataclass(frozen=True, slots=True)
class GovernedPriorArtifact:
    """Immutable prior plus its approval, evidence, scope and integrity chain."""

    prior_spec: dict[str, Any]
    approval_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    source_trace: tuple[dict[str, Any], ...] = ()
    compiler_version: str = "e2p-prior-spec-v1"
    scope: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    verification: str = SELF_ATTESTED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {
            **data,
            "approval_ids": list(self.approval_ids),
            "evidence_ids": list(self.evidence_ids),
            "source_trace": list(self.source_trace),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GovernedPriorArtifact:
        return cls(
            prior_spec=dict(data.get("prior_spec") or {}),
            approval_ids=tuple(data.get("approval_ids") or ()),
            evidence_ids=tuple(data.get("evidence_ids") or ()),
            source_trace=tuple(data.get("source_trace") or ()),
            compiler_version=str(
                data.get("compiler_version") or "e2p-prior-spec-v1"
            ),
            scope=dict(data.get("scope") or {}),
            content_hash=str(data.get("content_hash") or ""),
            verification=str(data.get("verification") or SELF_ATTESTED),
        )


def compute_prior_content_hash(
    prior_spec: dict[str, Any],
    approval_ids: list[str],
    scope: dict[str, Any],
    compiler_version: str,
) -> str:
    """Bind prior payload, approvals, scope and compiler into a stable digest."""
    payload = {
        "prior_spec": prior_spec,
        "approval_ids": sorted(set(approval_ids)),
        "scope": {
            key: value for key, value in sorted(scope.items()) if value is not None
        },
        "compiler_version": compiler_version,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "COMPILER_VERSION_KEY",
    "REPOSITORY_VERIFIED",
    "SELF_ATTESTED",
    "GovernedPriorArtifact",
    "compute_prior_content_hash",
]
