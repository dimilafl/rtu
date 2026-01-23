"""Replay input and output schema conventions."""

from __future__ import annotations

from typing import Any, Dict


INPUT_SCAN_FIELDS = ("scan_index", "timestamp", "signals")
OUTPUT_INCIDENT_FIELDS = ("event_type", "message", "recommended_action", "incident")
OUTPUT_GROUP_INCIDENT_FIELDS = (
    "group_id",
    "group_incident_id",
    "timestamp",
    "event_type",
    "severity",
    "cause",
    "degraded_fraction",
    "degraded_members",
    "counts",
)


def validate_scan_record(record: Dict[str, Any]) -> None:
    """Validate replay scan records using the schema conventions."""
    for key in INPUT_SCAN_FIELDS:
        if key not in record:
            raise ValueError(f"Scan record missing required field '{key}'")
    if not isinstance(record["scan_index"], int):
        raise ValueError("scan_index must be an int")
    if not isinstance(record["timestamp"], (int, float)):
        raise ValueError("timestamp must be a number")
    signals = record["signals"]
    if not isinstance(signals, dict):
        raise ValueError("signals must be a mapping of signal_id to value or null")
