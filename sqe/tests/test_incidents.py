"""Tests for incident engine."""

from typing import Dict

from sqe.core.engine import ProcessedSignal, SignalConfig, SignalQualityEngine
from sqe.core.incidents import (
    IncidentCause,
    IncidentEngine,
    IncidentEventType,
    IncidentPolicy,
    IncidentSeverity,
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
        stale=False,
        stale_reason=None,
        step_change=False,
        step_offset=None,
        plausibility_violation=False,
        plausibility_reasons=[],
        plausibility_rate=None,
        alert_level="warning" if sqi <= 50 else "none",
        drift_alert=False,
        spike_alert=False,
    )


def build_policy(
    start_persistence: int = 2,
    end_persistence: int = 2,
    start_threshold: float = 50,
    end_threshold: float = 60,
    state_retention_scans: int = 100,
) -> IncidentPolicy:
    return IncidentPolicy(
        start_sqi_threshold=start_threshold,
        end_sqi_threshold=end_threshold,
        start_persistence_scans=start_persistence,
        end_persistence_scans=end_persistence,
        critical_sqi_threshold=25,
        component_score_floor=70,
        state_retention_scans=state_retention_scans,
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
        emit_update_on_cause_change=True,
        emit_update_on_severity_change=True,
    )


def test_incident_opens_after_persistence():
    policy = build_policy(start_persistence=2)
    engine = IncidentEngine(policy, run_id="run-1")
    components = {
        "noise": 80,
        "drift": 80,
        "spikes": 80,
        "oscillation": 80,
        "missing": 80,
        "stale": 100,
        "step": 100,
        "plausibility": 100,
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
    assert events[0].incident.incident_id == "run-1:sig:0"


def test_incident_resolves_after_recovery_persistence():
    policy = build_policy(start_persistence=1, end_persistence=2)
    engine = IncidentEngine(policy, run_id="run-2")
    components = {
        "noise": 80,
        "drift": 80,
        "spikes": 80,
        "oscillation": 80,
        "missing": 80,
        "stale": 100,
        "step": 100,
        "plausibility": 100,
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


def test_incident_threshold_hysteresis_and_persistence_boundaries():
    policy = build_policy(start_persistence=2, end_persistence=2)
    engine = IncidentEngine(policy, run_id="run-3")
    components = {
        "noise": 80,
        "drift": 80,
        "spikes": 80,
        "oscillation": 80,
        "missing": 80,
        "stale": 100,
        "step": 100,
        "plausibility": 100,
    }

    events = engine.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={
            "sig": make_processed("sig", 1.0, 55, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert events == []

    events = engine.update_scan(
        scan_index=1,
        timestamp=2.0,
        processed_signals={
            "sig": make_processed("sig", 2.0, 50, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert events == []

    events = engine.update_scan(
        scan_index=2,
        timestamp=3.0,
        processed_signals={
            "sig": make_processed("sig", 3.0, 49, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.STARTED
    assert events[0].incident.incident_id == "run-3:sig:1"

    events = engine.update_scan(
        scan_index=3,
        timestamp=4.0,
        processed_signals={
            "sig": make_processed("sig", 4.0, 59, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert events == []

    events = engine.update_scan(
        scan_index=4,
        timestamp=5.0,
        processed_signals={
            "sig": make_processed("sig", 5.0, 60, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert events == []

    events = engine.update_scan(
        scan_index=5,
        timestamp=6.0,
        processed_signals={
            "sig": make_processed("sig", 6.0, 61, components)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.RESOLVED
    assert events[0].incident.incident_id == "run-3:sig:1"


def test_incident_updates_on_cause_and_severity_change():
    policy = build_policy(start_persistence=1)
    engine = IncidentEngine(policy, run_id="run-4")
    components_drift = {
        "noise": 80,
        "drift": 60,
        "spikes": 90,
        "oscillation": 90,
        "missing": 90,
        "stale": 100,
        "step": 100,
        "plausibility": 100,
    }
    components_noise = {
        "noise": 60,
        "drift": 90,
        "spikes": 90,
        "oscillation": 90,
        "missing": 90,
        "stale": 100,
        "step": 100,
        "plausibility": 100,
    }

    events = engine.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={
            "sig": make_processed("sig", 1.0, 40, components_drift)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.STARTED
    assert events[0].incident.incident_id == "run-4:sig:0"
    assert events[0].incident.cause == IncidentCause.DRIFT

    events = engine.update_scan(
        scan_index=1,
        timestamp=2.0,
        processed_signals={
            "sig": make_processed("sig", 2.0, 40, components_noise)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.UPDATED
    assert events[0].incident.incident_id == "run-4:sig:0"
    assert events[0].incident.cause == IncidentCause.NOISE

    events = engine.update_scan(
        scan_index=2,
        timestamp=3.0,
        processed_signals={
            "sig": make_processed("sig", 3.0, 20, components_noise)
        },
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.UPDATED
    assert events[0].incident.incident_id == "run-4:sig:0"
    assert events[0].incident.severity == IncidentSeverity.CRITICAL


def test_cause_selection_uses_lowest_component_score():
    policy = build_policy(start_persistence=1)
    engine = IncidentEngine(policy, run_id="run-5")
    components = {
        "noise": 80,
        "drift": 60,
        "spikes": 65,
        "oscillation": 90,
        "missing": 90,
        "stale": 100,
        "step": 100,
        "plausibility": 100,
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
    engine = IncidentEngine(policy, run_id="run-6")

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
    incident_engine = IncidentEngine(policy, run_id="run-7")
    service = RealtimeQualityService(engine, incident_engine)

    processed_scan, events, group_events = service.process_scan(
        {"sig": None}, timestamp=1.0
    )

    assert processed_scan.processed_signals == {}
    assert len(events) == 1
    assert group_events == []
    assert service.scan_index == 1


def test_incident_run_id_uniqueness():
    policy = build_policy(start_persistence=1)
    engine_a = IncidentEngine(policy, run_id="run-a")
    engine_b = IncidentEngine(policy, run_id="run-b")
    components = {
        "noise": 60,
        "drift": 90,
        "spikes": 90,
        "oscillation": 90,
        "missing": 90,
        "stale": 100,
        "step": 100,
        "plausibility": 100,
    }

    events_a = engine_a.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={"sig": make_processed("sig", 1.0, 40, components)},
        missing_ratio_by_signal={"sig": 0.0},
    )
    events_b = engine_b.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={"sig": make_processed("sig", 1.0, 40, components)},
        missing_ratio_by_signal={"sig": 0.0},
    )

    assert events_a[0].incident.incident_id != events_b[0].incident.incident_id


def test_incident_state_pruning():
    policy = build_policy(start_persistence=1, state_retention_scans=1)
    engine = IncidentEngine(policy, run_id="run-prune")
    components = {
        "noise": 80,
        "drift": 80,
        "spikes": 80,
        "oscillation": 80,
        "missing": 80,
        "stale": 100,
        "step": 100,
        "plausibility": 100,
    }

    engine.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={"sig": make_processed("sig", 1.0, 90, components)},
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert "sig" in engine._state_by_signal

    engine.update_scan(
        scan_index=1,
        timestamp=2.0,
        processed_signals={},
        missing_ratio_by_signal={},
    )
    assert "sig" in engine._state_by_signal

    engine.update_scan(
        scan_index=2,
        timestamp=3.0,
        processed_signals={},
        missing_ratio_by_signal={},
    )
    assert "sig" not in engine._state_by_signal


def test_active_incident_not_pruned():
    policy = build_policy(start_persistence=1, state_retention_scans=1)
    engine = IncidentEngine(policy, run_id="run-active")
    components = {
        "noise": 80,
        "drift": 80,
        "spikes": 80,
        "oscillation": 80,
        "missing": 80,
        "stale": 100,
        "step": 100,
        "plausibility": 100,
    }

    engine.update_scan(
        scan_index=0,
        timestamp=1.0,
        processed_signals={"sig": make_processed("sig", 1.0, 40, components)},
        missing_ratio_by_signal={"sig": 0.0},
    )
    assert engine._state_by_signal["sig"].active_incident is not None

    engine.update_scan(
        scan_index=2,
        timestamp=3.0,
        processed_signals={},
        missing_ratio_by_signal={},
    )
    assert "sig" in engine._state_by_signal
