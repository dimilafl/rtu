"""Tests for comms health classification."""

from sqe.comms.health import CommsHealthClass, CommsHealthThresholds, classify_comms_health
from sqe.comms.schema import CommsAggregate


def _make_aggregate(**overrides: float) -> CommsAggregate:
    base = {
        "node_id": "rtu1",
        "node_type": "RTU",
        "scan_index": 1,
        "scan_timestamp": 1.0,
        "sample_count": 10,
        "timeout_rate": 0.0,
        "retry_rate": 0.0,
        "crc_error_rate": 0.0,
        "avg_poll_cycle_ms": 1000.0,
        "avg_jitter_ms": 10.0,
        "bytes_tx_total": 100,
        "bytes_rx_total": 200,
    }
    base.update(overrides)
    return CommsAggregate(**base)


def test_classification_threshold_boundaries() -> None:
    thresholds = CommsHealthThresholds.from_config({})

    ok = classify_comms_health(_make_aggregate(), thresholds)
    assert ok.health_class == CommsHealthClass.OK
    assert ok.reasons == []

    degraded = classify_comms_health(
        _make_aggregate(timeout_rate=thresholds.timeout_rate_degraded), thresholds
    )
    assert degraded.health_class == CommsHealthClass.DEGRADED
    assert degraded.reasons == ["timeout_rate_degraded"]

    critical = classify_comms_health(
        _make_aggregate(retry_rate=thresholds.retry_rate_critical), thresholds
    )
    assert critical.health_class == CommsHealthClass.CRITICAL
    assert critical.reasons == ["retry_rate_critical"]


def test_reasons_ordering() -> None:
    thresholds = CommsHealthThresholds.from_config({})
    aggregate = _make_aggregate(
        timeout_rate=thresholds.timeout_rate_critical,
        retry_rate=thresholds.retry_rate_degraded,
        crc_error_rate=thresholds.crc_rate_degraded,
        avg_jitter_ms=thresholds.jitter_ms_critical,
        avg_poll_cycle_ms=thresholds.poll_cycle_ms_degraded,
    )

    status = classify_comms_health(aggregate, thresholds)

    assert status.reasons == [
        "timeout_rate_critical",
        "retry_rate_degraded",
        "crc_error_rate_degraded",
        "jitter_ms_critical",
        "poll_cycle_ms_degraded",
    ]
