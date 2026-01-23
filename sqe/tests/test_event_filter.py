"""Tests for event filtering behavior."""

from sqe.core.event_filter import EventFilter, EventFilterPolicy
from sqe.core.group_incidents import GroupIncident, GroupIncidentCause
from sqe.core.incidents import (
    IncidentCause,
    IncidentEvent,
    IncidentEventType,
    IncidentSeverity,
    QualityIncident,
)


def test_event_filter_suppresses_member_started_events():
    policy = EventFilterPolicy(
        suppress_member_events=True,
        suppress_when_group_event_active=True,
        suppress_group_causes=["comms"],
        suppress_event_types=["started", "resolved"],
        allow_resolved_passthrough=True,
        include_suppression_stats=True,
    )
    event_filter = EventFilter(policy)

    incident_started = _build_incident_event(
        event_type=IncidentEventType.STARTED
    )
    incident_resolved = _build_incident_event(
        event_type=IncidentEventType.RESOLVED
    )

    group_incident = GroupIncident(
        group_incident_id="STATION_01:0",
        group_id="STATION_01",
        start_timestamp=1.0,
        last_timestamp=1.0,
        end_timestamp=None,
        start_scan_index=0,
        last_scan_index=0,
        degraded_members=["STATION_01_AI_001"],
        severity=IncidentSeverity.CRITICAL,
        cause=GroupIncidentCause.COMMS,
        details={},
    )

    filtered, stats = event_filter.filter_events(
        scan_index=0,
        timestamp=1.0,
        signal_events=[incident_started, incident_resolved],
        group_events=[],
        active_group_incidents={"STATION_01": group_incident},
        signal_id_to_group_id={"STATION_01_AI_001": "STATION_01"},
    )

    assert [event.event_type for event in filtered] == [
        IncidentEventType.RESOLVED
    ]
    assert stats["suppressed_member_events"] == 1
    assert stats["suppressed_member_events_started"] == 1


def _build_incident_event(event_type: IncidentEventType) -> IncidentEvent:
    incident = QualityIncident(
        incident_id="STATION_01_AI_001:0",
        signal_id="STATION_01_AI_001",
        cause=IncidentCause.MISSING,
        severity=IncidentSeverity.WARNING,
        start_timestamp=1.0,
        last_timestamp=1.0,
        end_timestamp=None,
        min_sqi=0.0,
        last_sqi=0.0,
        start_scan_index=0,
        last_scan_index=0,
        details={},
    )
    return IncidentEvent(
        event_type=event_type,
        incident=incident,
        message="test",
        recommended_action="test",
    )
