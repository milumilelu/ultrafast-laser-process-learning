"""Gaussian-process UCB recommendation with separate hard bounds and soft prior."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from packages.e2p.application.prior_artifact import (
    REPOSITORY_VERIFIED,
    GovernedPriorArtifact,
    compute_prior_content_hash,
)
from packages.e2p.application.soft_prior import (
    PRIOR_SPEC_VERSION,
    decayed_evidence_weight,
    log_prior_score,
)
from packages.process_contracts.schemas import CORE_PARAMETER_NAMES, ParameterBounds
from packages.process_modeling.model_registry import build_model


def _predict_gpr(
    pipeline: Any, candidates: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    transformed = pipeline.named_steps["imputer"].transform(candidates)
    transformed = pipeline.named_steps["scaler"].transform(transformed)
    return pipeline.named_steps["gpr"].predict(transformed, return_std=True)


def _normalize(values: np.ndarray) -> np.ndarray:
    span = float(np.max(values) - np.min(values))
    return (values - np.min(values)) / span if span > 0 else np.zeros_like(values)


def _candidate_frame(
    bounds: dict[str, ParameterBounds], n_candidates: int, random_seed: int
) -> pd.DataFrame:
    rng = np.random.default_rng(random_seed)
    data = {
        name: rng.uniform(bounds[name].lower, bounds[name].upper, n_candidates)
        for name in CORE_PARAMETER_NAMES
    }
    data["passes"] = np.clip(
        np.rint(data["passes"]), bounds["passes"].lower, bounds["passes"].upper
    ).astype(int)
    frame = pd.DataFrame(data)
    lower = {name: bounds[name].lower for name in CORE_PARAMETER_NAMES}
    upper = {name: bounds[name].upper for name in CORE_PARAMETER_NAMES}
    return frame.clip(lower=lower, upper=upper, axis="columns")


def _validated_prior_spec(
    governed_prior: GovernedPriorArtifact | None,
) -> dict[str, Any]:
    if governed_prior is None:
        return {"prior_spec_version": PRIOR_SPEC_VERSION, "range_preferences": []}
    if not isinstance(governed_prior, GovernedPriorArtifact):
        raise TypeError("BO only accepts GovernedPriorArtifact; naked prior_spec is forbidden")
    preferences = governed_prior.prior_spec.get("range_preferences")
    if not isinstance(preferences, list):
        raise TypeError("GovernedPriorArtifact has an invalid prior_spec")
    if preferences:
        if governed_prior.verification != REPOSITORY_VERIFIED:
            raise ValueError("GovernedPriorArtifact is not repository verified")
        if not governed_prior.approval_ids or not governed_prior.evidence_ids:
            raise ValueError("GovernedPriorArtifact is missing approval provenance")
    expected_hash = compute_prior_content_hash(
        governed_prior.prior_spec,
        list(governed_prior.approval_ids),
        governed_prior.scope,
        governed_prior.compiler_version,
    )
    if governed_prior.content_hash != expected_hash:
        raise ValueError("GovernedPriorArtifact content hash mismatch")
    return governed_prior.prior_spec


def recommend_with_soft_prior(
    training: pd.DataFrame,
    target: str,
    bounds: dict[str, ParameterBounds],
    governed_prior: GovernedPriorArtifact | None,
    beta: float,
    lambda_0: float,
    alpha: float,
    n_unique_designs: int,
    n_candidates: int,
    random_seed: int,
    model: Any | None = None,
) -> dict:
    prior_spec = _validated_prior_spec(governed_prior)
    if model is None:
        x = training[list(CORE_PARAMETER_NAMES)]
        y = training[target].astype(float)
        gpr = build_model("GPR", random_seed).fit(x, y)
        model_source = "fitted_for_optimization"
    else:
        gpr = model
        model_source = "persisted_model_artifact"
    candidates = _candidate_frame(bounds, n_candidates, random_seed)
    mean, std = _predict_gpr(gpr, candidates)
    raw_ucb = (-mean if target == "roughness_um" else mean) + beta * std
    normalized_ucb = _normalize(raw_ucb)
    prior_score = log_prior_score(
        {name: candidates[name].to_numpy() for name in candidates}, prior_spec
    )
    lambda_t = decayed_evidence_weight(lambda_0, alpha, n_unique_designs)
    evidence_score = normalized_ucb + lambda_t * prior_score
    vanilla_index = int(np.argmax(normalized_ucb))
    selected_index = int(np.argmax(evidence_score))

    def point(index: int) -> dict[str, float | int]:
        values = candidates.iloc[index].to_dict()
        values["passes"] = int(values["passes"])
        for name, value in values.items():
            if not bounds[name].lower <= float(value) <= bounds[name].upper:
                raise RuntimeError(f"machine bound violated for {name}")
        return values

    return {
        "optimization_method": "GaussianProcess+UCB+E2PSoftPrior",
        "model_source": model_source,
        "recommended_parameters": point(selected_index),
        "vanilla_recommended_parameters": point(vanilla_index),
        "recommendation_changed_by_evidence": selected_index != vanilla_index,
        "prediction": {
            "mean": float(mean[selected_index]),
            "std": float(std[selected_index]),
        },
        "acquisition": {
            "normalized_ucb": float(normalized_ucb[selected_index]),
            "log_prior": float(prior_score[selected_index]),
            "lambda_t": lambda_t,
            "score": float(evidence_score[selected_index]),
        },
        "machine_bounds": {name: bound.model_dump() for name, bound in bounds.items()},
        "prior_spec": prior_spec,
    }
