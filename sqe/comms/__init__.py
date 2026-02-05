"""Comms health schema and aggregation utilities."""

from sqe.comms.schema import CommsAggregate, CommsMetrics
from sqe.comms.health import (
    CommsHealthClass,
    CommsHealthStatus,
    CommsHealthThresholds,
    aggregate_comms_metrics,
    classify_comms_health,
    comms_status_sort_key,
    summarize_comms_health,
)

__all__ = [
    "CommsAggregate",
    "CommsMetrics",
    "CommsHealthClass",
    "CommsHealthStatus",
    "CommsHealthThresholds",
    "aggregate_comms_metrics",
    "classify_comms_health",
    "comms_status_sort_key",
    "summarize_comms_health",
]
