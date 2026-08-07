from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

def _repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while not (current / "pyproject.toml").exists() and current.parent != current:
        current = current.parent
    return current


REPO_ROOT = _repo_root()
EVALUATOR_PATH = REPO_ROOT / "benchmarks" / "literature_metadata" / "scripts" / "evaluate_extraction.py"


def _load_evaluator():
    spec = importlib.util.spec_from_file_location("literature_metadata_evaluator", EVALUATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


E = _load_evaluator()
check_schema = E.check_schema
compute_metrics = E.compute_metrics
load_jsonl = E.load_jsonl
schema_check = E.schema_check
wilson_ci = E.wilson_ci

GOLD = [
    {
        "paper_id": "p1",
        "title": "Diamond lens",
        "is_review": False,
        "primary_material": ["Diamond"],
        "material_grade": {"Diamond": "single crystal"},
        "primary_process": "micromachining",
        "laser_type": "fs",
        "wavelength_nm": 800,
        "pulse_width": {"value": 50, "unit": "fs", "evidence": "50 fs"},
        "geometry": "lens",
        "material_mentions": [{"raw_text": "diamond", "canonical_material_id": "Diamond", "role": "primary_workpiece", "page": 1}],
        "process_mentions": [{"raw_text": "micromachining", "canonical_process_id": "micromachining", "role": "primary_process", "page": 1}],
        "evidence_page_primary_material": 1,
        "notes": "",
    },
    {
        "paper_id": "p2",
        "title": "Unknown material paper",
        "is_review": False,
        "primary_material": [],
        "material_grade": {},
        "primary_process": "",
        "laser_type": "",
        "wavelength_nm": None,
        "pulse_width": None,
        "geometry": "",
        "material_mentions": [],
        "process_mentions": [],
        "evidence_page_primary_material": None,
        "notes": "abstention case",
    },
    {
        "paper_id": "p3",
        "title": "Glass cutting",
        "is_review": False,
        "primary_material": ["Glass"],
        "material_grade": {},
        "primary_process": "cutting",
        "laser_type": "ps",
        "wavelength_nm": 1064,
        "pulse_width": None,
        "geometry": "sheet",
        "material_mentions": [],
        "process_mentions": [],
        "evidence_page_primary_material": None,
        "notes": "",
    },
]


def _record(paper_id: str, **overrides) -> dict:
    base = next(r for r in GOLD if r["paper_id"] == paper_id)
    return dict(base, **overrides)


def test_schema_check_accepts_gold(tmp_path) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in GOLD), encoding="utf-8")
    assert schema_check(load_jsonl(path), path) == []


def test_schema_check_detects_bad_role(tmp_path) -> None:
    bad = [dict(GOLD[0], material_mentions=[{"raw_text": "diamond", "canonical_material_id": "Diamond", "role": "banana", "page": 1}])]
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(bad[0], ensure_ascii=False), encoding="utf-8")
    errors = check_schema(bad[0], str(path), 1)
    assert any("invalid material mention role" in error for error in errors)


def test_compute_metrics_perfect_prediction() -> None:
    metrics = compute_metrics(GOLD, [dict(GOLD[0]), dict(GOLD[1]), dict(GOLD[2])])
    assert metrics["material_exact_accuracy"]["value"] == 1.0
    assert metrics["material_multi_label_f1"]["value"] == 1.0
    assert metrics["material_grade_accuracy"]["value"] == 1.0
    assert metrics["process_accuracy"]["value"] == 1.0
    assert metrics["laser_regime_accuracy"]["value"] == 1.0
    assert metrics["geometry_accuracy"]["value"] == 1.0
    assert metrics["evidence_page_accuracy"]["value"] == 1.0
    assert metrics["material_fp_on_abstain_papers"]["value"] == 0.0


def test_fp_on_gold_empty_material_is_penalized() -> None:
    """方法学 v2：gold 材料为空（非激光论文）时，模型乱报材料必须计入 FP。"""
    pred = [_record("p1", primary_material=["Diamond"]), _record("p2", primary_material=["Diamond"]), _record("p3", primary_material=["Glass"])]
    metrics = compute_metrics(GOLD, pred)
    # p2 gold 空但 pred 报 Diamond → FP；f1 应 < 1
    assert metrics["material_multi_label_f1"]["value"] < 1.0
    assert metrics["material_multi_label_precision"]["value"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["material_fp_on_abstain_papers"]["value"] == 1.0
    assert metrics["material_fp_on_abstain_papers"]["n"] == 1


def test_abstain_counts_in_process_denominator() -> None:
    """方法学 v2：process/laser 分母包含模型 abstain 的样本（abstain 按 miss 计）。"""
    pred = [
        _record("p1", primary_process="", laser_type=""),  # 模型 abstain → 错
        dict(GOLD[1]),
        _record("p3", primary_process="cutting", laser_type="ps"),
    ]
    metrics = compute_metrics(GOLD, pred)
    assert metrics["process_accuracy"]["n"] == 2  # p1 + p3（gold 非空）
    assert metrics["process_accuracy"]["value"] == 0.5  # p1 abstain 算 miss
    assert metrics["laser_regime_accuracy"]["n"] == 2
    assert metrics["laser_regime_accuracy"]["value"] == 0.5


def test_per_field_abstention_metrics() -> None:
    pred = [
        _record("p1", primary_material=["Diamond"], laser_type="fs", primary_process="micromachining"),
        _record("p2"),  # 正确 abstain 全部字段
        _record("p3", primary_material=[], primary_process="", laser_type="", wavelength_nm=None),  # 已知字段全 abstain → miss
    ]
    metrics = compute_metrics(GOLD, pred)
    assert metrics["abstention_recall_primary_material"]["value"] == 1.0  # p2 正确 abstain
    assert metrics["abstention_precision_primary_material"]["value"] == 0.5  # p3 已知却 abstain → 拉低 precision
    assert metrics["abstention_recall_primary_process"]["value"] == 1.0
    assert metrics["abstention_recall_laser_type"]["value"] == 1.0
    assert metrics["abstention_recall_wavelength_nm"]["value"] == 1.0


def test_unknown_miss_rate_removed_in_favor_of_field_accuracy() -> None:
    """旧 unknown_miss_rate 移除：process/laser 的 accuracy 分母已含 abstain。"""
    metrics = compute_metrics(GOLD, [dict(GOLD[0]), dict(GOLD[1]), dict(GOLD[2])])
    assert "unknown_miss_rate" not in metrics
    assert "abstention_recall_primary_material" in metrics


def test_compute_metrics_evidence_page_mismatch() -> None:
    pred = [
        _record("p1", material_mentions=[{"raw_text": "diamond", "canonical_material_id": "Diamond", "role": "primary_workpiece", "page": 2}]),
        dict(GOLD[1]),
        dict(GOLD[2]),
    ]
    metrics = compute_metrics(GOLD, pred)
    assert metrics["evidence_page_accuracy"]["value"] == 0.0
    assert metrics["evidence_page_accuracy"]["n"] == 1


def test_multi_label_f1_partial() -> None:
    gold = [_record("p1", primary_material=["Diamond", "SiC"])]
    pred = [_record("p1", primary_material=["Diamond"])]
    metrics = compute_metrics(gold, pred)
    assert metrics["material_multi_label_precision"]["value"] == 1.0
    assert metrics["material_multi_label_recall"]["value"] == 0.5
    assert metrics["material_multi_label_f1"]["value"] == pytest.approx(2 / 3, abs=1e-4)


def test_wilson_ci_bounds() -> None:
    ci = wilson_ci(10, 10)
    assert ci is not None
    assert ci[0] < 1.0 < ci[1] or abs(ci[1] - 1.0) < 1e-6
    ci_mid = wilson_ci(5, 10)
    assert ci_mid is not None
    assert 0.0 < ci_mid[0] < 0.5 < ci_mid[1] < 1.0
    assert wilson_ci(0, 0) is None
    ci_zero = wilson_ci(0, 10)
    assert ci_zero is not None and ci_zero[0] == 0.0


def test_metrics_json_serializable() -> None:
    metrics = compute_metrics(GOLD, [dict(GOLD[0]), dict(GOLD[1]), dict(GOLD[2])])
    json.dumps(metrics)
