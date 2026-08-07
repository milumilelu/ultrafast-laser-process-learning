"""批次5 回归：参数辨识 V2（文档 F6、§32-37）+ 物理特征构建。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ultrafast_knowledge.identification.service import identify_v2
from ultrafast_physics.feature_builder import PhysicsFeatureBuilder


def _raw_frame(n: int = 40, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for index in range(n):
        power = float(rng.uniform(5, 40))
        frequency = float(rng.uniform(50, 200))
        speed = float(rng.uniform(50, 500))
        hatch = float(rng.uniform(20, 80))
        passes = float(rng.integers(1, 8))
        pulse = float(rng.uniform(300, 800))
        # 真机理：归一化注量主导深度
        depth = 5.0 + 30.0 * (power / frequency) / (speed / 1000.0) + rng.normal(0, 0.5)
        rows.append(
            {
                "laser_power_W": power,
                "frequency_kHz": frequency,
                "scan_speed_mm_s": speed,
                "hatch_spacing_um": hatch,
                "passes": passes,
                "pulse_width_fs": pulse,
                "depth_um": depth,
                "parameter_combination_id": f"d{index % 25}",
            }
        )
    return pd.DataFrame(rows)


def test_physics_builder_unavailable_without_spot_radius() -> None:
    """文档 §30/§29：缺 spot radius → 全部物理特征 unavailable。"""
    raw = _raw_frame(5)
    built = PhysicsFeatureBuilder().build(
        raw.to_dict("records"),
        device_properties={},
    )
    assert built.rows == []
    assert "spot_radius_um" in built.missing_device_properties
    assert "peak_fluence" in built.unavailable_features


def test_physics_builder_computes_features_with_device_properties() -> None:
    raw = _raw_frame(5)
    built = PhysicsFeatureBuilder().build(
        raw.to_dict("records"),
        device_properties={
            "spot_radius_um": (10.0, "um"),
            "thermal_diffusivity_m2_s": (1e-6, "m2/s"),
            "ablation_threshold_J_m2": (0.5, "J/cm2"),
        },
    )
    assert built.rows
    assert "pulse_energy" in built.available_features
    assert "peak_fluence" in built.available_features
    assert "normalized_fluence" in built.available_features
    row = built.rows[0]
    assert row["pulse_energy"] > 0
    assert row["normalized_fluence"] > 0


def test_identify_raw_mode_ranks_controllable_parameters() -> None:
    frame = _raw_frame()
    result = identify_v2(
        frame,
        "depth_um",
        frame["parameter_combination_id"],
        mode="raw",
        feature_columns={
            "controllable": ["laser_power_W", "frequency_kHz", "scan_speed_mm_s", "hatch_spacing_um", "passes", "pulse_width_fs"],
            "mechanism": [],
        },
    )
    assert result["mode"] == "raw"
    assert result["cv_strategy"] == "GroupKFold"
    assert result["controllable_ranking"]
    assert result["mechanism_ranking"] == []
    # 双输出：controllable 单独排名
    ranks = [entry["rank"] for entry in result["controllable_ranking"]]
    assert ranks == sorted(ranks)
    importance_total = sum(entry["importance"] for entry in result["controllable_ranking"])
    assert importance_total == pytest.approx(1.0, abs=1e-6)


def test_identify_physics_mode_produces_mechanism_ranking_and_groups() -> None:
    raw = _raw_frame(60)
    built = PhysicsFeatureBuilder().build(
        raw.to_dict("records"),
        device_properties={
            "spot_radius_um": (10.0, "um"),
            "thermal_diffusivity_m2_s": (1e-6, "m2/s"),
            "ablation_threshold_J_m2": (0.5, "J/cm2"),
        },
    )
    frame = pd.DataFrame(built.rows)
    frame["depth_um"] = raw["depth_um"].values
    frame["parameter_combination_id"] = raw["parameter_combination_id"].values
    result = identify_v2(
        frame,
        "depth_um",
        frame["parameter_combination_id"],
        mode="physics",
        feature_columns={
            "controllable": [],
            "mechanism": built.available_features,
        },
    )
    assert result["mode"] == "physics"
    assert result["mechanism_ranking"]
    assert result["controllable_ranking"] == []
    assert result["mechanism_group_importance"]
    assert "energy_delivery" in result["mechanism_group_importance"]
    assert "overlap" in result["mechanism_group_importance"]
    assert "thermal" in result["mechanism_group_importance"]


def test_identify_hybrid_mode_uses_both() -> None:
    raw = _raw_frame(60)
    built = PhysicsFeatureBuilder().build(
        raw.to_dict("records"),
        device_properties={"spot_radius_um": (10.0, "um")},
    )
    frame = pd.DataFrame(built.rows)
    frame["depth_um"] = raw["depth_um"].values
    frame["parameter_combination_id"] = raw["parameter_combination_id"].values
    # hybrid frame 同时含 raw 控制列与物理特征列
    for name in ("laser_power_W", "frequency_kHz", "scan_speed_mm_s"):
        frame[name] = raw[name].values
    result = identify_v2(
        frame,
        "depth_um",
        frame["parameter_combination_id"],
        mode="hybrid",
        feature_columns={
            "controllable": ["laser_power_W", "frequency_kHz", "scan_speed_mm_s"],
            "mechanism": built.available_features,
        },
    )
    assert result["mode"] == "hybrid"
    assert result["controllable_ranking"]
    assert result["mechanism_ranking"]


def test_identify_requires_two_independent_designs() -> None:
    frame = _raw_frame(3)
    frame["parameter_combination_id"] = ["a", "a", "a"]
    with pytest.raises(ValueError):
        identify_v2(frame, "depth_um", frame["parameter_combination_id"], mode="raw")
