"""Publishing adapters for processed SQE data and incidents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Union

from sqe.core.engine import ProcessedSignal
from sqe.core.incidents import IncidentEvent, IncidentSeverity
from sqe.core.group_incidents import GroupIncidentEvent


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

    def _append_rows(self, path: Path, rows: Iterable[Dict]) -> None:
        if not rows:
            return
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True))
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

    def publish_processed(
        self,
        scan_timestamp: float,
        processed: Dict[str, ProcessedSignal],
        suppression_stats: Optional[Dict[str, int]] = None,
    ) -> None:
        raise NotImplementedError(
            "Map processed SQI outputs to OASyS derived points here."
        )

    def publish_incidents(self, events: List[IncidentEvent]) -> None:
        raise NotImplementedError(
            "Map incident events to OASyS Enterprise event stream here."
        )

    def publish_group_incidents(self, events: List[GroupIncidentEvent]) -> None:
        raise NotImplementedError(
            "Map group incident events to OASyS Enterprise event stream here."
        )
