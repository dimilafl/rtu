"""Comms schema definitions for metrics and aggregates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CommsMetrics:
    """Raw comms metrics for a single scan and signal."""

    scan_index: int
    scan_timestamp: float
    signal_id: Optional[str]
    rtu_id: str
    poll_group_id: Optional[str]
    comms_domain_id: Optional[str]
    poll_cycle_ms: Optional[float]
    poll_jitter_ms: Optional[float]
    timeout_count: int
    retry_count: int
    crc_error_count: int
    bytes_tx: int
    bytes_rx: int


@dataclass(frozen=True)
class CommsAggregate:
    """Aggregated comms metrics at a topology node for a scan."""

    node_id: str
    node_type: str
    scan_index: int
    scan_timestamp: float
    sample_count: int
    timeout_rate: float
    retry_rate: float
    crc_error_rate: float
    avg_poll_cycle_ms: Optional[float]
    avg_jitter_ms: Optional[float]
    bytes_tx_total: int
    bytes_rx_total: int
