"""Single governed Bayesian-optimization bounded context.

Public services are loaded lazily so governance and data-admission code does
not require the heavy numerical modeling stack at import time.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "BORecommendationService",
    "BOStatusService",
    "DatasetValidationService",
    "FeedbackService",
    "OfflineModelingService",
    "RecommendationService",
]


_EXPORTS = {
    "BORecommendationService": ("ultrafast_bo.application.formal_service", "BORecommendationService"),
    "BOStatusService": ("ultrafast_bo.application.services", "BOStatusService"),
    "DatasetValidationService": ("ultrafast_bo.application.services", "DatasetValidationService"),
    "FeedbackService": ("ultrafast_bo.application.services", "FeedbackService"),
    "OfflineModelingService": ("ultrafast_bo.application.services", "OfflineModelingService"),
    "RecommendationService": ("ultrafast_bo.application.services", "RecommendationService"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
