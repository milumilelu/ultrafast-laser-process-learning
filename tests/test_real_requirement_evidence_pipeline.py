"""End-to-end evidence checks over a repository-owned original paper PDF."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from ultrafast_evidence_prior.e2p import compile_beliefs, compile_priors
from ultrafast_evidence_prior.extraction import TypedEvidenceExtractor
from ultrafast_evidence_prior.schemas import (
    ConditionValidationState,
    EquipmentContext,
    EvidenceIRSetV2,
    ResolvedTaskV1,
    TargetMetric,
    ValidationState,
)
from ultrafast_evidence_prior.schemas import (
    EvidenceType as TypedEvidenceType,
)
from ultrafast_evidence_prior.schemas import (
    KnowledgeRequirementType as TypedRequirementType,
)
from ultrafast_evidence_prior.schemas import (
    KnowledgeRequirementV1 as TypedKnowledgeRequirement,
)
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
from ultrafast_knowledge.evidence_pipeline.schemas import EvidenceWindow, PaperCandidate
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


def _typed_task() -> ResolvedTaskV1:
    return ResolvedTaskV1(
        material="diamond",
        target_metric=TargetMetric.DEPTH_UM,
        equipment=EquipmentContext(
            equipment_profile_id="real-paper-benchmark",
            equipment_revision_id="v1",
            profile_name="30 fs, 800 nm system",
            wavelength_nm=800,
            pulse_width_min_fs=25,
            pulse_width_max_fs=35,
            frequency_min_kHz=1,
            frequency_max_kHz=100,
            scan_speed_min_mm_s=1,
            scan_speed_max_mm_s=1000,
        ),
    )


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


class _RecordedTypedClaimClient:
    """Deterministic claim projection over a verbatim block from the original PDF."""

    model = "recorded-real-paper-typed-claim"

    def __init__(
        self,
        *,
        block_ids: list[str],
        quote: str,
        content: dict[str, object],
        conditions: dict[str, object] | None = None,
    ) -> None:
        self.block_ids = block_ids
        self.quote = quote
        self.content = content
        self.conditions = conditions or {}

    def chat(self, _messages, **_kwargs):
        return {
            "content": json.dumps(
                {
                    "status": "FOUND",
                    "items": [
                        {
                            "content": self.content,
                            "conditions": self.conditions,
                            "evidence_quote": self.quote,
                            "source_block_refs": self.block_ids,
                            "extraction_confidence": 0.95,
                        }
                    ],
                }
            )
        }


def _typed_evidence_from_real_block(
    block,
    *,
    content: dict[str, object],
    conditions: dict[str, object] | None = None,
):
    return _typed_evidence_from_real_blocks(
        [block],
        content=content,
        conditions=conditions,
    )


def _typed_evidence_from_real_blocks(
    blocks,
    *,
    content: dict[str, object],
    conditions: dict[str, object] | None = None,
    paper_metadata: dict[str, object] | None = None,
):
    first_block = blocks[0]
    evidence_type = TypedEvidenceType(str(content["evidence_type"]))
    requirement = TypedKnowledgeRequirement(
        requirement_id="kreq-real-paper-numeric",
        requirement_type=TypedRequirementType.MATERIAL_PROPERTY,
        scientific_question="Which numeric parameter is directly reported?",
        target_metric=TargetMetric.DEPTH_UM,
        evidence_types=[evidence_type],
        query_terms=["reported parameter"],
    )
    candidate = PaperCandidate(
        paper_id=first_block.paper_id,
        document_version_id=first_block.document_version_id,
        score=1,
    )
    window = EvidenceWindow(
        window_id=f"window::{first_block.block_id}",
        requirement_id=requirement.requirement_id,
        paper_id=first_block.paper_id,
        center_block_id=first_block.block_id,
        blocks=blocks,
        score=1,
        paper_metadata=paper_metadata or {},
    )
    client = _RecordedTypedClaimClient(
        block_ids=[block.block_id for block in blocks],
        quote=first_block.text,
        content=content,
        conditions=conditions,
    )
    return TypedEvidenceExtractor(client, model=client.model).extract(
        requirement,
        candidate,
        [window],
    ).items[0]


def test_typed_evidence_accepts_real_pdf_numeric_unit_expression(
    indexed_real_corpus,
) -> None:
    store, _repository = indexed_real_corpus
    block = next(
        item
        for item in store.blocks(paper_ids=["04_arxiv_2502.16530.pdf"])
        if "ablation threshold of diamond (3.0 J/cm2)" in item.text
    )

    evidence = _typed_evidence_from_real_block(
        block,
        content={
            "evidence_type": "PARAMETER_VALUE",
            "parameter": "ablation_threshold",
            "value": 3,
            "unit": "J/cm2",
            "statement": "The diamond ablation threshold is 3 J/cm2.",
        },
    )

    assert evidence.validation_state == ValidationState.VALIDATED
    assert evidence.validation_errors == []


def test_typed_evidence_rejects_unit_substring_false_positive_in_real_pdf(
    indexed_real_corpus,
) -> None:
    store, _repository = indexed_real_corpus
    block = next(
        item
        for item in store.blocks(paper_ids=["04_arxiv_2502.16530.pdf"])
        if "only by ~20" in item.text and "500 kJ/cm" in item.text
    )

    evidence = _typed_evidence_from_real_block(
        block,
        content={
            "evidence_type": "PARAMETER_VALUE",
            "parameter": "average_power",
            "value": 20,
            "unit": "W",
            "statement": "The average power is 20 W.",
        },
    )

    assert evidence.validation_state == ValidationState.REJECTED
    assert evidence.validation_errors == [
        "numeric_unit_not_co_located_or_compatible:20.0:W"
    ]


def test_real_process_observation_compiles_to_transfer_observation(
    indexed_real_corpus,
) -> None:
    store, _repository = indexed_real_corpus
    block = next(
        item
        for item in store.blocks(paper_ids=["10_arxiv_2411.18093.pdf"])
        if "laser focal depth is set to 500" in item.text
    )
    evidence = _typed_evidence_from_real_block(
        block,
        content={
            "evidence_type": "PROCESS_OBSERVATION",
            "target_metric": "focal_depth_um",
            "measured_value": 500,
            "unit": "um",
            "statement": "The laser focal depth is set to 500 um below the wafer surface.",
        },
    )
    evidence_set = EvidenceIRSetV2(evidence_set_id="real-observation", items=[evidence])
    beliefs = compile_beliefs(_typed_task(), evidence_set)
    artifacts = compile_priors(evidence_set, beliefs)

    assert evidence.validation_state == ValidationState.VALIDATED
    assert artifacts.priors == []
    assert len(artifacts.observations) == 1
    assert artifacts.observations[0].measured_value == 500
    assert artifacts.observations[0].unit == "um"


def test_real_parameter_effect_preserves_threshold_value(indexed_real_corpus) -> None:
    store, _repository = indexed_real_corpus
    block = next(
        item
        for item in store.blocks(paper_ids=["04_arxiv_2502.16530.pdf"])
        if "doses in excess of 50 kJ/cm2 provide minimal gains" in item.text
    )
    evidence = _typed_evidence_from_real_block(
        block,
        content={
            "evidence_type": "PARAMETER_EFFECT",
            "parameter": "laser_energy_dose",
            "target_metric": "depth_um",
            "direction": "THRESHOLD",
            "threshold_value": 50,
            "lower": None,
            "upper": None,
            "unit": "kJ/cm2",
            "statement": "Doses above 50 kJ/cm2 provide minimal gains in ablation depth.",
        },
    )
    evidence_set = EvidenceIRSetV2(evidence_set_id="real-effect", items=[evidence])
    beliefs = compile_beliefs(_typed_task(), evidence_set)
    artifacts = compile_priors(evidence_set, beliefs)

    assert evidence.validation_state == ValidationState.VALIDATED
    assert len(artifacts.priors) == 1
    assert artifacts.priors[0].threshold_value == 50
    assert artifacts.priors[0].unit == "kJ/cm2"


def test_real_paper_transfer_benchmark_matches_manual_levels(
    indexed_real_corpus,
) -> None:
    store, _repository = indexed_real_corpus
    benchmark_path = REPO_ROOT / "tests" / "fixtures" / "e2p_real_transfer_benchmark.json"
    cases = json.loads(benchmark_path.read_text(encoding="utf-8"))

    for case in cases:
        blocks_by_id = {
            block.block_id: block
            for block in store.blocks(paper_ids=[case["paper_id"]])
        }
        blocks = [blocks_by_id[block_id] for block_id in case["block_ids"]]
        evidence = _typed_evidence_from_real_blocks(
            blocks,
            content={
                "evidence_type": "PROCESS_METHOD",
                "method": "reported laser processing regime",
                "statement": blocks[0].text,
            },
            conditions=case["conditions"],
            paper_metadata=case["paper_metadata"],
        )
        task_data = dict(case["task"])
        material = task_data.pop("material")
        task = ResolvedTaskV1(
            material=material,
            target_metric=TargetMetric.DEPTH_UM,
            equipment=EquipmentContext(
                equipment_profile_id=f"benchmark::{case['case_id']}",
                equipment_revision_id="manual-v1",
                profile_name=case["case_id"],
                **task_data,
            ),
        )
        belief = compile_beliefs(
            task,
            EvidenceIRSetV2(evidence_set_id=case["case_id"], items=[evidence]),
        ).beliefs[0]

        assert evidence.validation_state == ValidationState.VALIDATED, case["case_id"]
        assert all(
            provenance.validation_state == ConditionValidationState.VALIDATED
            for provenance in evidence.condition_provenance.values()
        ), case["case_id"]
        assert belief.transfer_level.value == case["expected_transfer_level"], (
            case["case_id"],
            case["rationale"],
            belief.model_dump(mode="json"),
        )
        assert belief.recommended_prior_strength <= belief.applicability_score


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
