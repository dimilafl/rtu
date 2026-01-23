"""Group-level incident engine for station incidents."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqe.core.incidents import IncidentCause, IncidentEventType, IncidentSeverity


class GroupIncidentCause(str, Enum):
    """Dominant cause for group incidents."""

    COMMS = "comms"
    DATA_QUALITY = "data_quality"
    MIXED = "mixed"


@dataclass(frozen=True)
class GroupIncidentPolicy:
    min_members_for_start: int
    min_fraction_for_start: float
    start_persistence_scans: int
    end_persistence_scans: int
    critical_fraction_threshold: float
    emit_updates: bool


@dataclass
class GroupIncident:
    group_incident_id: str
    group_id: str
    start_timestamp: float
    last_timestamp: float
    end_timestamp: Optional[float]
    start_scan_index: int
    last_scan_index: int
    degraded_members: List[str]
    severity: IncidentSeverity
    cause: GroupIncidentCause
    details: Dict[str, Any]


@dataclass(frozen=True)
class GroupIncidentEvent:
    event_type: IncidentEventType
    incident: GroupIncident
    message: str
    recommended_action: str


@dataclass
class _GroupIncidentState:
    active_incident: Optional[GroupIncident] = None
    degraded_streak: int = 0
    recovered_streak: int = 0
    last_members: Tuple[str, ...] = field(default_factory=tuple)


CAUSE_ACTIONS = {
    GroupIncidentCause.COMMS: (
        "Investigate comms path or poll group affecting this station."
    ),
    GroupIncidentCause.DATA_QUALITY: (
        "Investigate shared instrumentation or configuration affecting this station."
    ),
    GroupIncidentCause.MIXED: (
        "Review station trend and top degraded tags for common drivers."
    ),
}


class GroupIncidentEngine:
    """Scan-driven incident engine for station groups."""

    def __init__(self, policy: GroupIncidentPolicy) -> None:
        self.policy = policy
        self._state_by_group: Dict[str, _GroupIncidentState] = {}

    def update_scan(
        self,
        scan_index: int,
        timestamp: float,
        group_id_to_member_status: Dict[str, Dict[str, Any]],
    ) -> List[GroupIncidentEvent]:
        events: List[GroupIncidentEvent] = []

        for group_id in sorted(group_id_to_member_status):
            member_status = group_id_to_member_status.get(group_id, {})
            members_total = len(member_status)
            degraded_members = sorted(
                [
                    member_id
                    for member_id, status in member_status.items()
                    if status.get("degraded")
                ]
            )
            members_degraded = len(degraded_members)
            degraded_fraction = (
                members_degraded / members_total if members_total else 0.0
            )
            degraded_group = (
                members_degraded >= self.policy.min_members_for_start
                and degraded_fraction >= self.policy.min_fraction_for_start
            )

            cause = self._classify_cause(member_status, degraded_members)
            severity = (
                IncidentSeverity.CRITICAL
                if degraded_fraction >= self.policy.critical_fraction_threshold
                else IncidentSeverity.WARNING
            )
            details = self._build_details(
                member_status=member_status,
                members_total=members_total,
                members_degraded=members_degraded,
                degraded_fraction=degraded_fraction,
            )

            state = self._state_by_group.setdefault(group_id, _GroupIncidentState())

            if state.active_incident is None:
                if degraded_group:
                    state.degraded_streak += 1
                else:
                    state.degraded_streak = 0
                state.recovered_streak = 0

                if (
                    degraded_group
                    and state.degraded_streak >= self.policy.start_persistence_scans
                ):
                    start_scan_index = (
                        scan_index - self.policy.start_persistence_scans + 1
                    )
                    incident = GroupIncident(
                        group_incident_id=f"{group_id}:{start_scan_index}",
                        group_id=group_id,
                        start_timestamp=timestamp,
                        last_timestamp=timestamp,
                        end_timestamp=None,
                        start_scan_index=start_scan_index,
                        last_scan_index=scan_index,
                        degraded_members=degraded_members,
                        severity=severity,
                        cause=cause,
                        details=details,
                    )
                    state.active_incident = incident
                    state.degraded_streak = 0
                    state.last_members = tuple(degraded_members)
                    events.append(
                        GroupIncidentEvent(
                            event_type=IncidentEventType.STARTED,
                            incident=incident,
                            message=self._build_message(
                                incident, IncidentEventType.STARTED
                            ),
                            recommended_action=CAUSE_ACTIONS[cause],
                        )
                    )
                continue

            incident = state.active_incident
            if degraded_group:
                state.recovered_streak = 0
                incident.last_timestamp = timestamp
                incident.last_scan_index = scan_index
                incident.degraded_members = degraded_members
                incident.details = details

                cause_changed = incident.cause != cause
                severity_changed = incident.severity != severity
                members_changed = state.last_members != tuple(degraded_members)
                if cause_changed:
                    incident.cause = cause
                if severity_changed:
                    incident.severity = severity
                if members_changed:
                    state.last_members = tuple(degraded_members)

                if self.policy.emit_updates and (
                    cause_changed or severity_changed or members_changed
                ):
                    events.append(
                        GroupIncidentEvent(
                            event_type=IncidentEventType.UPDATED,
                            incident=incident,
                            message=self._build_update_message(
                                incident,
                                cause_changed=cause_changed,
                                severity_changed=severity_changed,
                                members_changed=members_changed,
                            ),
                            recommended_action=CAUSE_ACTIONS[incident.cause],
                        )
                    )
                continue

            state.recovered_streak += 1
            if state.recovered_streak >= self.policy.end_persistence_scans:
                incident.last_timestamp = timestamp
                incident.last_scan_index = scan_index
                incident.end_timestamp = timestamp
                incident.details = details
                events.append(
                    GroupIncidentEvent(
                        event_type=IncidentEventType.RESOLVED,
                        incident=incident,
                        message=self._build_message(
                            incident, IncidentEventType.RESOLVED
                        ),
                        recommended_action=CAUSE_ACTIONS[incident.cause],
                    )
                )
                state.active_incident = None
                state.recovered_streak = 0
                state.last_members = tuple()

        return events

    @staticmethod
    def _classify_cause(
        member_status: Dict[str, Any],
        degraded_members: List[str],
    ) -> GroupIncidentCause:
        missing = 0
        non_missing = 0
        for member_id in degraded_members:
            status = member_status.get(member_id, {})
            if status.get("cause") == IncidentCause.MISSING:
                missing += 1
            else:
                non_missing += 1
        if missing > non_missing:
            return GroupIncidentCause.COMMS
        if non_missing > missing:
            return GroupIncidentCause.DATA_QUALITY
        return GroupIncidentCause.MIXED

    @staticmethod
    def _build_details(
        member_status: Dict[str, Any],
        members_total: int,
        members_degraded: int,
        degraded_fraction: float,
    ) -> Dict[str, Any]:
        cause_counts: Dict[str, int] = {}
        for status in member_status.values():
            if not status.get("degraded"):
                continue
            cause = status.get("cause")
            key = cause.value if isinstance(cause, IncidentCause) else str(cause)
            cause_counts[key] = cause_counts.get(key, 0) + 1
        top_causes = sorted(
            cause_counts.items(), key=lambda item: (-item[1], item[0])
        )
        return {
            "members_total": members_total,
            "members_degraded": members_degraded,
            "degraded_fraction": degraded_fraction,
            "cause_counts": dict(sorted(cause_counts.items())),
            "top_causes": [
                {"cause": cause, "count": count} for cause, count in top_causes
            ],
        }

    @staticmethod
    def _build_message(
        incident: GroupIncident,
        event_type: IncidentEventType,
    ) -> str:
        if event_type == IncidentEventType.STARTED:
            return f"Group incident started for {incident.group_id}."
        if event_type == IncidentEventType.RESOLVED:
            return f"Group incident resolved for {incident.group_id}."
        return f"Group incident updated for {incident.group_id}."

    @staticmethod
    def _build_update_message(
        incident: GroupIncident,
        cause_changed: bool,
        severity_changed: bool,
        members_changed: bool,
    ) -> str:
        parts: List[str] = []
        if cause_changed:
            parts.append(f"cause {incident.cause.value}")
        if severity_changed:
            parts.append(f"severity {incident.severity.value}")
        if members_changed:
            parts.append("members")
        detail = ", ".join(parts) if parts else "status"
        return f"Group incident updated for {incident.group_id} with {detail}."
