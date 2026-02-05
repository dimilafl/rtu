"""Deterministic comms capacity budgeting utilities."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Dict, List, Optional

from sqe.comms.schema import CommsAggregate


@dataclass(frozen=True)
class BudgetThresholds:
    """Thresholds for utilization classification."""

    utilization_degraded: float
    utilization_critical: float
    low_headroom: float


@dataclass(frozen=True)
class BudgetConfig:
    """Configuration for deterministic comms capacity budgeting."""

    enabled: bool
    scan_interval_ms: int
    bytes_per_signal_estimate: int
    protocol_overhead_bytes: int
    default_capacity_bps_by_type: Dict[str, int]
    per_node_capacity_bps: Dict[str, int]
    thresholds: BudgetThresholds


@dataclass(frozen=True)
class UtilizationStatus:
    """Deterministic utilization status for a comms node."""

    node_type: str
    node_id: str
    scan_index: int
    scan_timestamp: float
    descendant_signal_count: int
    expected_bytes: int
    observed_bytes: int
    observed_bps: float
    utilization: float
    headroom: float
    level: str
    reasons: List[str]


def capacity_bps_for(node_type: str, node_id: str, cfg: BudgetConfig) -> int:
    """Select capacity in bits per second for the node."""
    if node_id in cfg.per_node_capacity_bps:
        capacity_bps = int(cfg.per_node_capacity_bps[node_id])
    else:
        key = node_type.lower()
        if key not in cfg.default_capacity_bps_by_type:
            raise ValueError(f"Missing default capacity for node type: {node_type}")
        capacity_bps = int(cfg.default_capacity_bps_by_type[key])
    if capacity_bps <= 0:
        raise ValueError("capacity_bps must be positive")
    return capacity_bps


def expected_bytes(descendant_signal_count: int, cfg: BudgetConfig) -> int:
    """Estimate expected bytes for a scan based on descendant signal count."""
    safe_count = max(0, int(descendant_signal_count))
    return int(cfg.protocol_overhead_bytes) + int(cfg.bytes_per_signal_estimate) * safe_count


def observed_bytes_from_aggregate(agg: Optional[CommsAggregate]) -> int:
    """Compute observed bytes from a comms aggregate."""
    if agg is None:
        return 0
    observed = int(agg.bytes_tx_total) + int(agg.bytes_rx_total)
    return max(0, observed)


def compute_utilization_status(
    node_type: str,
    node_id: str,
    scan_index: int,
    scan_timestamp: float,
    descendant_signal_count: int,
    agg: Optional[CommsAggregate],
    cfg: BudgetConfig,
) -> UtilizationStatus:
    """Compute deterministic utilization status for a comms node."""
    if cfg.scan_interval_ms <= 0:
        raise ValueError("scan_interval_ms must be positive")

    observed_bytes = observed_bytes_from_aggregate(agg)
    expected = expected_bytes(descendant_signal_count, cfg)
    capacity_bps = capacity_bps_for(node_type, node_id, cfg)
    observed_bps = observed_bytes * 8.0 / (cfg.scan_interval_ms / 1000.0)
    utilization = observed_bps / float(capacity_bps)
    headroom = 1.0 - utilization

    if not (isfinite(utilization) and isfinite(headroom)):
        raise ValueError("utilization and headroom must be finite")

    reasons: List[str] = []
    if utilization >= cfg.thresholds.utilization_critical:
        level = "CRITICAL"
        reasons.append("UTILIZATION_CRITICAL")
    elif utilization >= cfg.thresholds.utilization_degraded:
        level = "DEGRADED"
        reasons.append("UTILIZATION_DEGRADED")
    else:
        level = "OK"

    if headroom <= cfg.thresholds.low_headroom:
        reasons.append("LOW_HEADROOM")

    return UtilizationStatus(
        node_type=node_type,
        node_id=node_id,
        scan_index=scan_index,
        scan_timestamp=scan_timestamp,
        descendant_signal_count=max(0, int(descendant_signal_count)),
        expected_bytes=expected,
        observed_bytes=observed_bytes,
        observed_bps=observed_bps,
        utilization=utilization,
        headroom=headroom,
        level=level,
        reasons=reasons,
    )
