"""Event filtering and suppression for incident streams."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from sqe.core.group_incidents import GroupIncident, GroupIncidentEvent
from sqe.core.incidents import IncidentEvent, IncidentEventType


@dataclass(frozen=True)
class EventFilterPolicy:
    suppress_member_events: bool
    suppress_when_group_event_active: bool
    suppress_group_causes: List[str] = field(default_factory=lambda: ["comms"])
    suppress_event_types: List[str] = field(
        default_factory=lambda: ["started", "updated"]
    )
    allow_resolved_passthrough: bool = True
    include_suppression_stats: bool = True


class EventFilter:
    """Filter incident events based on active group incidents."""

    def __init__(self, policy: EventFilterPolicy) -> None:
        self.policy = policy
        self._deferred_by_group: Dict[str, List[IncidentEvent]] = {}

    def filter_events(
        self,
        scan_index: int,
        timestamp: float,
        signal_events: List[IncidentEvent],
        group_events: List[GroupIncidentEvent],
        active_group_incidents: Dict[str, GroupIncident],
        signal_id_to_group_id: Dict[str, str],
    ) -> Tuple[List[IncidentEvent], Dict[str, int]]:
        del scan_index, timestamp

        resolved_group_ids = {
            event.incident.group_id
            for event in group_events
            if event.event_type == IncidentEventType.RESOLVED
        }

        stats: Dict[str, int] = {}
        if self.policy.include_suppression_stats:
            stats = {
                "total_member_events": len(signal_events),
                "suppressed_member_events": 0,
                "suppressed_member_events_started": 0,
                "suppressed_member_events_updated": 0,
                "suppressed_member_events_resolved": 0,
                "deferred_member_events": 0,
                "reemitted_member_events": 0,
            }

        if not self.policy.suppress_member_events:
            return self._append_deferred_events(
                signal_events, resolved_group_ids, stats
            )
        if not self.policy.suppress_when_group_event_active:
            return self._append_deferred_events(
                signal_events, resolved_group_ids, stats
            )

        suppress_causes = {
            str(cause).lower() for cause in self.policy.suppress_group_causes
        }
        active_group_ids = {
            group_id
            for group_id, incident in active_group_incidents.items()
            if incident and str(incident.cause.value).lower() in suppress_causes
        }
        if not active_group_ids:
            return self._append_deferred_events(
                signal_events, resolved_group_ids, stats
            )

        suppress_event_types = {
            str(event_type).lower()
            for event_type in self.policy.suppress_event_types
        }
        filtered: List[IncidentEvent] = []
        for event in signal_events:
            signal_id = event.incident.signal_id
            group_id = signal_id_to_group_id.get(signal_id)
            if group_id is None or group_id not in active_group_ids:
                filtered.append(event)
                continue

            event_type = event.event_type.value
            if (
                event.event_type == IncidentEventType.RESOLVED
                and self.policy.allow_resolved_passthrough
            ):
                filtered.append(event)
                continue

            if event_type in suppress_event_types:
                if stats:
                    stats["suppressed_member_events"] += 1
                    if event.event_type == IncidentEventType.STARTED:
                        stats["suppressed_member_events_started"] += 1
                    elif event.event_type == IncidentEventType.UPDATED:
                        stats["suppressed_member_events_updated"] += 1
                    elif event.event_type == IncidentEventType.RESOLVED:
                        stats["suppressed_member_events_resolved"] += 1
                    stats["deferred_member_events"] += 1
                if group_id:
                    self._deferred_by_group.setdefault(group_id, []).append(event)
                continue

            filtered.append(event)

        return self._append_deferred_events(filtered, resolved_group_ids, stats)

    def _append_deferred_events(
        self,
        events: List[IncidentEvent],
        resolved_group_ids: set[str],
        stats: Dict[str, int],
    ) -> Tuple[List[IncidentEvent], Dict[str, int]]:
        if not resolved_group_ids:
            return list(events), stats

        deferred: List[IncidentEvent] = []
        for group_id in sorted(resolved_group_ids):
            deferred.extend(self._deferred_by_group.pop(group_id, []))

        if deferred and stats:
            stats["reemitted_member_events"] += len(deferred)

        return list(events) + deferred, stats
