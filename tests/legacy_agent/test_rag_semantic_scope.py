"""Canonical TaskScope / Ontology 回归测试：

CFRP 的中文/英文别名必须解析到同一个 Canonical ID；
RAG metadata 过滤与 Evidence Pack 的 scope 匹配必须与别名无关。
"""

from __future__ import annotations

from ultrafast_knowledge.rag.evidence_pack import build_evidence_pack
from ultrafast_knowledge.rag.metadata_filter import (
    apply_metadata_filters,
    evidence_waterfall,
    matches_filters,
)
from ultrafast_shared.ontology import (
    canonical_task_scope,
    resolve,
    resolve_material,
    resolve_process_type,
)


def test_cfrp_aliases_resolve_to_same_canonical_id() -> None:
    for alias in (
        "CFRP",
        "cfrp",
        "碳纤维复合材料",
        "碳纤维复合板",
        "碳纤维增强复合材料",
        "carbon fiber reinforced polymer",
        "carbon fibre reinforced plastic",
    ):
        assert resolve_material(alias) == "CFRP", alias


def test_other_materials_and_unknown_values() -> None:
    assert resolve_material("碳化硅陶瓷") == "SiC"
    assert resolve_material("氧化锆") == "ZrO2"
    assert resolve_material("zirconia") == "ZrO2"
    assert resolve_material("钛合金TC4") == "Ti6Al4V"
    assert resolve_material("完全未知的材料") is None


def test_process_and_laser_aliases() -> None:
    assert resolve_process_type("矩形槽") == "rectangular_groove"
    assert resolve_process_type("表面毛化") == "surface_roughening"
    assert resolve_process_type("切割") == "cutting"
    assert resolve("laser_type", "飞秒") == "fs"
    assert resolve("laser_type", "picosecond") == "ps"
    assert resolve("target", "表面粗糙度") == "roughness_um"
    assert resolve("target", "深度") == "depth_um"


def test_canonical_task_scope_normalization_flag() -> None:
    scope = canonical_task_scope(
        material="碳纤维复合板",
        laser_type="飞秒",
        process_type="表面毛化",
        target_metric="表面粗糙度",
        equipment_id="EQ-TEST-FS",
    )
    assert scope["material_id"] == "CFRP"
    assert scope["laser_type"] == "fs"
    assert scope["process_type"] == "surface_roughening"
    assert scope["target_metric"] == "roughness_um"
    assert scope["normalized"] is True

    unresolved = canonical_task_scope(material="某未知材料", laser_type="fs")
    assert unresolved["normalized"] is False
    assert unresolved["material_id"] == "某未知材料"


def _hit(material: str, review_status: str = "accepted") -> dict:
    return {
        "chunk_id": f"chunk-{material}",
        "paper_id": f"paper-{material}",
        "content": "text",
        "score": 0.9,
        "review_status": review_status,
        "metadata": {"material": material, "process_type": "surface_roughening"},
    }


def test_metadata_filter_matches_cfrp_aliases() -> None:
    hits = [
        _hit("碳纤维复合板"),
        _hit("carbon fiber reinforced polymer"),
        _hit("CFRP"),
        _hit("SiC"),
    ]
    matched = apply_metadata_filters(hits, {"material": "CFRP"})
    assert {hit["metadata"]["material"] for hit in matched} == {
        "碳纤维复合板",
        "carbon fiber reinforced polymer",
        "CFRP",
    }

    reverse = apply_metadata_filters([_hit("CFRP")], {"material": "碳纤维复合板"})
    assert len(reverse) == 1


def test_matches_filters_is_symmetric_across_aliases() -> None:
    assert matches_filters(_hit("碳纤维复合材料"), {"material": "CFRP"})
    assert matches_filters(_hit("CFRP"), {"material": "carbon fiber reinforced polymer"})
    assert not matches_filters(_hit("SiC"), {"material": "CFRP"})


def test_evidence_pack_matched_condition_uses_canonical_scope() -> None:
    hits = [
        _hit("碳纤维复合板"),
        _hit("carbon fibre composite"),
        _hit("CFRP"),
    ]
    pack = build_evidence_pack(
        "CFRP roughening",
        {"material": "CFRP", "process_type": "surface_roughening"},
        hits,
        purpose="literature_background",
    )
    assert pack["evidence_status"] == "sufficient"


def test_evidence_waterfall_layers() -> None:
    raw = [
        _hit("SiC", "accepted"),
        _hit("CFRP", "accepted"),
        _hit("CFRP", "pending_review"),
        {"chunk_id": "c4", "paper_id": "p4", "content": "x", "score": 0.1, "review_status": "accepted", "metadata": {"material": "ZrO2"}},
    ]
    waterfall = evidence_waterfall(raw, {"material": "CFRP"}, "literature_background")
    assert waterfall["raw_hits"] == 4
    assert waterfall["scope_match"] == 2
    assert waterfall["reviewed"] == 1
    assert waterfall["purpose_eligible"] == 1
    assert waterfall["prior_eligible"] == 0  # literature_background 非 prior 权限
