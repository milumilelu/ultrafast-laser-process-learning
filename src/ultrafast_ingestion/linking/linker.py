"""Schema-constrained semantic relation linker.

LLM interface + prompt construction + strict response parsing.

Pipeline: graph edges are INPUT (never ignored); hard negative edges are
validated downstream. Rationale is never used by validation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ultrafast_ingestion.graph.models import CandidateGraph, MentionRole
from ultrafast_ingestion.linking.models import (
    EvidenceStrength,
    LinkDecision,
    LinkingResult,
    LinkProposal,
    RelationType,
)

PROMPT_VERSION = "v0.1"
SCHEMA_VERSION = "experimental-condition-schema-v0.2"
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "experimental_condition_linker" / f"{PROMPT_VERSION}.md"


class LinkerClient(Protocol):
    """External LLM client. Must return raw text content."""

    def complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str: ...


class ResponseParseError(ValueError):
    pass


def build_linker_prompt(graph: CandidateGraph) -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    lines: list[str] = []
    for mid, mention in graph.mentions.items():
        role = graph.roles.get(mid, MentionRole.UNCLEAR)
        lines.append(
            f"- M {mid}: parameter={mention.parameter} values={mention.values} "
            f"unit={mention.normalized_unit} role_hint={role.value} "
            f"status={mention.acceptance_status.value}"
        )
    mention_section = "\n".join(lines)

    edge_lines: list[str] = []
    for i, edge in enumerate(graph.edges):
        edge_lines.append(
            f"- E {i}: {edge.type.value} {edge.source_mention_id} <-> {edge.target_mention_id} "
            f"rule={edge.source_rule} strength={edge.edge_strength.value}"
        )
    edge_section = "\n".join(edge_lines)

    return prompt.format(
        mentions=mention_section,
        edges=edge_section,
    )


_RELATION_NAMES = {r.value for r in RelationType}
_DECISION_NAMES = {d.value for d in LinkDecision}
_STRENGTH_NAMES = {s.value for s in EvidenceStrength}


def parse_response(raw: str) -> list[LinkProposal]:
    """Strict JSON parsing of the LLM response.

    Rejects: unknown relations, unknown decisions, malformed mention_ids,
    missing provenance anchors, any numeric value field (values must never
    be produced by the LLM).
    """
    content = raw.strip()
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ResponseParseError("no JSON object in response")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ResponseParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "proposals" not in payload:
        raise ResponseParseError("missing 'proposals' key")

    proposals: list[LinkProposal] = []
    for item in payload.get("proposals") or []:
        if not isinstance(item, dict):
            raise ResponseParseError("proposal must be an object")
        if "proposal_id" not in item:
            raise ResponseParseError("proposal missing proposal_id")
        decision = str(item.get("decision") or "")
        if decision not in _DECISION_NAMES:
            raise ResponseParseError(f"unknown decision: {decision}")
        mention_ids = [str(x) for x in item.get("mention_ids") or []]
        if not mention_ids:
            raise ResponseParseError(f"proposal {item['proposal_id']} has no mention_ids")
        relation = str(item.get("relation") or "")
        if relation and relation not in _RELATION_NAMES:
            raise ResponseParseError(f"unknown relation: {relation}")
        strength = str(item.get("evidence_strength") or "SEMANTICALLY_INFERRED")
        if strength not in _STRENGTH_NAMES:
            raise ResponseParseError(f"unknown evidence_strength: {strength}")
        if "supporting_edge_ids" not in item:
            raise ResponseParseError(f"proposal {item['proposal_id']} missing supporting_edge_ids")
        forbidden_value_fields = {"value", "values", "normalized_value", "lower", "upper"}
        present = forbidden_value_fields.intersection(item)
        if present:
            raise ResponseParseError(
                f"proposal {item['proposal_id']} contains numeric fields {sorted(present)} "
                "- LLM must never generate values"
            )
        proposals.append(LinkProposal.from_dict({**item, "mention_ids": mention_ids}))
    return proposals


@dataclass(slots=True)
class RecordedLinker:
    """Deterministic linker for CI: replays recorded responses."""

    record_path: Path
    model_name: str = "recorded"
    model_parameters: dict[str, Any] | None = None

    def complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        raise NotImplementedError("RecordedLinker is not a real client; use run_recorded")


def run_recorded(record_path: Path, graph: CandidateGraph, paper_id: str, doc_version: str) -> LinkingResult:
    rows = [
        json.loads(line)
        for line in record_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    proposals = []
    for row in rows:
        if row.get("type") == "proposal":
            proposals.append(LinkProposal.from_dict(row["proposal"]))
    return LinkingResult(
        paper_id=paper_id,
        document_version_id=doc_version,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        graph_version=f"graph-{doc_version[:8]}",
        model_name="recorded",
        proposals=proposals,
        abstentions=[r for r in rows if r.get("type") == "abstention"],
    )


def run_live(
    client: LinkerClient,
    graph: CandidateGraph,
    paper_id: str,
    doc_version: str,
    model_name: str,
    model_parameters: dict[str, Any] | None = None,
    temperature: float = 0.0,
) -> LinkingResult:
    system_prompt = (
        "You are a scientific document condition linker. Follow the instructions "
        "exactly. Output only one JSON object."
    )
    user_prompt = build_linker_prompt(graph)
    raw = client.complete(system_prompt, user_prompt, temperature=temperature)
    proposals = parse_response(raw)
    return LinkingResult(
        paper_id=paper_id,
        document_version_id=doc_version,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        graph_version=f"graph-{doc_version[:8]}",
        model_name=model_name,
        model_parameters=model_parameters or {},
        proposals=proposals,
    )
