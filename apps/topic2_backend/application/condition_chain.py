"""阶段一 · 中段五盒 orchestrator adapter (手册 §7 链中段).

Validated candidates (LLM analysis, cache-first)
  → CandidateLedger            (candidates/ledger.py models, LLM_DISCOVERY source)
  → Condition Compiler         (conditions/compiler.py compile_conditions)
  → SourceConditionSpec        (reconstructibility/adapter.py to_source_condition_spec)
  → ReconstructibilityReport   (reconstructibility/report.py build_report)
  → EvidenceIR projection      (each item gains ledger_ref / condition_refs /
                                reconstructibility_refs)

No algorithm is reimplemented: this module only projects the analysis
candidates' `conditions` dicts into the deterministic condition pipeline.
"""

from __future__ import annotations

from typing import Any

from ultrafast_ingestion.candidates.models import (
    CandidateKind,
    CandidateLedger,
    CandidateMapping,
    CandidateSourceType,
    GroundingStatus,
    MappingStatus,
    PromotionStatus,
    ScientificCandidate,
    VerificationStatus,
)
from ultrafast_ingestion.conditions.compiler import compile_conditions
from ultrafast_ingestion.conditions.models import ValidatedRelationGraph
from ultrafast_ingestion.graph.models import (
    CandidateEdge,
    CandidateGraph,
    EdgeStrength,
    EdgeType,
    MentionRole,
)
from ultrafast_ingestion.linking.models import (
    EvidenceStrength,
    LinkDecision,
    LinkProposal,
    RelationType,
    Scope,
)
from ultrafast_ingestion.mentions.models import (
    AcceptanceStatus,
    ConditionMention,
    ContextClass,
    MentionValueType,
)
from ultrafast_ingestion.models.provenance import ProvenanceAnchor, stable_hash
from ultrafast_reconstructibility.adapter import to_source_condition_spec
from ultrafast_reconstructibility.models import SourceConditionSpec
from ultrafast_reconstructibility.report import build_report

# CandidateType -> CandidateKind (routing taxonomy, deterministic)
CANDIDATE_KIND_MAP: dict[str, CandidateKind] = {
    "threshold": CandidateKind.QUANTITY,
    "material_property": CandidateKind.MATERIAL_PROPERTY,
    "optical_property": CandidateKind.MATERIAL_PROPERTY,
    "parameter_range": CandidateKind.QUANTITY,
    "parameter_value": CandidateKind.QUANTITY,
    "parameter_effect": CandidateKind.PARAMETER_EFFECT,
    "relative_importance": CandidateKind.COMPARISON,
    "mechanism": CandidateKind.MECHANISM,
    "formula": CandidateKind.PROCEDURE,
    "functional_shape": CandidateKind.MECHANISM,
    "reported_optimum": CandidateKind.OUTCOME,
    "experimental_condition": CandidateKind.CONSTRAINT,
}

# conditions dict key -> unit (adapter-side projection table)
CONDITION_UNITS: dict[str, str] = {
    "wavelength_nm": "nm",
    "pulse_width_fs": "fs",
    "pulse_width_ps": "ps",
    "frequency_kHz": "kHz",
    "scan_speed_mm_s": "mm/s",
    "hatch_spacing_um": "um",
    "passes": "count",
    "peak_fluence_J_cm2": "J/cm2",
    "average_power_W": "W",
}

# conditions dict key -> canonical physics parameter name consumed by the
# CoordinateEvaluator (reconstructibility) — deterministic projection only.
CONDITION_PARAMETER_CANONICAL: dict[str, str] = {
    "wavelength_nm": "wavelength",
    "pulse_width_fs": "pulse_width",
    "pulse_width_ps": "pulse_width",
    "frequency_kHz": "frequency",
    "scan_speed_mm_s": "scan_speed",
    "hatch_spacing_um": "hatch_spacing",
    "passes": "passes",
    "peak_fluence_J_cm2": "fluence",
    "average_power_W": "average_power",
}

ANALYSIS_DISCOVERY_METHOD = "scientific-reading-v1"


def _paper_of(candidate: dict[str, Any]) -> str:
    sources = candidate.get("supporting_sources") or []
    for source in sources:
        if source.get("paper_id"):
            return str(source["paper_id"])
    return "unknown-paper"


def _page_of(candidate: dict[str, Any]) -> int:
    sources = candidate.get("supporting_sources") or []
    for source in sources:
        page = source.get("page")
        if isinstance(page, int):
            return page
    return 0


def _raw_statement(candidate: dict[str, Any]) -> str:
    parameter = candidate.get("parameter")
    lower = candidate.get("lower")
    upper = candidate.get("upper")
    unit = candidate.get("unit")
    if lower is not None and upper is not None:
        return f"{parameter or 'value'} = {lower}..{upper} {unit or ''}".strip()
    if candidate.get("value") is not None:
        return f"{parameter or 'value'} = {candidate['value']} {unit or ''}".strip()
    return f"{candidate.get('type') or 'candidate'} {parameter or ''}".strip()


def _scientific_candidate(
    candidate: dict[str, Any],
    *,
    corpus_pack_id: str,
    model: str,
) -> ScientificCandidate:
    paper_id = _paper_of(candidate)
    page = _page_of(candidate)
    anchor = ProvenanceAnchor(
        paper_id=paper_id,
        document_version_id=corpus_pack_id,
        pdf_page_index=page,
        normalized_quote=_raw_statement(candidate),
        quote_fingerprint=stable_hash("quote", paper_id, _raw_statement(candidate)),
    )
    ctype = str(candidate.get("type") or "other")
    return ScientificCandidate(
        candidate_id=str(candidate.get("candidate_id") or stable_hash("cand", paper_id, str(candidate))),
        paper_id=paper_id,
        document_version_id=corpus_pack_id,
        candidate_kind=CANDIDATE_KIND_MAP.get(ctype, CandidateKind.OTHER),
        concept_label=str(candidate.get("parameter") or candidate.get("name") or ctype),
        raw_statement=_raw_statement(candidate),
        raw_value=str(candidate.get("value")) if candidate.get("value") is not None else None,
        raw_unit=candidate.get("unit"),
        source_type=CandidateSourceType.LLM_DISCOVERY,
        source_ref=str(candidate.get("candidate_id") or ""),
        source_locator=f"{paper_id}:p{page}",
        source_detail={
            "type": ctype,
            "parameter": candidate.get("parameter"),
            "lower": candidate.get("lower"),
            "upper": candidate.get("upper"),
            "unit": candidate.get("unit"),
            "conditions": dict(candidate.get("conditions") or {}),
            "expression": candidate.get("expression"),
            "assumptions": list(candidate.get("assumptions") or []),
            "model": model,
        },
        provenance_anchors=[anchor],
        grounding_status=GroundingStatus.GROUNDED,
        verification_status=VerificationStatus.NOT_RUN,
        promotion_status=PromotionStatus.NOT_PROMOTED,
        discovery_method=ANALYSIS_DISCOVERY_METHOD,
        discovery_version="v0.1",
    )


def build_candidate_ledger(
    candidates: list[dict[str, Any]],
    *,
    corpus_pack_id: str,
    model: str,
) -> CandidateLedger:
    """Run-level candidate ledger (frozen artifact CandidateLedger)."""
    entries = [
        _scientific_candidate(candidate, corpus_pack_id=corpus_pack_id, model=model)
        for candidate in candidates
    ]
    mappings = [
        CandidateMapping(
            candidate_id=entry.candidate_id,
            target_namespace="experimental_condition",
            status=MappingStatus.UNMAPPED,
        )
        for entry in entries
    ]
    return CandidateLedger(
        ledger_version_id=stable_hash("ledger", corpus_pack_id, len(entries)),
        paper_id="aggregate",
        document_version_id=corpus_pack_id,
        candidates=entries,
        mappings=mappings,
        metrics={
            "candidates": len(entries),
            "papers": len({entry.paper_id for entry in entries}),
        },
    )


def _numeric_conditions(candidate: dict[str, Any]) -> dict[str, float]:
    """Numeric experimental conditions reported by the analysis candidate."""
    result: dict[str, float] = {}
    for key, value in (candidate.get("conditions") or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = float(value)
    return result


def _condition_graph(
    paper_id: str,
    paper_candidates: list[dict[str, Any]],
    *,
    document_version_id: str,
) -> ValidatedRelationGraph:
    """Project one paper's analysis conditions into the mention graph.

    Every numeric condition field becomes a PROCESSING mention; all
    mentions of the paper are joined by STRONG SAME_EXPERIMENT edges so the
    deterministic Condition Compiler groups them into condition specs.
    """
    graph = CandidateGraph()
    seen: set[tuple[str, float]] = set()
    mention_ids: list[str] = []
    for candidate in paper_candidates:
        for raw_parameter, value in _numeric_conditions(candidate).items():
            parameter = CONDITION_PARAMETER_CANONICAL.get(raw_parameter, raw_parameter)
            key = (parameter, value)
            if key in seen:
                continue
            seen.add(key)
            mention_id = stable_hash("mention", paper_id, parameter, value)
            anchor = ProvenanceAnchor(
                paper_id=paper_id,
                document_version_id=document_version_id,
                pdf_page_index=0,
                normalized_quote=f"{parameter}={value}",
                quote_fingerprint=stable_hash("mquote", paper_id, parameter, value),
            )
            graph.add_mention(
                mention_id,
                ConditionMention(
                    mention_id=mention_id,
                    parameter=parameter,
                    raw_text=f"{parameter}={value}",
                    values=[value],
                    value_type=MentionValueType.SCALAR,
                    normalized_unit=CONDITION_UNITS.get(parameter, ""),
                    context_class=ContextClass.PROCESS_CONTEXT,
                    acceptance_status=AcceptanceStatus.ACCEPTED,
                    anchor=anchor,
                ),
                MentionRole.PROCESSING,
            )
            mention_ids.append(mention_id)
    for index, left in enumerate(mention_ids):
        for right in mention_ids[index + 1 :]:
            graph.add_edge(
                CandidateEdge(
                    source_mention_id=left,
                    target_mention_id=right,
                    type=EdgeType.SAME_EXPERIMENT_CANDIDATE,
                    source_rule="analysis-conditions-adapter",
                    edge_strength=EdgeStrength.STRONG,
                )
            )
    accepted = [
        LinkProposal(
            proposal_id=stable_hash("link", left, right),
            decision=LinkDecision.LINK,
            mention_ids=(left, right),
            relation=RelationType.SAME_EXPERIMENT,
            scope=Scope.EXPERIMENT_GROUP,
            evidence_strength=EvidenceStrength.STRUCTURALLY_SUPPORTED,
            rationale="analysis candidate conditions share one experiment group",
        )
        for index, left in enumerate(mention_ids)
        for right in mention_ids[index + 1 :]
    ]
    return ValidatedRelationGraph(graph=graph, accepted=accepted)


def compile_source_conditions(
    candidates: list[dict[str, Any]],
    *,
    corpus_pack_id: str,
) -> list[SourceConditionSpec]:
    """Condition Compiler + SourceCondition projection (deterministic)."""
    by_paper: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_paper.setdefault(_paper_of(candidate), []).append(candidate)
    conditions: list[SourceConditionSpec] = []
    for paper_id, paper_candidates in by_paper.items():
        graph = _condition_graph(paper_id, paper_candidates, document_version_id=corpus_pack_id)
        compiled = compile_conditions(graph)
        for condition in compiled.conditions:
            conditions.append(
                to_source_condition_spec(
                    condition,
                    document_version_id=corpus_pack_id,
                )
            )
    return conditions


def build_reconstructibility_reports(
    conditions: list[SourceConditionSpec],
) -> list[dict[str, Any]]:
    """ReconstructibilityReport per SourceCondition (deterministic)."""
    return [build_report(condition).to_dict() for condition in conditions]


def project_evidence_ir(
    evidence_items: list[dict[str, Any]],
    *,
    ledger: CandidateLedger,
    conditions: list[SourceConditionSpec],
    reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach ledger / condition / reconstructibility refs to each item.

    Ref matching is by paper_id (condition) and by condition_id (report);
    an item always carries the ledger ref.  Items without a matching paper
    keep honest empty refs - never fabricated.
    """
    condition_by_paper: dict[str, list[str]] = {}
    for condition in conditions:
        condition_by_paper.setdefault(condition.paper_id, []).append(condition.condition_id)
    report_by_condition: dict[str, str] = {
        str(report.get("condition_id")): str(report.get("condition_id"))
        for report in reports
    }
    projected: list[dict[str, Any]] = []
    for item in evidence_items:
        paper_ids = [
            str(ref.get("id"))
            for ref in item.get("source_refs") or []
            if ref.get("type") == "Paper"
        ]
        paper_id = paper_ids[0] if paper_ids else ""
        condition_refs = [
            {"type": "SourceCondition", "id": condition_id}
            for condition_id in condition_by_paper.get(paper_id, [])
        ]
        reconstructibility_refs = [
            {"type": "ReconstructibilityReport", "id": report_id}
            for condition_id in condition_by_paper.get(paper_id, [])
            if (report_id := report_by_condition.get(condition_id))
        ]
        projected.append(
            {
                **item,
                "ledger_ref": {"type": "CandidateLedger", "id": ledger.ledger_version_id},
                "condition_refs": condition_refs,
                "reconstructibility_refs": reconstructibility_refs,
            }
        )
    return projected
