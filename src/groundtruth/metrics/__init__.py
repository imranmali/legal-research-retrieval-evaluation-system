"""Metric contract, registry and the built-in metric families."""

# Importing the built-in families registers them with the registry.
from groundtruth.metrics import standard as _standard  # noqa: F401
from groundtruth.metrics.base import (
    EMPTY_CONTEXT,
    CutoffPolicy,
    Metric,
    MetricContext,
    MetricInfo,
    available_metrics,
    get_metric,
    register_metric,
)

__all__ = [
    "EMPTY_CONTEXT",
    "CutoffPolicy",
    "Metric",
    "MetricContext",
    "MetricInfo",
    "available_metrics",
    "get_metric",
    "register_metric",
]
