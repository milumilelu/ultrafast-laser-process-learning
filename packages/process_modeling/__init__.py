"""Topic2 建模契约适配层：科学实现已迁移至 ultrafast_e2p.application。

单一执行链：E2P ModelPolicy → ModelRegistry → Group-CV → winner。
本包只保留 Topic2 验收 API 的导入形状，算法一律委托 ultrafast_e2p。
"""

from __future__ import annotations

import sys
from pathlib import Path

_E2P_SRC = Path(__file__).resolve().parents[2] / "ultrafast_laser_memory" / "src"
if str(_E2P_SRC) not in sys.path:
    sys.path.insert(0, str(_E2P_SRC))

from ultrafast_e2p.application.model_registry import (
    ACCEPTANCE_MODELS,
    build_model,
    build_model_specs,
    supports_uncertainty,
)
from ultrafast_e2p.application.model_selection import (
    ModelSelectionResult,
    assert_no_group_leakage,
    comparison_report,
    group_cv_splits,
    select_model,
)

__all__ = [
    "ACCEPTANCE_MODELS",
    "ModelSelectionResult",
    "assert_no_group_leakage",
    "build_model",
    "build_model_specs",
    "comparison_report",
    "group_cv_splits",
    "select_model",
    "supports_uncertainty",
]
