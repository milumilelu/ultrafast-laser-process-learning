"""End-to-end evidence checks over a repository-owned original paper PDF."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_knowledge.evidence_pipeline import (
    RequirementEvidenceExtractor,
    RequirementEvidencePipeline,
    SemanticBlockBuilder,
    TwoLevelEvidenceRetriever,
)
from ultrafast_requirements import RequirementCompiler

pytestmark = [pytest.mark.integration, pytest.mark.pilot]

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_DIAMOND_PAPER = (
    REPO_ROOT / "artifacts" / "b1_annotation" / "papers" / "04_arxiv_2502.16530.pdf"
)


def _real_paper():
    if not REAL_DIAMOND_PAPER.is_file():
        pytest.skip(f"real paper PDF not present: {REAL_DIAMOND_PAPER}")
    document = PyMuPDFDocumentParser().parse(REAL_DIAMOND_PAPER)
    paper = SemanticBlockBuilder().build(
        document,
        title=(
            "Ultrashort 30-fs laser photoablation for high-precision and "
            "damage-free diamond machining"
        ),
        metadata={"material": "diamond", "laser_type": "fs"},
    )
    return document, paper


def _threshold_requirement_set():
    compiled = RequirementCompiler().compile(
        {"target": "depth_um", "material": "diamond", "laser_type": "fs"},
        {
            "laser_power_W": 20.0,
            "frequency_Hz": 100_000.0,
            "scan_speed_m_s": 1.0,
        },
    )
    threshold = next(
        item
        for item in compiled.knowledge_requirements
        if item.quantity == "ablation_threshold_J_m2"
    )
    return compiled.model_copy(update={"requirements": [threshold]})


def test_semantic_blocks_preserve_the_real_pdf_text_and_provenance() -> None:
    document, paper = _real_paper()
    native = {
        block.block_id(): block
        for page in document.pages
        for block in page
    }

    assert paper.blocks
    assert {item.block_id for item in paper.blocks} == set(native)
    assert all(item.text == native[item.block_id].text for item in paper.blocks)
    assert all(item.page == native[item.block_id].page_index + 1 for item in paper.blocks)
    assert paper.blocks[0].next_block_id == paper.blocks[1].block_id
    assert paper.blocks[-1].previous_block_id == paper.blocks[-2].block_id


def test_two_level_retrieval_finds_reported_threshold_inside_the_real_paper() -> None:
    _document, paper = _real_paper()
    requirement = _threshold_requirement_set().knowledge_requirements[0]
    candidates, windows = TwoLevelEvidenceRetriever().retrieve(requirement, [paper])

    assert candidates[0].paper_id == "04_arxiv_2502.16530.pdf"
    assert windows
    center = paper.block_by_id(windows[0].center_block_id)
    assert center is not None
    assert "ablation threshold" in center.text
    assert "diamond" in center.text
    assert "3 J/cm2" in center.text
    assert center.section_type != "references"
    assert center.page == 4


class _RecordedThresholdClient:
    """Recorded semantic answer; source text still comes from the original PDF."""

    model = "recorded-real-paper-answer"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, messages, **_kwargs):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        target_line = next(
            line
            for line in prompt.splitlines()
            if "ablation threshold of diamond (3.0 J/cm2)" in line
        )
        block_id = re.match(r"\[([^|]+)\s+\|", target_line).group(1).strip()
        return {
            "content": json.dumps(
                {
                    "status": "FOUND",
                    "value": 3.0,
                    "lower": None,
                    "upper": None,
                    "unit": "J/cm2",
                    "conditions": {"material": "diamond", "laser_type": "fs"},
                    "semantic_role": "property_constant",
                    "source_block_refs": [block_id],
                    "confidence": 0.96,
                    "conflict_values": [],
                    "evidence_quote": (
                        "fs-laser ablation threshold of diamond (3.0 J/cm2)"
                    ),
                }
            )
        }


def test_requirement_specific_extraction_is_grounded_in_the_real_pdf() -> None:
    _document, paper = _real_paper()
    requirement_set = _threshold_requirement_set()
    client = _RecordedThresholdClient()
    pipeline = RequirementEvidencePipeline(
        RequirementEvidenceExtractor(client, model=client.model)
    )

    run = pipeline.analyze(requirement_set, papers=[paper])

    assert len(client.calls) == 1
    assert '"quantity": "ablation_threshold_J_m2"' in client.calls[0]
    assert "incubation_coefficient" not in client.calls[0]
    assert len(run.results) == 1
    result = run.results[0]
    assert result.status.value == "FOUND"
    assert result.value == 3.0
    assert result.unit == "J/cm2"
    assert result.source_block_refs
    assert result.valid, result.validation_errors
    cited = paper.block_by_id(result.source_block_refs[0])
    assert cited is not None
    assert "3.0 J/cm2" in cited.text
