"""Tests for comms aggregation."""

from sqe.comms.health import aggregate_comms_metrics
from sqe.comms.schema import CommsMetrics


def test_aggregate_comms_metrics_deterministic() -> None:
    metrics = [
        CommsMetrics(
            scan_index=10,
            scan_timestamp=123.0,
            signal_id="sig1",
            rtu_id="rtu1",
            poll_group_id="pg1",
            comms_domain_id="cd1",
            poll_cycle_ms=1000.0,
            poll_jitter_ms=50.0,
            timeout_count=1,
            retry_count=2,
            crc_error_count=0,
            bytes_tx=100,
            bytes_rx=200,
        ),
        CommsMetrics(
            scan_index=10,
            scan_timestamp=123.0,
            signal_id="sig2",
            rtu_id="rtu1",
            poll_group_id="pg1",
            comms_domain_id="cd1",
            poll_cycle_ms=1100.0,
            poll_jitter_ms=None,
            timeout_count=0,
            retry_count=1,
            crc_error_count=1,
            bytes_tx=150,
            bytes_rx=250,
        ),
    ]

    aggregates = aggregate_comms_metrics(metrics)

    rtu_agg = aggregates[("RTU", "rtu1")]
    assert rtu_agg.sample_count == 2
    assert rtu_agg.timeout_rate == 0.5
    assert rtu_agg.retry_rate == 1.5
    assert rtu_agg.crc_error_rate == 0.5
    assert rtu_agg.avg_poll_cycle_ms == 1050.0
    assert rtu_agg.avg_jitter_ms == 50.0
    assert rtu_agg.bytes_tx_total == 250
    assert rtu_agg.bytes_rx_total == 450

    pg_agg = aggregates[("POLL_GROUP", "pg1")]
    assert pg_agg.sample_count == 2
    assert pg_agg.timeout_rate == 0.5
    assert pg_agg.retry_rate == 1.5

    cd_agg = aggregates[("COMMS_DOMAIN", "cd1")]
    assert cd_agg.sample_count == 2
    assert cd_agg.avg_poll_cycle_ms == 1050.0
    assert cd_agg.avg_jitter_ms == 50.0
