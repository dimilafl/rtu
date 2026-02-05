"""Tests for comms budget math."""

from sqe.comms.budget import (
    BudgetConfig,
    BudgetThresholds,
    compute_utilization_status,
    expected_bytes,
)
from sqe.comms.schema import CommsAggregate


def _make_config(
    *,
    scan_interval_ms: int = 1000,
    capacity_bps: int = 800,
    utilization_degraded: float = 0.7,
    utilization_critical: float = 0.9,
    low_headroom: float = 0.1,
) -> BudgetConfig:
    return BudgetConfig(
        enabled=True,
        scan_interval_ms=scan_interval_ms,
        bytes_per_signal_estimate=18,
        protocol_overhead_bytes=200,
        default_capacity_bps_by_type={
            "rtu": capacity_bps,
            "poll_group": capacity_bps,
            "comms_domain": capacity_bps,
        },
        per_node_capacity_bps={},
        thresholds=BudgetThresholds(
            utilization_degraded=utilization_degraded,
            utilization_critical=utilization_critical,
            low_headroom=low_headroom,
        ),
    )


def _make_aggregate(bytes_tx_total: int, bytes_rx_total: int) -> CommsAggregate:
    return CommsAggregate(
        node_id="rtu-1",
        node_type="RTU",
        scan_index=5,
        scan_timestamp=123.0,
        sample_count=1,
        timeout_rate=0.0,
        retry_rate=0.0,
        crc_error_rate=0.0,
        avg_poll_cycle_ms=None,
        avg_jitter_ms=None,
        bytes_tx_total=bytes_tx_total,
        bytes_rx_total=bytes_rx_total,
    )


def test_expected_bytes_clamps_negative_counts():
    cfg = _make_config()
    assert expected_bytes(-5, cfg) == 200
    assert expected_bytes(3, cfg) == 254


def test_observed_bps_math_for_scan_intervals():
    cfg = _make_config(scan_interval_ms=1000)
    agg = _make_aggregate(100, 100)
    status = compute_utilization_status(
        node_type="RTU",
        node_id="rtu-1",
        scan_index=1,
        scan_timestamp=1.0,
        descendant_signal_count=0,
        agg=agg,
        cfg=cfg,
    )
    assert status.observed_bps == 1600.0

    cfg_half = _make_config(scan_interval_ms=500)
    status_half = compute_utilization_status(
        node_type="RTU",
        node_id="rtu-1",
        scan_index=1,
        scan_timestamp=1.0,
        descendant_signal_count=0,
        agg=agg,
        cfg=cfg_half,
    )
    assert status_half.observed_bps == 3200.0


def test_utilization_and_headroom_exact_values():
    cfg = _make_config(scan_interval_ms=1000, capacity_bps=2000)
    agg = _make_aggregate(62, 63)
    status = compute_utilization_status(
        node_type="RTU",
        node_id="rtu-1",
        scan_index=1,
        scan_timestamp=1.0,
        descendant_signal_count=0,
        agg=agg,
        cfg=cfg,
    )
    assert status.observed_bps == 1000.0
    assert status.utilization == 0.5
    assert status.headroom == 0.5


def test_threshold_boundaries_for_levels():
    cfg = _make_config(scan_interval_ms=1000, capacity_bps=800)
    degraded_agg = _make_aggregate(70, 0)
    degraded = compute_utilization_status(
        node_type="RTU",
        node_id="rtu-1",
        scan_index=1,
        scan_timestamp=1.0,
        descendant_signal_count=0,
        agg=degraded_agg,
        cfg=cfg,
    )
    assert degraded.level == "DEGRADED"

    critical_agg = _make_aggregate(90, 0)
    critical = compute_utilization_status(
        node_type="RTU",
        node_id="rtu-1",
        scan_index=1,
        scan_timestamp=1.0,
        descendant_signal_count=0,
        agg=critical_agg,
        cfg=cfg,
    )
    assert critical.level == "CRITICAL"
