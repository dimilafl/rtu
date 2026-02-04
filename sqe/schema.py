"""Schema versions and JSON schemas for SQE outputs."""

from __future__ import annotations

from typing import Any, Dict

SCHEMA_VERSION = "1.0.0"

PROCESSED_SCAN_SCHEMA: Dict[str, Any] = {
    "$id": "https://schemas.sqe.local/processed_scan.json",
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ProcessedScan",
    "type": "object",
    "required": [
        "schema_version",
        "scan_timestamp",
        "signal_id",
        "timestamp",
        "sqi",
        "quality_class",
        "dominant_cause",
        "severity",
        "components",
        "alert_level",
        "drift_alert",
        "spike_alert",
    ],
    "properties": {
        "schema_version": {"type": "string"},
        "scan_timestamp": {"type": "number"},
        "signal_id": {"type": "string"},
        "timestamp": {"type": "number"},
        "sqi": {"type": "number"},
        "quality_class": {"type": "string"},
        "dominant_cause": {"type": "string"},
        "severity": {"type": "string"},
        "components": {"type": "object"},
        "alert_level": {"type": "string"},
        "drift_alert": {"type": "boolean"},
        "spike_alert": {"type": "boolean"},
        "suppression_stats": {"type": "object"},
    },
}

INCIDENT_EVENT_SCHEMA: Dict[str, Any] = {
    "$id": "https://schemas.sqe.local/incident_event.json",
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "IncidentEvent",
    "type": "object",
    "required": ["schema_version", "event_type", "message", "recommended_action"],
    "properties": {
        "schema_version": {"type": "string"},
        "event_type": {"type": "string"},
        "message": {"type": "string"},
        "recommended_action": {"type": "string"},
        "incident": {"type": "object"},
    },
}

GROUP_INCIDENT_EVENT_SCHEMA: Dict[str, Any] = {
    "$id": "https://schemas.sqe.local/group_incident_event.json",
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "GroupIncidentEvent",
    "type": "object",
    "required": ["schema_version", "event_type", "message", "recommended_action"],
    "properties": {
        "schema_version": {"type": "string"},
        "event_type": {"type": "string"},
        "message": {"type": "string"},
        "recommended_action": {"type": "string"},
        "incident": {"type": "object"},
    },
}
