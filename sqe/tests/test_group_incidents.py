"""Tests for group incident engine."""

from sqe.core.group_incidents import (
    GroupIncidentCause,
    GroupIncidentEngine,
    GroupIncidentPolicy,
)
from sqe.core.incidents import IncidentCause, IncidentEventType, IncidentSeverity


def _status(degraded, cause, severity):
    return {"degraded": degraded, "cause": cause, "severity": severity}


def test_group_incident_starts_after_persistence():
    policy = GroupIncidentPolicy(
        min_members_for_start=2,
        min_fraction_for_start=0.5,
        start_persistence_scans=2,
        end_persistence_scans=2,
        critical_fraction_threshold=0.8,
        emit_updates=True,
    )
    engine = GroupIncidentEngine(policy, run_id="run-1")

    scan0 = {
        "station_1": {
            "s1": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s2": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
            "s3": _status(False, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }
    scan1 = {
        "station_1": {
            "s1": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s2": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
            "s3": _status(False, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }

    assert engine.update_scan(0, 1.0, scan0) == []
    events = engine.update_scan(1, 2.0, scan1)

    assert len(events) == 1
    event = events[0]
    assert event.event_type == IncidentEventType.STARTED
    assert event.incident.group_incident_id == "run-1:group:station_1:0"
    assert event.incident.degraded_members == ["s1", "s2"]


def test_group_incident_resolves_after_persistence():
    policy = GroupIncidentPolicy(
        min_members_for_start=1,
        min_fraction_for_start=0.5,
        start_persistence_scans=1,
        end_persistence_scans=2,
        critical_fraction_threshold=0.8,
        emit_updates=True,
    )
    engine = GroupIncidentEngine(policy, run_id="run-2")

    scan0 = {
        "station_1": {
            "s1": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
        }
    }
    scan1 = {
        "station_1": {
            "s1": _status(False, IncidentCause.MISSING, IncidentSeverity.WARNING),
        }
    }
    scan2 = {
        "station_1": {
            "s1": _status(False, IncidentCause.MISSING, IncidentSeverity.WARNING),
        }
    }

    start_event = engine.update_scan(0, 1.0, scan0)[0]
    assert start_event.event_type == IncidentEventType.STARTED

    assert engine.update_scan(1, 2.0, scan1) == []
    events = engine.update_scan(2, 3.0, scan2)
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.RESOLVED
    assert events[0].incident.end_timestamp == 3.0


def test_group_incident_requires_member_and_fraction_gates():
    policy = GroupIncidentPolicy(
        min_members_for_start=2,
        min_fraction_for_start=0.75,
        start_persistence_scans=2,
        end_persistence_scans=1,
        critical_fraction_threshold=0.8,
        emit_updates=True,
    )
    engine = GroupIncidentEngine(policy, run_id="run-3")

    scan0 = {
        "station_1": {
            "s1": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
        }
    }
    scan1 = {
        "station_1": {
            "s1": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s2": _status(False, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }
    scan2 = {
        "station_1": {
            "s1": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s2": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
            "s3": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
            "s4": _status(False, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }

    assert engine.update_scan(0, 1.0, scan0) == []
    assert engine.update_scan(1, 2.0, scan1) == []
    assert engine.update_scan(2, 3.0, scan2) == []

    events = engine.update_scan(3, 4.0, scan2)
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.STARTED
    assert events[0].incident.group_incident_id == "run-3:group:station_1:2"


def test_group_incident_cause_switches_when_missing_dominates():
    policy = GroupIncidentPolicy(
        min_members_for_start=2,
        min_fraction_for_start=0.5,
        start_persistence_scans=1,
        end_persistence_scans=1,
        critical_fraction_threshold=0.8,
        emit_updates=True,
    )
    engine = GroupIncidentEngine(policy, run_id="run-4")

    scan0 = {
        "station_1": {
            "s1": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
            "s2": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
            "s3": _status(False, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }
    scan1 = {
        "station_1": {
            "s1": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s2": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s3": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }

    start_event = engine.update_scan(0, 1.0, scan0)[0]
    assert start_event.incident.cause == GroupIncidentCause.DATA_QUALITY

    events = engine.update_scan(1, 2.0, scan1)
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.UPDATED
    assert events[0].incident.cause == GroupIncidentCause.COMMS


def test_group_incident_member_churn_and_partial_recovery():
    policy = GroupIncidentPolicy(
        min_members_for_start=2,
        min_fraction_for_start=0.5,
        start_persistence_scans=1,
        end_persistence_scans=2,
        critical_fraction_threshold=0.8,
        emit_updates=True,
    )
    engine = GroupIncidentEngine(policy, run_id="run-5")

    scan0 = {
        "station_1": {
            "s1": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s2": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s3": _status(False, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }
    scan1 = {
        "station_1": {
            "s1": _status(False, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s2": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s3": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }
    partial_recovery = {
        "station_1": {
            "s1": _status(False, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s2": _status(False, IncidentCause.MISSING, IncidentSeverity.WARNING),
            "s3": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }

    start_event = engine.update_scan(0, 1.0, scan0)[0]
    assert start_event.event_type == IncidentEventType.STARTED
    assert start_event.incident.group_incident_id == "run-5:group:station_1:0"

    events = engine.update_scan(1, 2.0, scan1)
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.UPDATED
    assert events[0].incident.group_incident_id == "run-5:group:station_1:0"
    assert events[0].incident.degraded_members == ["s2", "s3"]

    assert engine.update_scan(2, 3.0, partial_recovery) == []

    events = engine.update_scan(3, 4.0, partial_recovery)
    assert len(events) == 1
    assert events[0].event_type == IncidentEventType.RESOLVED
    assert events[0].incident.group_incident_id == "run-5:group:station_1:0"


def test_group_incident_member_order_and_ids_are_deterministic():
    policy = GroupIncidentPolicy(
        min_members_for_start=2,
        min_fraction_for_start=0.5,
        start_persistence_scans=1,
        end_persistence_scans=1,
        critical_fraction_threshold=0.8,
        emit_updates=True,
    )
    engine = GroupIncidentEngine(policy, run_id="run-6")
    scan = {
        "station_1": {
            "s2": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
            "s1": _status(True, IncidentCause.NOISE, IncidentSeverity.WARNING),
            "s3": _status(False, IncidentCause.NOISE, IncidentSeverity.WARNING),
        }
    }

    events = engine.update_scan(5, 10.0, scan)
    assert len(events) == 1
    incident = events[0].incident
    assert incident.group_incident_id == "run-6:group:station_1:5"
    assert incident.degraded_members == ["s1", "s2"]


def test_group_incident_state_pruning():
    policy = GroupIncidentPolicy(
        min_members_for_start=1,
        min_fraction_for_start=0.5,
        start_persistence_scans=1,
        end_persistence_scans=1,
        critical_fraction_threshold=0.8,
        emit_updates=True,
        state_retention_scans=1,
    )
    engine = GroupIncidentEngine(policy, run_id="run-prune")
    scan = {
        "station_1": {
            "s1": _status(True, IncidentCause.MISSING, IncidentSeverity.WARNING),
        }
    }

    engine.update_scan(0, 1.0, scan)
    assert "station_1" in engine._state_by_group

    engine.update_scan(
        1,
        2.0,
        {
            "station_1": {
                "s1": _status(False, IncidentCause.MISSING, IncidentSeverity.WARNING),
            }
        },
    )
    assert engine._state_by_group["station_1"].active_incident is None

    engine.update_scan(3, 4.0, {})
    assert "station_1" not in engine._state_by_group
