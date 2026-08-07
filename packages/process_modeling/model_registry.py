"""Deprecated submodule path; canonical registry lives in ultrafast_e2p.application.model_registry."""

from packages.process_modeling import (
    ACCEPTANCE_MODELS,
    build_model,
    build_model_specs,
    supports_uncertainty,
)

__all__ = ["ACCEPTANCE_MODELS", "build_model", "build_model_specs", "supports_uncertainty"]
