"""Tests for optional comms health in service pipeline."""

from sqe.comms.health import CommsHealthClass, CommsHealthThresholds
from sqe.comms.schema import CommsMetrics
from sqe.core.incidents import IncidentCause, IncidentEngine, IncidentPolicy
from sqe.core.engine import SignalQualityEngine
from sqe.ops.service import RealtimeQualityService


def _build_policy() -> IncidentPolicy:
    return IncidentPolicy(
        start_sqi_threshold=50,
        end_sqi_threshold=60,
        start_persistence_scans=1,
        end_persistence_scans=1,
        critical_sqi_threshold=25,
        component_score_floor=70,
        cause_priority=[
            IncidentCause.MISSING,
            IncidentCause.STALE,
            IncidentCause.STEP,
            IncidentCause.PLAUSIBILITY,
            IncidentCause.DRIFT,
            IncidentCause.SPIKES,
            IncidentCause.NOISE,
            IncidentCause.OSCILLATION,
            IncidentCause.UNKNOWN,
        ],
    )


def _run_service(comms_enabled: bool, comms_metrics=None):
    engine = SignalQualityEngine(scan_interval=0.1)
    service = RealtimeQualityService(
        engine,
        IncidentEngine(_build_policy()),
        comms_enabled=comms_enabled,
        comms_thresholds=CommsHealthThresholds.from_config({}),
    )
    return service.process_scan(
        {"sig1": 1.0},
        timestamp=1.0,
        comms_metrics=comms_metrics,
    )


def test_service_comms_disabled_no_change():
    comms_metrics = [
        CommsMetrics(
            scan_index=0,
            scan_timestamp=1.0,
            signal_id="sig1",
            rtu_id="rtu1",
            poll_group_id="pg1",
            comms_domain_id="cd1",
            poll_cycle_ms=1000.0,
            poll_jitter_ms=10.0,
            timeout_count=0,
            retry_count=0,
            crc_error_count=0,
            bytes_tx=10,
            bytes_rx=20,
        )
    ]

    baseline_scan, baseline_events, baseline_group_events = _run_service(
        comms_enabled=False, comms_metrics=None
    )
    disabled_scan, disabled_events, disabled_group_events = _run_service(
        comms_enabled=False, comms_metrics=comms_metrics
    )

    assert disabled_scan.comms_health is None
    assert baseline_scan.comms_health is None
    assert baseline_events == disabled_events
    assert baseline_group_events == disabled_group_events
    assert set(baseline_scan.processed_signals.keys()) == set(
        disabled_scan.processed_signals.keys()
    )
    for signal_id in baseline_scan.processed_signals:
        baseline_signal = baseline_scan.processed_signals[signal_id]
        disabled_signal = disabled_scan.processed_signals[signal_id]
        assert baseline_signal.sqi == disabled_signal.sqi
        assert baseline_signal.quality_class == disabled_signal.quality_class


def test_service_comms_enabled_returns_health():
    comms_metrics = [
        CommsMetrics(
            scan_index=0,
            scan_timestamp=1.0,
            signal_id="sig1",
            rtu_id="rtu1",
            poll_group_id="pg1",
            comms_domain_id="cd1",
            poll_cycle_ms=1000.0,
            poll_jitter_ms=10.0,
            timeout_count=1,
            retry_count=0,
            crc_error_count=0,
            bytes_tx=10,
            bytes_rx=20,
        )
    ]

    processed_scan, _, _ = _run_service(
        comms_enabled=True, comms_metrics=comms_metrics
    )

    assert processed_scan.comms_health is not None
    assert len(processed_scan.comms_health) == 3
    for status in processed_scan.comms_health:
        assert status.health_class in {
            CommsHealthClass.OK,
            CommsHealthClass.DEGRADED,
            CommsHealthClass.CRITICAL,
        }
