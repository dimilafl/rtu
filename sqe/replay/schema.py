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
    for signal_id, value in signals.items():
        if value is None or isinstance(value, (int, float)):
            continue
        if isinstance(value, dict):
            allowed_keys = {"value", "quality", "source_timestamp"}
            unknown_keys = set(value.keys()) - allowed_keys
            if unknown_keys:
                raise ValueError(
                    f"Invalid keys for {signal_id}: {sorted(unknown_keys)}"
                )
            sample_value = value.get("value")
            if sample_value is not None and not isinstance(
                sample_value, (int, float)
            ):
                raise ValueError(
                    f"Invalid value for {signal_id}: value must be number or null"
                )
            quality = value.get("quality")
            if quality is not None:
                if not isinstance(quality, str):
                    raise ValueError(
                        f"Invalid quality for {signal_id}: must be string"
                    )
                if quality.lower() not in {"good", "uncertain", "bad"}:
                    raise ValueError(
                        f"Invalid quality for {signal_id}: {quality}"
                    )
            source_timestamp = value.get("source_timestamp")
            if source_timestamp is not None and not isinstance(
                source_timestamp, (int, float)
            ):
                raise ValueError(
                    f"Invalid source_timestamp for {signal_id}: must be number"
                )
            continue
        raise ValueError(
            f"Invalid value for {signal_id}: must be number, null, or object"
        )
