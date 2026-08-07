"""RAG → Topic2 Evidence[] 转换链测试（确定性抽取，不依赖 LLM）。"""

from __future__ import annotations

import pytest

from ultrafast_knowledge.rag.evidence_converter import (
    PARAMETER_MAPPING,
    rag_evidence_to_topic2,
)


class _FakeHit:
    def __init__(self, content: str, paper: str = "P-042", review_status: str = "approved"):
        self._content = content
        self._paper = paper
        self._review_status = review_status

    def get(self, key, default=None):
        if key == "content":
            return self._content
        if key == "paper_id":
            return self._paper
        if key == "chunk_id":
            return f"{self._paper}-C1"
        if key == "page_start":
            return 3
        if key == "review_status":
            return self._review_status
        if key == "evidence_level":
            return "literature_evidence"
        if key == "metadata":
            return {"material": "SiC", "review_status": self._review_status}
        return default


def _fake_query(payload, *args, **kwargs):
    return {
        "hits": [
            {
                "chunk_id": "C1",
                "paper_id": "P-042",
                "page_start": 3,
                "content": (
                    "实验发现：扫描速度 50 mm/s、重复频率 20 kHz 时获得最大加工深度。"
                ),
                "review_status": "approved",
                "evidence_level": "literature_evidence",
                "metadata": {"material": "SiC", "review_status": "approved"},
            }
        ],
        "evidence_status": "sufficient",
        "retrieval_metadata": {"evidence_waterfall": {"raw_hits": 1, "reviewed": 1}},
    }


def test_converter_builds_topic2_evidence(monkeypatch) -> None:

    monkeypatch.setattr("ultrafast_knowledge.rag.relaxed_query.query_rag", _fake_query)

    result = rag_evidence_to_topic2(
        {
            "material": "SiC",
            "laser_type": "fs",
            "geometry_type": "rectangular_groove",
            "equipment_id": "EQ-REAL",
            "target": "depth_um",
        },
        top_k=8,
    )
    assert result["retrieved_hits"] == 1
    assert result["reviewed_hits"] == 1
    evidence = result["evidence"]
    assert evidence, "含参数锚点的文本必须能编译出证据"
    params = {item["parameter"] for item in evidence}
    assert "scan_speed_mm_s" in params
    assert "frequency_kHz" in params
    for item in evidence:
        assert item["claim_type"] == "range_preference"
        assert item["target"] == "depth_um"
        assert item["review_status"] == "pending"
        assert item["provenance"]["review_id"] is None
        assert item["claim"]["lower"] < item["claim"]["upper"]
        assert item["provenance"]["source_id"]
        assert item["scope"]["equipment_id"] == "EQ-REAL"


def test_converter_maps_pulse_width_fs_to_ps(monkeypatch) -> None:
    def fake(payload, *args, **kwargs):
        return {
            "hits": [
                {
                    "chunk_id": "C2",
                    "paper_id": "P-7",
                    "page_start": 1,
                    "content": "脉宽 500 fs 时去除率最高。",
                    "review_status": "approved",
                    "evidence_level": "literature_evidence",
                    "metadata": {"review_status": "approved"},
                }
            ],
            "evidence_status": "sufficient",
            "retrieval_metadata": {},
        }

    monkeypatch.setattr("ultrafast_knowledge.rag.relaxed_query.query_rag", fake)
    result = rag_evidence_to_topic2(
        {"material": "SiC", "target": "depth_um"},
        top_k=4,
    )
    evidence = result["evidence"]
    assert evidence
    pulse = next(item for item in evidence if item["parameter"] == "pulse_width_ps")
    # 500 fs → 0.5 ps；单一观测 → 显式标记的推导区间（±10%）
    assert pulse["claim"]["lower"] == pytest.approx(0.45)
    assert pulse["claim"]["upper"] == pytest.approx(0.55)
    assert pulse["claim"]["derived"] is True


def test_mapping_table_uses_topic2_names() -> None:
    topic2_names = {name for name, _ in PARAMETER_MAPPING.values()}
    assert "pulse_width_ps" in topic2_names
    assert "frequency_kHz" in topic2_names
    assert "scan_speed_mm_s" in topic2_names
    assert "hatch_spacing_um" in topic2_names
    assert "passes" in topic2_names


def test_converter_returns_empty_evidence_without_anchored_values(monkeypatch) -> None:
    def fake(payload, *args, **kwargs):
        return {
            "hits": [
                {
                    "chunk_id": "C3",
                    "paper_id": "P-9",
                    "page_start": 1,
                    "content": "该文综述了超快激光加工的物理机制与实验现象。",
                    "review_status": "approved",
                    "evidence_level": "literature_evidence",
                    "metadata": {"review_status": "approved"},
                }
            ],
            "evidence_status": "partial",
            "retrieval_metadata": {},
        }

    monkeypatch.setattr("ultrafast_knowledge.rag.relaxed_query.query_rag", fake)
    result = rag_evidence_to_topic2({"material": "SiC", "target": "depth_um"})
    assert result["evidence"] == []
    assert result["reviewed_hits"] == 1

