"""Tests for incident engine."""

from typing import Dict

from sqe.core.engine import ProcessedSignal, SignalConfig, SignalQualityEngine
from sqe.core.incidents import (
    IncidentCause,
    IncidentEngine,
    IncidentEventType,
    IncidentPolicy,
)
from sqe.ops.service import RealtimeQualityService


def make_processed(
    signal_id: str,
    timestamp: float,
    sqi: float,
    components: Dict[str, float],
) -> ProcessedSignal:
    return ProcessedSignal(
        signal_id=signal_id,
        timestamp=timestamp,
        raw=10.0,
        filtered_ewma=10.0,
        filtered_ma=10.0,
        highpass=0.0,
        drift=0.0,
        drift_type="none",
        drift_severity=0.0,
        monotonic_samples=0,
        variance=0.0,
        std_dev=0.0,
        noise_level=0.0,
        is_spike=False,
        spike_frequency=0.0,
        oscillation_energy=0.0,
        dominant_frequency=None,
        sqi=sqi,
        quality_class="good",
        sqi_trend="stable",
        sqi_components=components,
        sqi_weights={name: 0.2 for name in components},
        alert_level="warning" if sqi <= 50 else "none",
        drift_alert=False,
        spike_alert=False,
    )


def build_policy(
    start_persistence: int = 2,
    end_persistence: int = 2,
    start_threshold: float = 50,
    end_threshold: float = 60,
) -> IncidentPolicy:
    return IncidentPolicy(
        start_sqi_threshold=start_threshold,
        end_sqi_threshold=end_threshold,
        start_persistence_scans=start_persistence,
        end_persistence_scans=end_persistence,
        critical_sqi_threshold=25,
        component_score_floor=70,
        cause_priority=[
            IncidentCause.MISSING,
            IncidentCause.DRIFT,
            IncidentCause.SPIKES,
            IncidentCause.NOISE,
            IncidentCause.OSCILLATION,
            IncidentCause.UNKNOWN,
        ],
        emit_update_on_cause_change=True,
        emit_update_on_severity_change=True,
    )


def test_incident_opens_after_persistence():
    policy = build_policy(start_persistence=2)
    engine = IncidentEngine(policy)
    components = {
        "noise": 80,
        "drift": 80,
        "spikes": 80,
        "oscillation": 80,
        "missing": 80,
    }

    events = engine.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={
            "sig": make_processed("sig", 1.0, 40, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert events == []

    events = engine.update_scan(
        scan_index=1,
        timestamp=2.0,
        processed_signals={
            "sig": make_processed("sig", 2.0, 40, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.STARTED
    assert events[0].incident.incident_id == "sig:0"


def test_incident_resolves_after_recovery_persistence():
    policy = build_policy(start_persistence=1, end_persistence=2)
    engine = IncidentEngine(policy)
    components = {
        "noise": 80,
        "drift": 80,
        "spikes": 80,
        "oscillation": 80,
        "missing": 80,
    }

    engine.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={
            "sig": make_processed("sig", 1.0, 40, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )

    events = engine.update_scan(
        scan_index=1,
        timestamp=2.0,
        processed_signals={
            "sig": make_processed("sig", 2.0, 80, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert events == []

    events = engine.update_scan(
        scan_index=2,
        timestamp=3.0,
        processed_signals={
            "sig": make_processed("sig", 3.0, 80, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.RESOLVED


def test_cause_selection_uses_lowest_component_score():
    policy = build_policy(start_persistence=1)
    engine = IncidentEngine(policy)
    components = {
        "noise": 80,
        "drift": 60,
        "spikes": 65,
        "oscillation": 90,
        "missing": 90,
    }

    events = engine.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={
            "sig": make_processed("sig", 1.0, 40, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert len(events) == 1
    assert events[0].incident.cause == IncidentCause.DRIFT


def test_missing_only_incident_triggers():
    policy = build_policy(start_persistence=1)
    engine = IncidentEngine(policy)

    events = engine.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={},
        missing_ratio_by_signal={"sig": 1.0},
    )

    assert len(events) == 1
    assert events[0].incident.cause == IncidentCause.MISSING
    assert events[0].incident.last_sqi == 0.0


def test_realtime_service_process_scan_returns_incidents():
    policy = build_policy(start_persistence=1)
    engine = SignalQualityEngine()
    engine.register_signal("sig", SignalConfig(signal_id="sig"))
    incident_engine = IncidentEngine(policy)
    service = RealtimeQualityService(engine, incident_engine)

    processed, events = service.process_scan({"sig": None}, timestamp=1.0)

    assert processed == {}
    assert len(events) == 1
    assert service.scan_index == 1
