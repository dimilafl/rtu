"""Tests for budget reason ordering."""

from sqe.comms.budget import BudgetConfig, BudgetThresholds, compute_utilization_status
from sqe.comms.schema import CommsAggregate


def _make_config():
    return BudgetConfig(
        enabled=True,
        scan_interval_ms=1000,
        bytes_per_signal_estimate=18,
        protocol_overhead_bytes=200,
        default_capacity_bps_by_type={
            "comms_domain": 800,
            "poll_group": 800,
            "rtu": 800,
        },
        per_node_capacity_bps={},
        thresholds=BudgetThresholds(
            utilization_degraded=0.7,
            utilization_critical=0.9,
            low_headroom=0.2,
        ),
    )


def _make_aggregate(total_bytes: int) -> CommsAggregate:
    return CommsAggregate(
        node_id="rtu-1",
        node_type="RTU",
        scan_index=3,
        scan_timestamp=12.0,
        sample_count=1,
        timeout_rate=0.0,
        retry_rate=0.0,
        crc_error_rate=0.0,
        avg_poll_cycle_ms=None,
        avg_jitter_ms=None,
        bytes_tx_total=total_bytes,
        bytes_rx_total=0,
    )


def test_reason_order_for_critical_and_low_headroom():
    cfg = _make_config()
    agg = _make_aggregate(95)
    status = compute_utilization_status(
        node_type="RTU",
        node_id="rtu-1",
        scan_index=1,
        scan_timestamp=1.0,
        descendant_signal_count=0,
        agg=agg,
        cfg=cfg,
    )
    assert status.reasons == ["UTILIZATION_CRITICAL", "LOW_HEADROOM"]


def test_reason_order_for_degraded_and_low_headroom():
    cfg = _make_config()
    agg = _make_aggregate(80)
    status = compute_utilization_status(
        node_type="RTU",
        node_id="rtu-1",
        scan_index=1,
        scan_timestamp=1.0,
        descendant_signal_count=0,
        agg=agg,
        cfg=cfg,
    )
    assert status.reasons == ["UTILIZATION_DEGRADED", "LOW_HEADROOM"]
