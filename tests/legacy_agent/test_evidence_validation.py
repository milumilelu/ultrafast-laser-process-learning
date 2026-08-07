"""batch-aware 验证 + 对抗性单位抽取基准（RAG→Evidence 正确性）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ultrafast_e2p.application.model_selection import (
    assert_no_group_leakage,
    group_cv_splits,
    select_model,
)
from ultrafast_knowledge.rag.parameter_recommendation import (
    _coerce_value,
    _text_observations,
)

# ---------------- E. batch-aware validation ----------------

def test_group_cv_by_batch_is_leakage_free() -> None:
    """以 batch 为 Group 做 LOBO 风格验证：同批次重复点绝不跨 train/test。"""
    batches = [f"B{index // 6}" for index in range(18)]  # 3 批，每批 6 行
    splitter, folds = group_cv_splits(batches)
    splits = list(splitter.split(np.zeros(len(batches)), np.zeros(len(batches)), batches))
    assert_no_group_leakage(splits, batches)
    assert folds == 3


def test_select_model_with_batch_groups_runs_and_keeps_splits() -> None:
    rng = np.random.default_rng(3)
    n = 24
    x = pd.DataFrame({"a": rng.uniform(0, 1, n), "b": rng.uniform(0, 1, n)})
    y = pd.Series(2.0 * x["a"] - 1.0 * x["b"] + rng.normal(0, 0.1, n))
    batches = [f"B{index // 8}" for index in range(n)]
    result = select_model(
        x, y, batches, candidate_models=["RSM", "GPR"], max_folds=3, random_seed=7
    )
    assert result.cv_folds == 3
    assert result.selected_model in {"RSM", "GPR"}
    assert result.metrics_by_model[result.selected_model]["cv_folds"] == 3


def test_group_cv_by_equipment_is_leave_one_equipment_out() -> None:
    """以设备为 Group：跨设备泛化验证（LOEO）。"""
    equipment = ["EQ-A", "EQ-A", "EQ-A", "EQ-B", "EQ-B", "EQ-B"]
    splitter, folds = group_cv_splits(equipment)
    splits = list(splitter.split(np.zeros(6), np.zeros(6), equipment))
    assert_no_group_leakage(splits, equipment)
    assert folds == 2


# ---------------- F. adversarial unit / identity extraction ----------------

def test_unit_conversion_frequency_khz() -> None:
    assert _coerce_value("20", "MHz", "frequency_kHz")["value"] == 20_000.0
    assert _coerce_value("500", "Hz", "frequency_kHz")["value"] == 0.5
    assert _coerce_value("10", "kHz", "frequency_kHz")["value"] == 10.0


def test_unit_conversion_power_w() -> None:
    assert _coerce_value("5", "mW", "laser_power_W")["value"] == 0.005
    assert _coerce_value("3", "W", "laser_power_W")["value"] == 3.0


def test_unit_conversion_pulse_width_fs() -> None:
    assert _coerce_value("800", "fs", "pulse_width_fs")["value"] == 800.0
    assert _coerce_value("0.5", "ps", "pulse_width_fs")["value"] == 500.0


def test_unit_conversion_scan_speed() -> None:
    assert _coerce_value("1", "m/s", "scan_speed_mm_s")["value"] == 1000.0
    assert _coerce_value("50", "mm/s", "scan_speed_mm_s")["value"] == 50.0


def test_unit_conversion_hatch_spacing() -> None:
    assert _coerce_value("0.5", "mm", "hatch_spacing_um")["value"] == 500.0
    assert _coerce_value("40", "um", "hatch_spacing_um")["value"] == 40.0


@pytest.mark.parametrize(
    "text,name,expected_value,expected_unit",
    [
        ("重复频率 20 MHz", "frequency_kHz", 20_000.0, "kHz"),
        ("平均功率 5 mW", "laser_power_W", 0.005, "W"),
        ("脉宽 0.5 ps", "pulse_width_fs", 500.0, "fs"),
        ("扫描速度 1 m/s", "scan_speed_mm_s", 1000.0, "mm/s"),
        ("填充间距 0.5 mm", "hatch_spacing_um", 500.0, "um"),
    ],
)
def test_text_observations_apply_units(text, name, expected_value, expected_unit) -> None:
    observations = _text_observations(text, name, "P-1:C-1")
    assert observations, f"未抽取到 {name}"
    value = observations[0]
    assert value["value"] == pytest.approx(expected_value)
    assert value["unit"] == expected_unit


def test_mixed_units_are_kept_separate() -> None:
    """同一段落同时出现 kHz 与 MHz 时必须分别换算，不能混淆。"""
    text = "频率 10 kHz，重复频率 2 MHz 范围内扫描"
    observations = _text_observations(text, "frequency_kHz", "P-1:C-1")
    values = sorted(item["value"] for item in observations)
    assert values == [10.0, 2000.0]
    # 无别名锚点的数值（范围端点）不抽取：保守契约，避免误读
    anchored = _text_observations("频率 10 kHz 至 2 MHz", "frequency_kHz", "P-1:C-1")
    assert [item["value"] for item in anchored] == [10.0]
