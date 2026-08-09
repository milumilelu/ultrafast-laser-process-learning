"""End-to-end evidence checks over a repository-owned original paper PDF."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from ultrafast_ingestion import PyMuPDFDocumentParser
from ultrafast_knowledge.evidence_pipeline import (
    PersistentScientificPaperRepository,
    RequirementEvidenceExtractor,
    RequirementEvidencePipeline,
    RetrievalGold,
    ScientificIndexIngestionService,
    ScientificIndexStore,
    SemanticBlockBuilder,
    TwoLevelEvidenceRetriever,
    evaluate_evidence_run,
)
from ultrafast_requirements import RequirementCompiler

pytestmark = [pytest.mark.integration, pytest.mark.pilot]

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_DIAMOND_PAPER = (
    REPO_ROOT / "artifacts" / "b1_annotation" / "papers" / "04_arxiv_2502.16530.pdf"
)
REAL_SIC_PAPERS = [
    REPO_ROOT / "artifacts" / "b1_annotation" / "papers" / "10_arxiv_2411.18093.pdf",
    REPO_ROOT / "artifacts" / "b1_annotation" / "papers" / "11_arxiv_2404.09906.pdf",
    REPO_ROOT / "artifacts" / "b1_annotation" / "papers" / "13_arxiv_2411.18868.pdf",
]


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
        {
            "target": "depth_um",
            "task_type": "prediction",
            "material": "diamond",
            "laser_type": "fs",
        },
        [
            {"quantity": "laser_power_W", "value": 20.0, "unit": "W", "source": "task"},
            {"quantity": "frequency_kHz", "value": 100.0, "unit": "kHz", "source": "task"},
            {"quantity": "scan_speed_m_s", "value": 1.0, "unit": "m/s", "source": "task"},
        ],
    )
    threshold = next(
        item
        for item in compiled.knowledge_requirements
        if item.quantity == "ablation_threshold_J_m2"
    )
    return compiled.model_copy(update={"requirements": [threshold]})


@pytest.fixture()
def indexed_real_corpus(tmp_path: Path):
    paths = [REAL_DIAMOND_PAPER, *REAL_SIC_PAPERS]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        pytest.skip(f"real paper PDFs not present: {missing}")
    database = tmp_path / "scientific-index.db"

    @contextmanager
    def connection():
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    store = ScientificIndexStore(connection)
    ingestion = ScientificIndexIngestionService(store)
    ingestion.ingest_many(
        [
            {
                "pdf_path": REAL_DIAMOND_PAPER,
                "title": "Ultrashort 30-fs laser photoablation of diamond",
                "metadata": {"material": "diamond", "laser_type": "fs"},
            },
            {
                "pdf_path": REAL_SIC_PAPERS[0],
                "title": "Multi-focal picosecond laser vertical slicing of 4H-SiC",
                "metadata": {"material": "4H-SiC", "laser_type": "ps"},
            },
            {
                "pdf_path": REAL_SIC_PAPERS[1],
                "title": "Photoluminescence of femtosecond laser-irradiated silicon carbide",
                "metadata": {"material": "SiC", "laser_type": "fs"},
            },
            {
                "pdf_path": REAL_SIC_PAPERS[2],
                "title": "Laser writing and spin control of near infrared emitters in SiC",
                "metadata": {"material": "SiC", "laser_type": "fs"},
            },
        ]
    )
    return store, PersistentScientificPaperRepository(store)


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


def test_two_level_retrieval_finds_reported_threshold_inside_the_real_paper(
    indexed_real_corpus,
) -> None:
    store, _repository = indexed_real_corpus
    requirement = _threshold_requirement_set().knowledge_requirements[0]
    candidates, windows_by_paper = TwoLevelEvidenceRetriever(store).retrieve(requirement)

    assert candidates[0].paper_id == "04_arxiv_2502.16530.pdf"
    assert "global_block_index" in candidates[0].retrieval_routes
    windows = windows_by_paper[
        f"{candidates[0].paper_id}::{candidates[0].document_version_id}"
    ]
    assert windows
    center = store.papers([candidates[0].paper_id])[0].block_by_id(
        windows[0].center_block_id
    )
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
        if "ablation threshold of diamond (3.0 J/cm2)" not in prompt:
            return {
                "content": json.dumps(
                    {
                        "status": "NOT_FOUND",
                        "confidence": 0.9,
                        "source_block_refs": [],
                    }
                )
            }
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


class _AlwaysNotFoundClient:
    model = "recorded-negative-answer"

    def chat(self, _messages, **_kwargs):
        return {
            "content": json.dumps(
                {"status": "NOT_FOUND", "confidence": 0.99, "source_block_refs": []}
            )
        }


def test_requirement_specific_extraction_is_grounded_in_the_real_pdf(
    indexed_real_corpus,
) -> None:
    store, repository = indexed_real_corpus
    requirement_set = _threshold_requirement_set()
    client = _RecordedThresholdClient()
    pipeline = RequirementEvidencePipeline(
        RequirementEvidenceExtractor(client, model=client.model),
        repository=repository,
        store=store,
    )

    run = pipeline.analyze(requirement_set)

    assert len(client.calls) == 4
    assert all('"quantity": "ablation_threshold_J_m2"' in call for call in client.calls)
    assert all("incubation_coefficient" not in call for call in client.calls)
    assert len(run.results) == 1
    result = run.results[0]
    assert result.status.value == "FOUND"
    assert result.value == 3.0
    assert result.unit == "J/cm2"
    assert result.source_block_refs
    assert result.valid, result.validation_errors
    cited = store.papers(["04_arxiv_2502.16530.pdf"])[0].block_by_id(
        result.source_block_refs[0]
    )
    assert cited is not None
    assert "3.0 J/cm2" in cited.text
    assert len(store.query_knowledge(requirement_set.knowledge_requirements[0])) == 1
    assert run.governance_warnings


def test_multi_real_pdf_benchmark_reports_recall_and_false_satisfied_rate(
    indexed_real_corpus,
) -> None:
    store, repository = indexed_real_corpus
    requirement_set = _threshold_requirement_set()
    threshold = requirement_set.knowledge_requirements[0]
    client = _RecordedThresholdClient()
    pipeline = RequirementEvidencePipeline(
        RequirementEvidenceExtractor(client, model=client.model),
        repository=repository,
        store=store,
    )
    positive_run = pipeline.analyze(requirement_set)
    candidates, windows = repository.retrieve(threshold)
    gold_block = next(
        block
        for block in store.blocks(paper_ids=["04_arxiv_2502.16530.pdf"])
        if "ablation threshold of diamond (3.0 J/cm2)" in block.text
    )

    negative = threshold.model_copy(
        update={
            "requirement_id": "req-negative-real-corpus",
            "quantity": "nonexistent_material_constant",
            "role": "negative_benchmark",
            "expected_unit": None,
            "query_terms": ["nonexistent material constant qzxv"],
        }
    )
    negative_set = requirement_set.model_copy(update={"requirements": [negative]})
    negative_client = _AlwaysNotFoundClient()
    negative_pipeline = RequirementEvidencePipeline(
        RequirementEvidenceExtractor(negative_client, model=negative_client.model),
        repository=repository,
        store=store,
    )
    negative_run = negative_pipeline.analyze(negative_set)
    metrics = evaluate_evidence_run(
        candidates,
        windows,
        positive_run.results[0],
        RetrievalGold(
            relevant_paper_ids={"04_arxiv_2502.16530.pdf"},
            relevant_block_ids={gold_block.block_id},
            expected_value=3.0,
            expected_unit="J/cm2",
            expected_conditions={"material": "diamond", "laser_type": "fs"},
        ),
        paper_k=3,
        block_k=8,
        negative_results=negative_run.results,
    )

    assert metrics.paper_recall_at_k == 1.0
    assert metrics.evidence_block_recall_at_k == 1.0
    assert metrics.paper_mrr == 1.0
    assert metrics.source_attribution_accuracy == 1.0
    assert metrics.numerical_extraction_precision == 1.0
    assert metrics.numerical_extraction_recall == 1.0
    assert metrics.unit_accuracy == 1.0
    assert metrics.condition_linkage_accuracy == 1.0
    assert metrics.false_satisfied_rate == 0.0
    assert negative_run.fallback_requirements[0]["category"] == "CALIBRATION_REQUIREMENT"
