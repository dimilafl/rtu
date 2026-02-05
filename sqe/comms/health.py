"""Comms health aggregation and classification utilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple

from sqe.comms.schema import CommsAggregate, CommsMetrics


class CommsHealthClass(Enum):
    """Health classification for comms."""

    OK = "OK"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class CommsHealthThresholds:
    """Thresholds for comms health classification."""

    timeout_rate_degraded: float
    timeout_rate_critical: float
    retry_rate_degraded: float
    retry_rate_critical: float
    crc_rate_degraded: float
    crc_rate_critical: float
    jitter_ms_degraded: float
    jitter_ms_critical: float
    poll_cycle_ms_degraded: float
    poll_cycle_ms_critical: float

    @staticmethod
    def from_config(config: Dict[str, float]) -> "CommsHealthThresholds":
        """Build thresholds from a config mapping."""
        return CommsHealthThresholds(
            timeout_rate_degraded=float(config.get("timeout_rate_degraded", 0.02)),
            timeout_rate_critical=float(config.get("timeout_rate_critical", 0.10)),
            retry_rate_degraded=float(config.get("retry_rate_degraded", 0.05)),
            retry_rate_critical=float(config.get("retry_rate_critical", 0.20)),
            crc_rate_degraded=float(config.get("crc_rate_degraded", 0.001)),
            crc_rate_critical=float(config.get("crc_rate_critical", 0.01)),
            jitter_ms_degraded=float(config.get("jitter_ms_degraded", 250.0)),
            jitter_ms_critical=float(config.get("jitter_ms_critical", 750.0)),
            poll_cycle_ms_degraded=float(
                config.get("poll_cycle_ms_degraded", 2000.0)
            ),
            poll_cycle_ms_critical=float(
                config.get("poll_cycle_ms_critical", 5000.0)
            ),
        )


@dataclass(frozen=True)
class CommsHealthStatus:
    """Health status for a comms node."""

    node_id: str
    node_type: str
    scan_index: int
    scan_timestamp: float
    timeout_rate: float
    retry_rate: float
    crc_error_rate: float
    avg_poll_cycle_ms: Optional[float]
    avg_jitter_ms: Optional[float]
    bytes_tx_total: int
    bytes_rx_total: int
    health_class: CommsHealthClass
    reasons: List[str]

    def to_dict(self) -> Dict[str, Optional[object]]:
        """Convert to dictionary with stable key ordering."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "scan_index": self.scan_index,
            "scan_timestamp": self.scan_timestamp,
            "timeout_rate": self.timeout_rate,
            "retry_rate": self.retry_rate,
            "crc_error_rate": self.crc_error_rate,
            "avg_poll_cycle_ms": self.avg_poll_cycle_ms,
            "avg_jitter_ms": self.avg_jitter_ms,
            "bytes_tx_total": self.bytes_tx_total,
            "bytes_rx_total": self.bytes_rx_total,
            "health_class": self.health_class.value,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class CommsHealthSummary:
    """Summary of comms health statuses for troubleshooting."""

    degraded_nodes: List[CommsHealthStatus]
    critical_nodes: List[CommsHealthStatus]

    def to_dict(self) -> Dict[str, List[Dict[str, Optional[object]]]]:
        """Convert to dictionary with stable key ordering."""
        return {
            "degraded_nodes": [status.to_dict() for status in self.degraded_nodes],
            "critical_nodes": [status.to_dict() for status in self.critical_nodes],
        }


def aggregate_comms_metrics(
    metrics: Iterable[CommsMetrics],
) -> Dict[Tuple[str, str], CommsAggregate]:
    """Aggregate comms metrics per topology node."""
    aggregates: Dict[Tuple[str, str], Dict[str, object]] = {}

    for metric in metrics:
        nodes = [("RTU", metric.rtu_id)]
        if metric.poll_group_id:
            nodes.append(("POLL_GROUP", metric.poll_group_id))
        if metric.comms_domain_id:
            nodes.append(("COMMS_DOMAIN", metric.comms_domain_id))

        for node_type, node_id in nodes:
            key = (node_type, node_id)
            aggregate = aggregates.get(key)
            if aggregate is None:
                aggregate = {
                    "scan_index": metric.scan_index,
                    "scan_timestamp": metric.scan_timestamp,
                    "sample_count": 0,
                    "timeout_count": 0,
                    "retry_count": 0,
                    "crc_error_count": 0,
                    "poll_cycle_sum": 0.0,
                    "poll_cycle_count": 0,
                    "jitter_sum": 0.0,
                    "jitter_count": 0,
                    "bytes_tx_total": 0,
                    "bytes_rx_total": 0,
                }
                aggregates[key] = aggregate

            aggregate["sample_count"] = int(aggregate["sample_count"]) + 1
            aggregate["timeout_count"] = int(aggregate["timeout_count"]) + int(
                metric.timeout_count
            )
            aggregate["retry_count"] = int(aggregate["retry_count"]) + int(
                metric.retry_count
            )
            aggregate["crc_error_count"] = int(
                aggregate["crc_error_count"]
            ) + int(metric.crc_error_count)
            if metric.poll_cycle_ms is not None:
                aggregate["poll_cycle_sum"] = float(
                    aggregate["poll_cycle_sum"]
                ) + float(metric.poll_cycle_ms)
                aggregate["poll_cycle_count"] = int(
                    aggregate["poll_cycle_count"]
                ) + 1
            if metric.poll_jitter_ms is not None:
                aggregate["jitter_sum"] = float(aggregate["jitter_sum"]) + float(
                    metric.poll_jitter_ms
                )
                aggregate["jitter_count"] = int(aggregate["jitter_count"]) + 1
            aggregate["bytes_tx_total"] = int(
                aggregate["bytes_tx_total"]
            ) + int(metric.bytes_tx)
            aggregate["bytes_rx_total"] = int(
                aggregate["bytes_rx_total"]
            ) + int(metric.bytes_rx)

    final: Dict[Tuple[str, str], CommsAggregate] = {}
    for (node_type, node_id), aggregate in aggregates.items():
        sample_count = int(aggregate["sample_count"])
        timeout_count = int(aggregate["timeout_count"])
        retry_count = int(aggregate["retry_count"])
        crc_error_count = int(aggregate["crc_error_count"])
        timeout_rate = timeout_count / sample_count if sample_count else 0.0
        retry_rate = retry_count / sample_count if sample_count else 0.0
        crc_error_rate = crc_error_count / sample_count if sample_count else 0.0
        poll_cycle_count = int(aggregate["poll_cycle_count"])
        jitter_count = int(aggregate["jitter_count"])
        avg_poll_cycle = (
            float(aggregate["poll_cycle_sum"]) / poll_cycle_count
            if poll_cycle_count
            else None
        )
        avg_jitter = (
            float(aggregate["jitter_sum"]) / jitter_count if jitter_count else None
        )

        final[(node_type, node_id)] = CommsAggregate(
            node_id=node_id,
            node_type=node_type,
            scan_index=int(aggregate["scan_index"]),
            scan_timestamp=float(aggregate["scan_timestamp"]),
            sample_count=sample_count,
            timeout_rate=timeout_rate,
            retry_rate=retry_rate,
            crc_error_rate=crc_error_rate,
            avg_poll_cycle_ms=avg_poll_cycle,
            avg_jitter_ms=avg_jitter,
            bytes_tx_total=int(aggregate["bytes_tx_total"]),
            bytes_rx_total=int(aggregate["bytes_rx_total"]),
        )
    return final


def classify_comms_health(
    aggregate: CommsAggregate,
    thresholds: CommsHealthThresholds,
) -> CommsHealthStatus:
    """Classify comms health for an aggregate."""
    reasons: List[str] = []
    severity = 0

    def apply_rate(label: str, value: float, degraded: float, critical: float) -> None:
        nonlocal severity
        if value >= critical:
            reasons.append(f"{label}_critical")
            severity = max(severity, 2)
        elif value >= degraded:
            reasons.append(f"{label}_degraded")
            severity = max(severity, 1)

    def apply_value(
        label: str, value: Optional[float], degraded: float, critical: float
    ) -> None:
        nonlocal severity
        if value is None:
            return
        if value >= critical:
            reasons.append(f"{label}_critical")
            severity = max(severity, 2)
        elif value >= degraded:
            reasons.append(f"{label}_degraded")
            severity = max(severity, 1)

    apply_rate(
        "timeout_rate",
        aggregate.timeout_rate,
        thresholds.timeout_rate_degraded,
        thresholds.timeout_rate_critical,
    )
    apply_rate(
        "retry_rate",
        aggregate.retry_rate,
        thresholds.retry_rate_degraded,
        thresholds.retry_rate_critical,
    )
    apply_rate(
        "crc_error_rate",
        aggregate.crc_error_rate,
        thresholds.crc_rate_degraded,
        thresholds.crc_rate_critical,
    )
    apply_value(
        "jitter_ms",
        aggregate.avg_jitter_ms,
        thresholds.jitter_ms_degraded,
        thresholds.jitter_ms_critical,
    )
    apply_value(
        "poll_cycle_ms",
        aggregate.avg_poll_cycle_ms,
        thresholds.poll_cycle_ms_degraded,
        thresholds.poll_cycle_ms_critical,
    )

    if severity >= 2:
        health_class = CommsHealthClass.CRITICAL
    elif severity == 1:
        health_class = CommsHealthClass.DEGRADED
    else:
        health_class = CommsHealthClass.OK

    return CommsHealthStatus(
        node_id=aggregate.node_id,
        node_type=aggregate.node_type,
        scan_index=aggregate.scan_index,
        scan_timestamp=aggregate.scan_timestamp,
        timeout_rate=aggregate.timeout_rate,
        retry_rate=aggregate.retry_rate,
        crc_error_rate=aggregate.crc_error_rate,
        avg_poll_cycle_ms=aggregate.avg_poll_cycle_ms,
        avg_jitter_ms=aggregate.avg_jitter_ms,
        bytes_tx_total=aggregate.bytes_tx_total,
        bytes_rx_total=aggregate.bytes_rx_total,
        health_class=health_class,
        reasons=reasons,
    )


def summarize_comms_health(
    statuses: Iterable[CommsHealthStatus],
    *,
    top_n: int,
) -> CommsHealthSummary:
    """Build a comms summary with deterministic ordering."""
    critical: List[CommsHealthStatus] = []
    degraded: List[CommsHealthStatus] = []

    for status in statuses:
        if status.health_class == CommsHealthClass.CRITICAL:
            critical.append(status)
        elif status.health_class == CommsHealthClass.DEGRADED:
            degraded.append(status)

    critical_sorted = sorted(critical, key=comms_status_sort_key)[:top_n]
    degraded_sorted = sorted(degraded, key=comms_status_sort_key)[:top_n]

    return CommsHealthSummary(
        degraded_nodes=degraded_sorted,
        critical_nodes=critical_sorted,
    )


def comms_status_sort_key(status: CommsHealthStatus) -> Tuple[int, float, int, str]:
    """Deterministic sort key for comms health statuses."""
    node_type_priority = {"COMMS_DOMAIN": 0, "POLL_GROUP": 1, "RTU": 2}
    class_priority = {
        CommsHealthClass.CRITICAL: 0,
        CommsHealthClass.DEGRADED: 1,
        CommsHealthClass.OK: 2,
    }
    return (
        class_priority.get(status.health_class, 99),
        -status.timeout_rate,
        node_type_priority.get(status.node_type, 99),
        status.node_id,
    )
