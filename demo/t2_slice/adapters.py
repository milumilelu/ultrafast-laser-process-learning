"""Demo V2 adapters: CSV→BOSample, ledger→EvidenceClaim, claims→priors.

Contract: docs/contracts/T2_VERTICAL_SLICE_V0_1.md §3/§5.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ultrafast_bo.domain.models import BOSample
from ultrafast_e2p.domain.evidence import EvidenceClaim
from ultrafast_ingestion.candidates.models import (
    CandidateLedger,
    CandidateSourceType,
    MappingStatus,
)

# canonical parameter -> machine_bounds / BO x_parameter key
PARAM_TO_BOUNDS_KEY = {
    "frequency": "frequency_kHz",
    "pulse_width": "pulse_width_ps",
    "scan_speed": "scan_speed_mm_s",
    "hatch_spacing": "hatch_spacing_um",
    "passes": "passes",
}

# deterministic unit conversion: mention normalized_unit -> bounds key factor.
# Units outside the family are skipped (claim stays in the ledger, never deleted).
UNIT_CONVERSION: dict[str, dict[str, float]] = {
    "pulse_width_ps": {"fs": 0.001, "ps": 1.0},
    "frequency_kHz": {"kHz": 1.0, "MHz": 1000.0, "Hz": 0.001},
    "hatch_spacing_um": {"um": 1.0, "mm": 1000.0},
    "scan_speed_mm_s": {"mm/s": 1.0, "m/s": 1000.0},
    "passes": {"": 1.0},
}

CSV_PARAM_COLUMNS = [
    "pulse_width_ps",
    "frequency_kHz",
    "hatch_spacing_um",
    "passes",
    "scan_speed_mm_s",
]
TARGET_COLUMN = "depth_um"
GROUP_COLUMN = "experiment_batch_id"


def load_csv_samples(
    csv_path: Path,
    *,
    material: str,
    process_type: str,
    equipment_profile_id: str,
    target_metric: str = TARGET_COLUMN,
) -> list[BOSample]:
    """CSV → BOSample[]（只取参数列与目标列齐全的行）。"""
    df = pd.read_csv(csv_path)
    samples: list[BOSample] = []
    for _, row in df.iterrows():
        x = {
            col: float(row[col])
            for col in CSV_PARAM_COLUMNS
            if pd.notna(row.get(col))
        }
        y_val = row.get(target_metric)
        if not x or pd.isna(y_val):
            continue
        samples.append(
            BOSample(
                sample_id=str(row.get("experiment_id") or f"row_{len(samples)}"),
                x_parameters=x,
                y_metrics={target_metric: float(y_val)},
                valid_for_training=bool(row.get("valid_flag", True)),
                material=material,
                process_type=process_type,
                equipment_profile_id=equipment_profile_id,
                target_metric=target_metric,
                batch_id=str(row.get(GROUP_COLUMN) or ""),
                source_type="experiment",
            )
        )
    return samples


def machine_bounds_from_csv(csv_path: Path) -> dict[str, list[float]]:
    """BO machine bounds from the CSV parameter ranges (frozen §3)."""
    df = pd.read_csv(csv_path)
    bounds: dict[str, list[float]] = {}
    for col in CSV_PARAM_COLUMNS:
        values = df[col].dropna()
        if len(values) == 0:
            continue
        bounds[col] = [float(values.min()), float(values.max())]
    return bounds


def ledger_to_evidence_claims(
    ledger: CandidateLedger,
    *,
    task_scope: dict[str, Any],
    target: str,
) -> list[EvidenceClaim]:
    """CandidateLedger → EvidenceClaim[]（MAPPED 的确定性候选）。

    Only MAPPED candidates with a resolvable numeric value shape become
    claims; everything else stays in the ledger (I11 - nothing is deleted).
    Scope uses canonical E2P keys (material_id / target_metric).
    """
    mapping_by_id = {m.candidate_id: m for m in ledger.mappings}
    scope = {
        "material_id": task_scope.get("material"),
        "laser_type": task_scope.get("laser_type"),
        "process_type": task_scope.get("process_type"),
        "geometry_type": task_scope.get("geometry_type"),
        "target_metric": task_scope.get("objective_metric"),
    }
    claims: list[EvidenceClaim] = []
    for candidate in ledger.candidates:
        if candidate.source_type not in (
            CandidateSourceType.CONDITION_MENTION,
            CandidateSourceType.TABLE_CELL,
        ):
            continue
        mapping = mapping_by_id.get(candidate.candidate_id)
        if mapping is None or mapping.status != MappingStatus.MAPPED:
            continue
        bounds_key = PARAM_TO_BOUNDS_KEY.get(mapping.target_field or "")
        if bounds_key is None:
            continue
        unit_factors = UNIT_CONVERSION.get(bounds_key)
        if unit_factors is None:
            continue
        unit = candidate.source_detail.get("normalized_unit") or ""
        factor = unit_factors.get(unit)
        if factor is None:
            continue  # unit family mismatch: stays in the ledger, never deleted
        values = sorted(
            v * factor for v in (candidate.source_detail.get("values") or [])
        )
        if not values:
            continue
        anchor = candidate.provenance_anchors[0] if candidate.provenance_anchors else None
        claims.append(
            EvidenceClaim(
                claim_id=f"claim_{candidate.candidate_id}",
                claim_type="range_preference",
                parameter=bounds_key,
                target=target,
                value={
                    "lower_bound": min(values),
                    "upper_bound": max(values),
                },
                scope=scope,
                semantic_role="experimental_condition",
                source={
                    "paper_id": ledger.paper_id,
                    "block_id": anchor.block_id if anchor else "",
                    "quote_fingerprint": anchor.quote_fingerprint if anchor else "",
                    "quote": candidate.raw_statement,
                    "claim_source": candidate.source_type.value,
                    "candidate_id": candidate.candidate_id,
                },
                review_status="approved",  # Demo auto-approve（§4 显式声明）
            )
        )
    return claims


def claims_to_approved_priors(claims: list[EvidenceClaim]) -> list[dict[str, Any]]:
    """EvidenceClaim → approved prior dict（compile_from_approved_priors 输入）。"""
    priors: list[dict[str, Any]] = []
    for claim in claims:
        value = claim.value or {}
        if value.get("lower_bound") is None or value.get("upper_bound") is None:
            continue
        priors.append(
            {
                "approval_id": claim.claim_id,
                "parameter_name": claim.parameter,
                "lower_bound": float(value["lower_bound"]),
                "upper_bound": float(value["upper_bound"]),
                # claim 本身即 evidence；approval_id 与 evidence_id 同源
                # （契约 G3：artifact.evidence_ids 可追溯回 EvidenceIR claims）
                "evidence_ids": [claim.claim_id],
            }
        )
    return priors


def claim_to_evidence_ir(ledger: CandidateLedger, claims: list[EvidenceClaim]) -> dict[str, Any]:
    """EvidenceIR audit meta（§5）。"""
    papers = sorted({c.source.get("paper_id", "") for c in claims if c.source.get("paper_id")})
    return {
        "paper_count": len(papers),
        "papers": papers,
        "claim_count": len(claims),
        "ledger_candidate_count": len(ledger.candidates),
        "ledger_version_id": ledger.ledger_version_id,
    }
