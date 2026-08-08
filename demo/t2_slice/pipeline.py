"""Demo V2 vertical slice orchestration (六区域，契约 §2/§3)。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from demo.t2_slice.adapters import (
    CSV_PARAM_COLUMNS,
    GROUP_COLUMN,
    TARGET_COLUMN,
    claim_to_evidence_ir,
    claims_to_approved_priors,
    ledger_to_evidence_claims,
    load_csv_samples,
    machine_bounds_from_csv,
)
from ultrafast_bo.application.formal_service import BORecommendationService
from ultrafast_e2p.application.evidence_compiler import compile_evidence
from ultrafast_e2p.application.prior_compiler import compile_from_approved_priors
from ultrafast_e2p.domain.evidence import EvidenceClaim
from ultrafast_ingestion.candidates.ledger import build_ledger
from ultrafast_physics.feature_builder import PhysicsFeatureBuilder

_CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "test_fixture" / "topic2_experiments_v1.csv"

# HYBRID view: RAW + physics features that do NOT depend on laser power
# (pulse_energy/fluence coordinates are blocked and reported unavailable)
HYBRID_PHYSICS_FEATURES = (
    "pulse_interval",
    "pulse_spacing",
    "pulse_overlap",
    "pulses_per_spot",
)
DEMO_DEVICE_PROPERTIES: dict[str, tuple[float, str]] = {
    # demo assumption（§3 显式声明，不冒充已确认 canonical 值）
    "spot_radius_um": (5.0, "um"),
}


def _feature_views(csv_path: Path) -> dict[str, Any]:
    df = pd.read_csv(csv_path)
    rows = []
    for _, row in df.iterrows():
        raw = {
            "frequency_kHz": row.get("frequency_kHz"),
            "scan_speed_mm_s": row.get("scan_speed_mm_s"),
            "hatch_spacing_um": row.get("hatch_spacing_um"),
            "passes": row.get("passes"),
            "pulse_width_fs": row.get("pulse_width_ps") * 1000.0
            if pd.notna(row.get("pulse_width_ps"))
            else None,
            "sample_id": str(row.get("experiment_id") or ""),
        }
        rows.append(raw)
    builder = PhysicsFeatureBuilder(features=HYBRID_PHYSICS_FEATURES)
    built = builder.build(rows, device_properties=DEMO_DEVICE_PROPERTIES)
    return {
        "raw": df[CSV_PARAM_COLUMNS].copy(),
        "hybrid": df[CSV_PARAM_COLUMNS].copy(),
        "hybrid_physics": built.feature_frame(),
        "unavailable_physics": built.unavailable_features,
        "missing_device_properties": built.missing_device_properties,
        "blocked_coordinates": sorted(set(built.unavailable_features)),
    }


def _run_process_learning(csv_path: Path, random_seed: int = 42) -> dict[str, Any]:
    """DEMO-1：Dataset → ProcessLearningResult（RAW/HYBRID × Group-CV）。

    HYBRID is a real training matrix: RAW columns + verified computable
    physics features (blocked coordinates excluded). Until every physics
    coordinate is computable, HYBRID stays partial and RAW remains the
    honest baseline.
    """
    from ultrafast_e2p.application.model_selection import (
        comparison_report,
        select_model,
    )

    df = pd.read_csv(csv_path)
    y = df[TARGET_COLUMN].dropna()
    groups = df.loc[y.index, GROUP_COLUMN]
    x = df.loc[y.index, CSV_PARAM_COLUMNS]
    views = _feature_views(csv_path)
    x_hybrid = _hybrid_frame(df, views)
    results: dict[str, Any] = {}
    for view_name, x_frame in (("RAW", x), ("HYBRID", x_hybrid)):
        clean = x_frame.dropna()
        if len(clean) < 2:
            continue
        result = select_model(
            clean,
            y.loc[clean.index],
            groups.loc[clean.index],
            max_folds=5,
            random_seed=random_seed,
        )
        results[view_name] = {
            "selected_model": result.selected_model,
            "metrics_by_model": {
                name: metrics for name, metrics in result.metrics_by_model.items()
            },
            "cv_folds": result.cv_folds,
            "comparison": comparison_report(result),
        }
    if "RAW" not in results:
        raise ValueError("RAW process learning could not be computed")
    winner_view = max(results, key=lambda v: _cv_score(results[v]))
    hybrid_available = sorted(
        set(views.get("hybrid_physics") or {}).difference(
            set(views.get("blocked_coordinates") or [])
        )
    )
    return {
        "feature_views": {
            "RAW": {"status": "available"},
            "HYBRID": {
                "status": "partial",
                "available_physics": hybrid_available,
                "blocked_coordinates": views["blocked_coordinates"],
                "note": "blocked 坐标（依赖设备属性）尚未纳入训练矩阵，下一步优先开发",
            },
        },
        "model_comparison": results,
        "selected_feature_view": winner_view,
        "selected_model": results[winner_view]["selected_model"],
        "cv_metrics": results[winner_view]["metrics_by_model"],
        "cv_folds": results[winner_view]["cv_folds"],
        "prediction_interface": "surrogate prediction + uncertainty (BO engine)",
        "uncertainty_interface": "acquisition variance (UCB)",
    }


def _hybrid_frame(df: pd.DataFrame, views: dict | None = None) -> pd.DataFrame:
    """True HYBRID training matrix: RAW five columns + physics features that are
    computable and verified by the physics builder.

    Blocked coordinates (missing device properties) are excluded - they are
    never silently added.  Values are aligned to the CSV row order used by
    ``_feature_views``; pandas index alignment handles dropna afterwards.
    """
    if views is None:
        raise ValueError("_hybrid_frame requires the feature views report")
    frame = df[CSV_PARAM_COLUMNS].copy()
    physics = views.get("hybrid_physics") or {}
    blocked = set(views.get("blocked_coordinates") or [])
    for feature, values in physics.items():
        if feature in blocked:
            continue
        frame[feature] = values
    return frame


def _cv_score(view_result: dict) -> float:
    metrics = view_result.get("metrics_by_model") or {}
    selected = view_result.get("selected_model")
    if selected in metrics:
        rmse = metrics[selected].get("RMSE", metrics[selected].get("cv_rmse"))
        if rmse is not None:
            return -float(rmse)
    return -1e9


def _run_literature(
    documents: list,
    mentions_by_paper: dict[str, list],
    regions_by_paper: dict[str, list],
    compile_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """DEMO-2：PDF → ScientificDocument → CandidateLedger → EvidenceIR。"""
    ledgers = []
    for doc in documents:
        ledgers.append(
            build_ledger(
                doc,
                mentions_by_paper.get(doc.paper_id, []),
                regions_by_paper.get(doc.paper_id, []),
                compile_result=compile_results.get(doc.paper_id) if compile_results else None,
            )
        )
    return {"ledgers": ledgers, "paper_count": len(ledgers)}


def _run_source_states(
    documents: list,
    mentions_by_paper: dict[str, list],
    regions_by_paper: dict[str, list],
) -> list:
    """M6/M8: per-condition CanonicalInteractionState (source side)."""
    from ultrafast_ingestion.conditions.compiler import compile_conditions
    from ultrafast_ingestion.conditions.models import ValidatedRelationGraph
    from ultrafast_ingestion.graph.builder import build_candidate_graph
    from ultrafast_interaction.canonical import source_state
    from ultrafast_reconstructibility.adapter import to_source_condition_spec
    from ultrafast_reconstructibility.report import build_report

    states = []
    for doc in documents:
        ledger = build_ledger(
            doc,
            mentions_by_paper.get(doc.paper_id, []),
            regions_by_paper.get(doc.paper_id, []),
        )
        graph = build_candidate_graph(
            doc, ledger.for_condition_linking(doc, regions_by_paper.get(doc.paper_id, []))
        )
        compiled = compile_conditions(ValidatedRelationGraph(graph=graph))
        for condition in compiled.conditions:
            spec = to_source_condition_spec(
                condition, document_version_id=doc.document_version_id
            )
            states.append(source_state(build_report(spec)))
    return states


def _run_cfa(
    task_spec: dict[str, Any],
    claims: list,
    source_states: list,
) -> dict[str, Any]:
    """Demo V3 integration gate: real assess_all over the slice.

    CFA is an audit/assessment output only - it NEVER changes prior weight
    (uncalibrated heuristic != probability).
    """
    from ultrafast_cfa.cfa import CFA_VERSION, assess_all
    from ultrafast_interaction.canonical import target_state
    from ultrafast_interaction.target import (
        TargetCoordinateEvaluator,
        build_target_condition_spec,
    )

    target_spec = build_target_condition_spec(
        _CSV_PATH,
        equipment_profile={"spot_radius_um": (5.0, "um", False)},  # UNVERIFIED (M7)
        equipment_profile_id=task_spec.get("equipment_profile_id", ""),
    )
    target = target_state(
        TargetCoordinateEvaluator().evaluate(target_spec), condition_id="target"
    )
    task = _canonical_task(task_spec)
    by_paper: dict[str, list] = {}
    for claim in claims:
        paper = (claim.source or {}).get("paper_id", "")
        by_paper.setdefault(paper, []).append(claim)
    reports = []
    for paper_id, paper_claims in sorted(by_paper.items()):
        scope = paper_claims[0].scope or {}
        states = [s for s in source_states if s.paper_id == paper_id]
        for state in states:
            reports.append(
                assess_all(
                    task_scope=task,
                    evidence_scope=scope,
                    source=state,
                    target=target,
                    evidence_claim_id=paper_claims[0].claim_id,
                    version=CFA_VERSION,
                ).to_dict()
            )
    return {
        "target_physics_readiness": readiness_projection_repr(
            TargetCoordinateEvaluator().evaluate(target_spec)
        ),
        "reports": reports,
        "calibration_status": "NOT_YET_CALIBRATED",
    }


def readiness_projection_repr(target_report) -> dict:
    from ultrafast_interaction.target import readiness_projection

    return readiness_projection(target_report).to_dict()


def _run_e2p_prior(
    claims: list[EvidenceClaim],
    task_spec: dict[str, Any],
    bounds: dict[str, list[float]],
    approval_verifier,
) -> dict[str, Any]:
    """DEMO-3：EvidenceIR → approved priors → GovernedPriorArtifact。"""
    task = _canonical_task(task_spec)
    bundle = compile_evidence(task, claims)
    priors = claims_to_approved_priors(bundle.accepted)
    artifact = compile_from_approved_priors(
        bounds,
        priors,
        scope=task,
        approval_verifier=approval_verifier,
    )
    return {"bundle": bundle, "artifact": artifact, "prior_count": len(priors)}


def _canonical_task(task_spec: dict[str, Any]) -> dict[str, Any]:
    """task_spec → E2P applicability canonical keys."""
    return {
        "material_id": task_spec.get("material"),
        "laser_type": task_spec.get("laser_type"),
        "process_type": task_spec.get("process_type"),
        "geometry_type": task_spec.get("geometry_type"),
        "equipment_id": task_spec.get("equipment_profile_id"),
        "target_metric": task_spec.get("objective_metric"),
    }


def _cfa_facet_summary(reports: list[dict]) -> dict[str, str]:
    """Real facet aggregation over assess_all reports (audit layer only).

    Same semantics as the frozen B1 predictor summary: InteractionState takes
    the highest judgment across reports (any PARTIAL -> PARTIAL; all UNKNOWN
    -> UNKNOWN); other facets follow the first report (shared evidence scope).
    Statuses are KNOWN/PARTIAL/UNKNOWN/MISMATCH - never probabilities.
    """
    names = ("Material", "Task", "InteractionState", "Reconstructibility", "Reachability")
    if not reports:
        return {name: "UNKNOWN" for name in names}
    summary: dict[str, str] = {}
    for name in names:
        statuses = [
            next(f["status"] for f in rep["facets"] if f["facet"] == name)
            for rep in reports
        ]
        if name == "InteractionState":
            if "PARTIAL" in statuses:
                summary[name] = "PARTIAL"
            elif "KNOWN" in statuses:
                summary[name] = "KNOWN"
            elif "UNKNOWN" in statuses:
                summary[name] = "UNKNOWN"
            else:
                summary[name] = statuses[0] if statuses else "UNKNOWN"
        else:
            summary[name] = statuses[0] if statuses else "UNKNOWN"
    return summary


def _run_bo(
    task_spec: dict[str, Any],
    samples: list,
    machine_context: dict[str, Any],
    governed_artifact,
    approval_verifier,
) -> dict[str, Any]:
    """DEMO-4/5：Vanilla vs Evidence-assisted BO。"""
    service = BORecommendationService()
    vanilla = service.recommend(
        task_spec, samples, machine_context, governed_prior=None
    )
    assisted = service.recommend(
        task_spec,
        samples,
        machine_context,
        governed_prior=governed_artifact,
        approval_verifier=approval_verifier,
    )
    return {
        "vanilla": vanilla,
        "evidence_assisted": assisted,
        "prior_applied_evidence": {
            # "文献知识有没有进入优化算法"的直接证据（契约 G2/G7）
            "assisted_search_prior_applied": bool(
                assisted.get("search_prior_applied")
            ),
            "vanilla_search_prior_applied": bool(vanilla.get("search_prior_applied")),
            "assisted_prior_guidance": (assisted.get("acquisition") or {}).get(
                "prior_guidance"
            ),
            "governed_prior_hash": governed_artifact.content_hash,
            "assisted_prior_evidence_ids": list(governed_artifact.evidence_ids),
        },
    }


def run_vertical_slice(
    *,
    csv_path: Path,
    documents: list,
    mentions_by_paper: dict[str, list],
    regions_by_paper: dict[str, list],
    task_spec: dict[str, Any],
    approval_repo: set[str] | None = None,
    random_seed: int = 42,
) -> dict[str, Any]:
    """六区域完整编排（契约 §2）。

    approval_repo=None → Demo auto-approve：所有 review_status="approved"
    的 claims 自动进入 approval repo（§4 显式声明；生产必须显式传入）。
    """
    samples = load_csv_samples(
        csv_path,
        material=task_spec["material"],
        process_type=task_spec["process_type"],
        equipment_profile_id=task_spec["equipment_profile_id"],
        target_metric=task_spec["objective_metric"],
    )
    bounds = machine_bounds_from_csv(csv_path)
    machine_context = {
        "active": True,
        "machine_bounds": bounds,
        "equipment_profile_id": task_spec["equipment_profile_id"],
        "revision_id": "demo-profile-v0.1",
    }

    # 区域 1+2
    learning = _run_process_learning(csv_path, random_seed=random_seed)

    # 区域 3
    literature = _run_literature(documents, mentions_by_paper, regions_by_paper)
    claims: list[EvidenceClaim] = []
    for ledger in literature["ledgers"]:
        claims.extend(
            ledger_to_evidence_claims(
                ledger, task_scope=task_spec, target=task_spec["objective_metric"]
            )
        )
    evidence_meta = {}
    if literature["ledgers"]:
        evidence_meta = claim_to_evidence_ir(literature["ledgers"][0], claims)
    evidence_meta["paper_count"] = literature["paper_count"]
    evidence_ir = {
        "claims": [c.as_dict() for c in claims],
        "meta": evidence_meta,
    }

    repo = approval_repo if approval_repo is not None else {
        c.claim_id for c in claims if c.review_status == "approved"
    }

    def verifier(approval_id: str) -> bool:
        return approval_id in repo

    # 区域 4
    e2p = _run_e2p_prior(claims, task_spec, bounds, verifier)

    # 区域 5
    bo = _run_bo(
        task_spec,
        samples,
        machine_context,
        e2p["artifact"],
        verifier,
    )

    # Demo V3 集成 Gate：真实 CFA（M6-M9 主链插回 vertical slice）。
    # CFA 只是 audit/assessment 输出，绝不改变 prior weight（§Demo V3）。
    source_states = _run_source_states(documents, mentions_by_paper, regions_by_paper)
    cfa = _run_cfa(task_spec, claims, source_states)

    # 区域 6（审计由各组件原生字段组成）
    audit = {
        "bo_run_id_vanilla": bo["vanilla"].get("bo_run_id"),
        "bo_run_id_assisted": bo["evidence_assisted"].get("bo_run_id"),
        "evidence_ids": list(e2p["artifact"].evidence_ids),
        "prior_content_hash": e2p["artifact"].content_hash,
        "model_version": bo["evidence_assisted"].get("model_version"),
        "feature_view": learning["selected_feature_view"],
        "ledger_version_ids": [l.ledger_version_id for l in literature["ledgers"]],
        "audit_trace": bo["evidence_assisted"].get("audit_trace"),
        "cfa_status": cfa["calibration_status"],
        "cfa_facets": _cfa_facet_summary(cfa["reports"]),
    }

    return {
        "target_task": {
            "material": task_spec["material"],
            "laser_type": task_spec["laser_type"],
            "geometry": task_spec.get("geometry_type"),
            "objective": task_spec["objective_metric"],
            "dataset": str(csv_path),
            "parameter_domain": bounds,
            "sample_count": len(samples),
        },
        "process_learning": learning,
        "literature_evidence": {
            "paper_count": literature["paper_count"],
            "ledger_count": len(literature["ledgers"]),
        },
        "evidence_ir": evidence_ir,
        "e2p_prior": {
            "prior_count": e2p["prior_count"],
            "accepted_count": len(e2p["bundle"].accepted),
            "rejected": list(e2p["bundle"].rejected),
            "governed_prior": e2p["artifact"].to_dict(),
        },
        "bo": bo,
        "cfa": cfa,
        "audit": audit,
    }
