from importlib import import_module
from typing import Any

__all__ = [
    "BODatasetSliceService",
    "BOEligibilityService",
    "BOModelRegistry",
    "BOReadinessAssessmentService",
    "BORecommendationService",
    "BOStatusService",
    "ConstrainedBORecommendationService",
    "DatasetValidationService",
    "FeedbackService",
    "OfflineModelingService",
    "RecommendationService",
    "SearchSpaceBuilder",
]


_EXPORTS = {
    "ConstrainedBORecommendationService": (
        "ultrafast_bo.application.constrained_service",
        "ConstrainedBORecommendationService",
    ),
    "BORecommendationService": ("ultrafast_bo.application.formal_service", "BORecommendationService"),
    "BODatasetSliceService": ("ultrafast_bo.application.governance", "BODatasetSliceService"),
    "BOEligibilityService": ("ultrafast_bo.application.governance", "BOEligibilityService"),
    "BOReadinessAssessmentService": (
        "ultrafast_bo.application.governance",
        "BOReadinessAssessmentService",
    ),
    "BOModelRegistry": ("ultrafast_bo.application.lifecycle", "BOModelRegistry"),
    "SearchSpaceBuilder": ("ultrafast_bo.application.search_space", "SearchSpaceBuilder"),
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
