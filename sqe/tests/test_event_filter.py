"""Tests for event filtering behavior."""

import json

from sqe.core.event_filter import EventFilter, EventFilterPolicy
from sqe.core.group_incidents import (
    GroupIncident,
    GroupIncidentCause,
    GroupIncidentEvent,
)
from sqe.core.incidents import (
    IncidentCause,
    IncidentEvent,
    IncidentEventType,
    IncidentSeverity,
    QualityIncident,
)
from sqe.replay.runner import run_replay


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


def test_suppression_stats_written_to_scans_jsonl(tmp_path):
    replay_path = tmp_path / "replay.jsonl"
    replay_path.write_text(
        json.dumps(
            {
                "scan_index": 0,
                "timestamp": 1.0,
                "signals": {
                    "STATION_01_AI_001": {
                        "value": 10.0,
                        "quality": "uncertain",
                    },
                    "STATION_01_AI_002": {
                        "value": 11.0,
                        "quality": "uncertain",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        "\n".join(
            [
                "incidents:",
                "  start_sqi_threshold: 100",
                "  end_sqi_threshold: 100",
                "  start_persistence_scans: 1",
                "  end_persistence_scans: 1",
                "  critical_sqi_threshold: 25",
                "  component_score_floor: 70",
                "event_filter:",
                "  suppress_member_events: true",
                "  suppress_when_group_event_active: true",
                "  suppress_group_causes: ['comms']",
                "  suppress_event_types: ['started', 'updated']",
                "  allow_resolved_passthrough: true",
                "  include_suppression_stats: true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    groups_path = tmp_path / "groups.yaml"
    groups_path.write_text(
        "\n".join(
            [
                "grouping:",
                "  mode: prefix",
                "  prefix_delimiter: _",
                "  prefix_depth: 2",
                "  min_members_for_group_incident: 2",
                "  min_fraction_for_group_incident: 1.0",
                "  persistence_scans: 1",
                "  resolve_persistence_scans: 1",
                "group_incidents:",
                "  min_members_for_start: 2",
                "  min_fraction_for_start: 1.0",
                "  start_persistence_scans: 1",
                "  end_persistence_scans: 1",
                "  critical_fraction_threshold: 0.8",
                "  emit_updates: true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    run_replay(
        input_jsonl_path=str(replay_path),
        config_path=str(config_path),
        groups_config_path=str(groups_path),
        out_dir=str(out_dir),
    )

    scans = [
        json.loads(line)
        for line in (out_dir / "scans.jsonl").read_text().splitlines()
    ]
    assert len(scans) == 2
    expected_stats = {
        "total_member_events": 2,
        "suppressed_member_events": 2,
        "suppressed_member_events_started": 2,
        "suppressed_member_events_updated": 0,
        "suppressed_member_events_resolved": 0,
        "deferred_member_events": 2,
        "reemitted_member_events": 0,
    }
    for scan in scans:
        assert scan["suppression_stats"] == expected_stats


def test_event_filter_reemits_deferred_events_on_group_resolve():
    policy = EventFilterPolicy(
        suppress_member_events=True,
        suppress_when_group_event_active=True,
        suppress_group_causes=["comms"],
        suppress_event_types=["started"],
        allow_resolved_passthrough=False,
        include_suppression_stats=True,
    )
    event_filter = EventFilter(policy)

    incident_started = _build_incident_event(
        event_type=IncidentEventType.STARTED
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
        signal_events=[incident_started],
        group_events=[],
        active_group_incidents={"STATION_01": group_incident},
        signal_id_to_group_id={"STATION_01_AI_001": "STATION_01"},
    )

    assert filtered == []
    assert stats["deferred_member_events"] == 1
    assert stats["reemitted_member_events"] == 0

    resolved_event = GroupIncidentEvent(
        event_type=IncidentEventType.RESOLVED,
        incident=group_incident,
        message="resolved",
        recommended_action="resolved",
    )

    filtered, stats = event_filter.filter_events(
        scan_index=1,
        timestamp=2.0,
        signal_events=[],
        group_events=[resolved_event],
        active_group_incidents={},
        signal_id_to_group_id={"STATION_01_AI_001": "STATION_01"},
    )

    assert [event.event_type for event in filtered] == [
        IncidentEventType.STARTED
    ]
    assert stats["reemitted_member_events"] == 1
