"""Deprecated submodule path; canonical selection lives in ultrafast_e2p.application.model_selection."""

from packages.process_modeling import (
    ModelSelectionResult,
    assert_no_group_leakage,
    comparison_report,
    group_cv_splits,
    select_model,
)

__all__ = [
    "ModelSelectionResult",
    "assert_no_group_leakage",
    "comparison_report",
    "group_cv_splits",
    "select_model",
]
