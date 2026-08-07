from __future__ import annotations

import json
from types import SimpleNamespace

from ultrafast_knowledge.literature.chunk_builder import _chunk_metadata
from ultrafast_knowledge.rag.hybrid_retriever import HybridRetriever
from ultrafast_knowledge.rag.index_service import _lexical_entry
from ultrafast_knowledge.rag.metadata_filter import (
    apply_metadata_filters_three_way,
    evidence_waterfall,
    match_tier,
    matches_filters_three_way,
    metadata_for_hit,
    tier_for_hit,
)
from ultrafast_knowledge.rag.relaxed_query import _pre_filter_stats, _three_way_stats
from ultrafast_knowledge.rag.reranker import rerank_hits


def _hit(metadata: dict, review_status: str = "accepted") -> dict:

    return {
        "chunk_id": "c-1",
        "paper_id": "p-1",
        "metadata": metadata,
        "review_status": review_status,
    }


def test_match_tier_known_match_with_alias() -> None:
    assert match_tier("CFRP", "碳纤维复合板", "material") == "known_match"
    assert match_tier("碳纤维复合材料", "CFRP", "material") == "known_match"
    assert match_tier("femtosecond", "fs", "laser_type") == "known_match"


def test_match_tier_unknown_for_missing_metadata() -> None:
    assert match_tier(None, "CFRP", "material") == "unknown"
    assert match_tier("", "CFRP", "material") == "unknown"
    assert match_tier([], "CFRP", "material") == "unknown"
    assert match_tier("CFRP", None, "material") == "no_filter"


def test_match_tier_known_mismatch() -> None:
    assert match_tier("Diamond", "CFRP", "material") == "known_mismatch"
    assert match_tier("ps", "fs", "laser_type") == "known_mismatch"


def test_tier_for_hit_with_json_metadata() -> None:
    import json

    hit = {
        "chunk_id": "c-2",
        "paper_id": "p-2",
        "metadata_json": json.dumps({"material": "Diamond", "laser_type": "fs"}),
    }
    tiers = tier_for_hit(hit, {"material": "CFRP", "laser_type": "fs"})
    assert tiers == {"material": "known_mismatch", "laser_type": "known_match"}


def test_tier_for_hit_unknown_when_no_material_tag() -> None:
    hit = {"chunk_id": "c-3", "paper_id": "p-3", "metadata": {"laser_type": "fs"}}
    tiers = tier_for_hit(hit, {"material": "CFRP"})
    assert tiers == {"material": "unknown"}


def test_canonical_metadata_wins_over_conflicting_legacy_projection() -> None:
    hit = _hit(
        {
            "material": "Diamond",
            "process_type": "cutting",
            "primary_material": ["CFRP"],
            "primary_process": "surface_roughening",
        }
    )
    metadata = metadata_for_hit(hit)
    assert metadata["material"] == "CFRP"
    assert metadata["process_type"] == "surface_roughening"
    assert tier_for_hit(
        hit,
        {"material": "CFRP", "process_type": "surface_roughening"},
    ) == {"material": "known_match", "process_type": "known_match"}
    assert not matches_filters_three_way(hit, {"material": "Diamond"})


def test_canonical_unknown_is_not_overridden_by_legacy_tag() -> None:
    hit = _hit({"material": "CFRP", "primary_material": []})
    assert tier_for_hit(hit, {"material": "CFRP"}) == {"material": "unknown"}
    assert matches_filters_three_way(hit, {"material": "CFRP"})


def test_year_range_compares_paper_year_and_keeps_unknown() -> None:
    hit = _hit({"year": "2021", "primary_material": ["CFRP"]})
    assert tier_for_hit(hit, {"year_min": 2020, "year_max": 2022}) == {
        "year_min": "known_match",
        "year_max": "known_match",
    }
    assert not matches_filters_three_way(hit, {"year_min": 2022})
    assert matches_filters_three_way(_hit({"primary_material": ["CFRP"]}), {"year_min": 2022})


def test_three_way_filter_keeps_unknown_drops_mismatch() -> None:
    hits = [
        _hit({"material": "CFRP"}, "accepted"),
        _hit({"material": "Diamond"}, "accepted"),
        _hit({"laser_type": "fs"}, "accepted"),
    ]
    kept, counts = apply_metadata_filters_three_way(hits, {"material": "CFRP"})
    assert {h["metadata"]["material"] for h in kept if "material" in h["metadata"]} == {"CFRP"}
    assert any("metadata_match_tiers" in hit for hit in kept)
    unknown_hit = next(h for h in kept if "material" not in h["metadata"])
    assert unknown_hit["metadata_match_tiers"] == {"material": "unknown"}
    assert counts == {"known_match": 1, "unknown": 1, "known_mismatch": 1, "no_filter": 0}


def test_three_way_rejects_reviewed_rejected() -> None:
    hits = [_hit({"material": "CFRP"}, "rejected")]
    kept, counts = apply_metadata_filters_three_way(hits, {"material": "CFRP"})
    assert kept == []
    assert counts["known_mismatch"] == 0


def test_matches_filters_three_way() -> None:
    assert matches_filters_three_way(_hit({"material": "CFRP"}), {"material": "CFRP"})
    assert matches_filters_three_way(_hit({"laser_type": "fs"}), {"material": "CFRP"})
    assert not matches_filters_three_way(_hit({"material": "Diamond"}), {"material": "CFRP"})
    assert matches_filters_three_way(_hit({"material": "CFRP"}), None)


def test_evidence_waterfall_reports_three_way_tiers() -> None:
    raw = [
        _hit({"material": "CFRP", "not_usable_for": ["direct_parameter_recommendation"]}, "accepted"),
        _hit({"material": "Diamond"}, "accepted"),
        _hit({"laser_type": "fs"}, "accepted"),
    ]
    waterfall = evidence_waterfall(raw, {"material": "CFRP"}, "literature_background")
    assert waterfall["scope_match"] == 2
    assert waterfall["three_way"] == {"known_match": 1, "unknown": 1, "known_mismatch": 1, "no_filter": 0}


def test_relaxed_three_way_stats() -> None:
    hits = [
        _hit({"material": "CFRP"}),
        _hit({"material": "Diamond"}),
        _hit({"laser_type": "fs"}),
        _hit({"material": "SiCp/Al", "laser_type": "fs"}),
    ]
    stats = _three_way_stats(hits, {"material": "CFRP"})
    assert stats == {"known_match": 1, "unknown": 1, "known_mismatch": 2, "no_filter": 0}


def test_relaxed_stats_use_pre_filter_waterfall() -> None:
    expected = {"known_match": 2, "unknown": 1, "known_mismatch": 7, "no_filter": 0}
    pack = {
        "hits": [_hit({"primary_material": ["CFRP"]})],
        "retrieval_metadata": {"evidence_waterfall": {"three_way": expected}},
    }
    assert _pre_filter_stats(pack, {"material": "CFRP"}) == expected


def test_alias_known_match_receives_rerank_boost() -> None:
    alias_hit = {
        **_hit({"primary_material": ["碳纤维复合板"]}),
        "chunk_id": "alias",
        "score": 0.5,
    }
    unknown_hit = {
        **_hit({"primary_material": []}),
        "chunk_id": "unknown",
        "score": 0.55,
    }
    ranked = rerank_hits([unknown_hit, alias_hit], {"material": "CFRP"}, top_k=2)
    assert [hit["chunk_id"] for hit in ranked] == ["alias", "unknown"]
    assert ranked[0]["score"] == 0.62


def test_chunk_metadata_projects_canonical_fields_over_legacy() -> None:
    metadata = _chunk_metadata(
        {
            "paper_id": "p-1",
            "material": "Diamond",
            "process_type": "cutting",
            "primary_material": '["CFRP"]',
            "primary_material_grade": '{"CFRP": "T300"}',
            "primary_process": "surface_roughening",
        },
        SimpleNamespace(
            artifact_id="a-1",
            section_type="methods",
            section_title="Methods",
            page_start=2,
            page_end=3,
        ),
    )
    assert metadata["primary_material"] == ["CFRP"]
    assert metadata["material"] == "CFRP"
    assert metadata["primary_process"] == "surface_roughening"
    assert metadata["process_type"] == "surface_roughening"


def test_lexical_entry_text_uses_canonical_metadata() -> None:
    entry = _lexical_entry(
        {
            "chunk_id": "c-1",
            "content": "fluence response",
            "canonical_title": "A study",
            "material": "Diamond",
            "process_type": "cutting",
            "primary_material": '["CFRP"]',
            "primary_material_grade": '{"CFRP": "T300"}',
            "primary_process": "surface_roughening",
            "metadata_json": json.dumps(
                {
                    "material": "Diamond",
                    "process_type": "cutting",
                    "primary_material": ["CFRP"],
                    "primary_process": "surface_roughening",
                }
            ),
        }
    )
    assert entry["material"] == "CFRP"
    assert entry["process_type"] == "surface_roughening"
    assert "CFRP" in entry["content"]
    assert "Diamond" not in entry["content"]


def test_hybrid_retriever_preserves_pre_filter_candidate_set() -> None:
    raw_hits = [
        {**_hit({"primary_material": ["CFRP"]}), "chunk_id": "match", "score": 0.9},
        {**_hit({"primary_material": ["Diamond"]}), "chunk_id": "mismatch", "score": 0.8},
        {**_hit({"primary_material": []}), "chunk_id": "unknown", "score": 0.7},
    ]

    class Embedding:
        def embed_query(self, query: str) -> list[float]:
            return [1.0]

    class LexicalIndex:
        def search(self, query: str, top_k: int) -> list[dict]:
            return raw_hits[:top_k]

    class VectorStore:
        def query(self, vector: list[float], top_k: int, filters=None) -> list[dict]:
            assert filters is None
            return []

    result = HybridRetriever(Embedding(), VectorStore(), LexicalIndex()).retrieve(
        "CFRP", {"material": "CFRP"}, rerank_top_k=3
    )
    assert {hit["chunk_id"] for hit in result["raw_hits"]} == {
        "match",
        "mismatch",
        "unknown",
    }
    assert {hit["chunk_id"] for hit in result["hits"]} == {"match", "unknown"}
