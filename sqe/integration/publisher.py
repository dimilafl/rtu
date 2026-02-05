"""Publishing adapters for processed SQE data and incidents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Union

from sqe.comms.budget import UtilizationStatus
from sqe.comms.health import CommsHealthClass, CommsHealthStatus, comms_status_sort_key
from sqe.core.engine import ProcessedSignal
from sqe.core.incidents import IncidentEvent, IncidentSeverity
from sqe.core.group_incidents import GroupIncidentEvent
from sqe.schema import SCHEMA_VERSION


class QualityPublisher(Protocol):
    """Publisher interface for SQE outputs."""

    def publish_processed(
        self,
        scan_timestamp: float,
        processed: Dict[str, ProcessedSignal],
        suppression_stats: Optional[Dict[str, int]] = None,
    ) -> None:
        """Publish processed scan results."""

    def publish_incidents(self, events: List[IncidentEvent]) -> None:
        """Publish incident events."""

    def publish_group_incidents(self, events: List[GroupIncidentEvent]) -> None:
        """Publish group incident events."""

    def publish_comms_health(self, statuses: List[CommsHealthStatus]) -> None:
        """Publish comms health statuses."""

    def publish_comms_budget(self, statuses: List[UtilizationStatus]) -> None:
        """Publish comms budget utilization statuses."""


class JsonLinesPublisher:
    """
    JSONL publisher for processed scans and incident events.

    scans.jsonl stores one JSON object per scan per signal.
    incidents.jsonl stores one JSON object per incident event.
    """

    def __init__(self, output_dir: Union[str, Path]) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.scans_path = self.output_dir / "scans.jsonl"
        self.incidents_path = self.output_dir / "incidents.jsonl"
        self.group_incidents_path = self.output_dir / "group_incidents.jsonl"
        self.comms_health_path = self.output_dir / "comms_health.jsonl"
        self.comms_budget_path = self.output_dir / "comms_budget.jsonl"

    def publish_processed(
        self,
        scan_timestamp: float,
        processed: Dict[str, ProcessedSignal],
        suppression_stats: Optional[Dict[str, int]] = None,
    ) -> None:
        rows = [
            self._build_scan_row(
                scan_timestamp, signal_id, signal, suppression_stats
            )
            for signal_id, signal in sorted(processed.items())
        ]
        self._append_rows(self.scans_path, rows)

    def publish_incidents(self, events: List[IncidentEvent]) -> None:
        rows = [self._build_incident_row(event) for event in events]
        self._append_rows(self.incidents_path, rows)

    def publish_group_incidents(self, events: List[GroupIncidentEvent]) -> None:
        rows = [self._build_group_incident_row(event) for event in events]
        self._append_rows(self.group_incidents_path, rows)

    def publish_comms_health(self, statuses: List[CommsHealthStatus]) -> None:
        rows = [
            status.to_dict()
            for status in sorted(statuses, key=comms_status_sort_key)
            if status.health_class != CommsHealthClass.OK
        ]
        self._append_rows(self.comms_health_path, rows, sort_keys=False)

    def publish_comms_budget(self, statuses: List[UtilizationStatus]) -> None:
        rows = [
            self._build_comms_budget_row(status)
            for status in sorted(statuses, key=self._comms_budget_sort_key)
            if status.level in {"DEGRADED", "CRITICAL"}
        ]
        self._append_rows(
            self.comms_budget_path,
            rows,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _append_rows(
        self,
        path: Path,
        rows: Iterable[Dict],
        *,
        sort_keys: bool = True,
        separators: Optional[tuple[str, str]] = None,
    ) -> None:
        if not rows:
            return
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(row, sort_keys=sort_keys, separators=separators)
                )
                handle.write("\n")
            handle.flush()

    def _build_scan_row(
        self,
        scan_timestamp: float,
        signal_id: str,
        signal: ProcessedSignal,
        suppression_stats: Optional[Dict[str, int]] = None,
    ) -> Dict:
        dominant_cause = self._dominant_cause(signal.sqi_components)
        severity = self._severity_from_signal(signal)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "scan_timestamp": scan_timestamp,
            "signal_id": signal_id,
            "timestamp": signal.timestamp,
            "sqi": signal.sqi,
            "quality_class": signal.quality_class,
            "dominant_cause": dominant_cause,
            "severity": severity.value,
            "components": signal.sqi_components,
            "alert_level": signal.alert_level,
            "drift_alert": signal.drift_alert,
            "spike_alert": signal.spike_alert,
        }
        if suppression_stats is not None:
            payload["suppression_stats"] = suppression_stats
        return payload

    @staticmethod
    def _dominant_cause(components: Dict[str, float]) -> str:
        if not components:
            return "unknown"
        return min(components.items(), key=lambda item: item[1])[0]

    @staticmethod
    def _severity_from_signal(signal: ProcessedSignal) -> IncidentSeverity:
        if signal.alert_level == "critical":
            return IncidentSeverity.CRITICAL
        if signal.alert_level == "warning":
            return IncidentSeverity.WARNING
        return IncidentSeverity.WARNING

    @staticmethod
    def _build_incident_row(event: IncidentEvent) -> Dict:
        incident = event.incident
        return {
            "schema_version": event.schema_version,
            "event_type": event.event_type.value,
            "message": event.message,
            "recommended_action": event.recommended_action,
            "incident": {
                "incident_id": incident.incident_id,
                "signal_id": incident.signal_id,
                "cause": incident.cause.value,
                "severity": incident.severity.value,
                "start_timestamp": incident.start_timestamp,
                "last_timestamp": incident.last_timestamp,
                "end_timestamp": incident.end_timestamp,
                "min_sqi": incident.min_sqi,
                "last_sqi": incident.last_sqi,
                "start_scan_index": incident.start_scan_index,
                "last_scan_index": incident.last_scan_index,
                "details": incident.details,
            },
        }

    @staticmethod
    def _build_group_incident_row(event: GroupIncidentEvent) -> Dict[str, Any]:
        incident = event.incident
        details = incident.details or {}
        return {
            "schema_version": event.schema_version,
            "group_id": incident.group_id,
            "group_incident_id": incident.group_incident_id,
            "timestamp": incident.last_timestamp,
            "event_type": event.event_type.value,
            "severity": incident.severity.value,
            "cause": incident.cause.value,
            "degraded_fraction": details.get("degraded_fraction", 0.0),
            "degraded_members": list(incident.degraded_members),
            "counts": {
                "members_total": details.get("members_total", 0),
                "members_degraded": details.get("members_degraded", 0),
            },
        }

    @staticmethod
    def _build_comms_budget_row(status: UtilizationStatus) -> Dict[str, Any]:
        return {
            "node_type": status.node_type,
            "node_id": status.node_id,
            "scan_index": status.scan_index,
            "scan_timestamp": status.scan_timestamp,
            "descendant_signal_count": status.descendant_signal_count,
            "expected_bytes": status.expected_bytes,
            "observed_bytes": status.observed_bytes,
            "observed_bps": status.observed_bps,
            "utilization": status.utilization,
            "headroom": status.headroom,
            "level": status.level,
            "reasons": list(status.reasons),
        }

    @staticmethod
    def _comms_budget_sort_key(
        status: UtilizationStatus,
    ) -> tuple[int, float, int, str]:
        node_type_priority = {"COMMS_DOMAIN": 0, "POLL_GROUP": 1, "RTU": 2}
        level_priority = {"CRITICAL": 0, "DEGRADED": 1, "OK": 2}
        return (
            level_priority.get(status.level, 99),
            -status.utilization,
            node_type_priority.get(status.node_type, 99),
            status.node_id,
        )


class OasysEnterprisePublisher:
    """
    Placeholder publisher for AVEVA OASyS Enterprise integration.

    Map SQI to derived points:
      - SQI score
      - dominant cause code
      - severity code

    Map incident events to event stream entries:
      - incident started
      - incident resolved
    """

    ALERT_LEVEL_CODES = {
        "none": 0,
        "warning": 1,
        "critical": 2,
    }
    INCIDENT_EVENT_CODES = {
        "started": "START",
        "updated": "UPDATE",
        "resolved": "RESOLVE",
    }
    SEVERITY_CODES = {
        IncidentSeverity.WARNING: 1,
        IncidentSeverity.CRITICAL: 2,
    }

    def __init__(
        self,
        send_point: Optional[Callable[[Dict[str, Any]], None]] = None,
        send_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        send_group_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        send_comms: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._send_point = send_point
        self._send_event = send_event
        self._send_group_event = send_group_event
        self._send_comms = send_comms
        self.published_points: List[Dict[str, Any]] = []
        self.published_events: List[Dict[str, Any]] = []
        self.published_group_events: List[Dict[str, Any]] = []
        self.published_comms: List[Dict[str, Any]] = []

    def publish_processed(
        self,
        scan_timestamp: float,
        processed: Dict[str, ProcessedSignal],
        suppression_stats: Optional[Dict[str, int]] = None,
    ) -> None:
        rows = [
            self._build_sqi_point(
                scan_timestamp, signal_id, signal, suppression_stats
            )
            for signal_id, signal in sorted(processed.items())
        ]
        for row in rows:
            self._emit_point(row)

    def publish_incidents(self, events: List[IncidentEvent]) -> None:
        rows = [self._build_incident_event(event) for event in events]
        for row in rows:
            self._emit_event(row)

    def publish_group_incidents(self, events: List[GroupIncidentEvent]) -> None:
        rows = [self._build_group_incident_event(event) for event in events]
        for row in rows:
            self._emit_group_event(row)

    def publish_comms_health(self, statuses: List[CommsHealthStatus]) -> None:
        rows = [
            status.to_dict()
            for status in sorted(statuses, key=comms_status_sort_key)
            if status.health_class != CommsHealthClass.OK
        ]
        for row in rows:
            self._emit_comms(row)

    def _emit_point(self, payload: Dict[str, Any]) -> None:
        if self._send_point:
            self._send_point(payload)
        else:
            self.published_points.append(payload)

    def _emit_event(self, payload: Dict[str, Any]) -> None:
        if self._send_event:
            self._send_event(payload)
        else:
            self.published_events.append(payload)

    def _emit_group_event(self, payload: Dict[str, Any]) -> None:
        if self._send_group_event:
            self._send_group_event(payload)
        else:
            self.published_group_events.append(payload)

    def _emit_comms(self, payload: Dict[str, Any]) -> None:
        if self._send_comms:
            self._send_comms(payload)
        else:
            self.published_comms.append(payload)

    def _build_sqi_point(
        self,
        scan_timestamp: float,
        signal_id: str,
        signal: ProcessedSignal,
        suppression_stats: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        dominant_cause = JsonLinesPublisher._dominant_cause(signal.sqi_components)
        severity_code = self.ALERT_LEVEL_CODES.get(signal.alert_level, 0)
        payload = {
            "type": "derived_point",
            "tag": f"{signal_id}:SQI",
            "scan_timestamp": scan_timestamp,
            "timestamp": signal.timestamp,
            "values": {
                "sqi": signal.sqi,
                "quality_class": signal.quality_class,
                "dominant_cause": dominant_cause,
                "severity_code": severity_code,
                "alert_level": signal.alert_level,
                "alert_flags": {
                    "drift": signal.drift_alert,
                    "spike": signal.spike_alert,
                },
            },
        }
        if suppression_stats is not None:
            payload["suppression_stats"] = suppression_stats
        return payload

    def _build_incident_event(self, event: IncidentEvent) -> Dict[str, Any]:
        incident = event.incident
        return {
            "type": "incident_event",
            "event_code": self.INCIDENT_EVENT_CODES.get(
                event.event_type.value, event.event_type.value.upper()
            ),
            "signal_id": incident.signal_id,
            "incident_id": incident.incident_id,
            "cause": incident.cause.value,
            "severity_code": self.SEVERITY_CODES.get(incident.severity, 0),
            "state_transition": event.event_type.value,
            "timestamp": incident.last_timestamp,
            "start_timestamp": incident.start_timestamp,
            "end_timestamp": incident.end_timestamp,
            "message": event.message,
            "recommended_action": event.recommended_action,
        }

    def _build_group_incident_event(
        self, event: GroupIncidentEvent
    ) -> Dict[str, Any]:
        incident = event.incident
        return {
            "type": "group_incident_event",
            "event_code": self.INCIDENT_EVENT_CODES.get(
                event.event_type.value, event.event_type.value.upper()
            ),
            "group_id": incident.group_id,
            "group_incident_id": incident.group_incident_id,
            "cause": incident.cause.value,
            "severity_code": self.SEVERITY_CODES.get(incident.severity, 0),
            "state_transition": event.event_type.value,
            "timestamp": incident.last_timestamp,
            "start_timestamp": incident.start_timestamp,
            "end_timestamp": incident.end_timestamp,
            "message": event.message,
            "recommended_action": event.recommended_action,
            "degraded_members": list(incident.degraded_members),
            "details": dict(incident.details or {}),
        }
