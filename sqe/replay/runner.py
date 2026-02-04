"""Deterministic replay runner for SQE scans."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqe.config.loader import (
    build_signal_config,
    configure_logging,
    get_engine_auto_register,
    get_engine_max_signals_policy,
    get_engine_max_signals,
    get_engine_scan_interval,
    get_engine_treat_missing_signals_as_none,
    get_engine_unknown_signal_policy,
    get_event_filter_policy,
    get_incident_policy,
    get_group_incident_policy,
    get_grouping_config,
    load_config,
    load_groups_config,
)
from sqe.core.engine import ProcessedSignal, SignalQualityEngine
from sqe.core.event_filter import EventFilter
from sqe.core.group_incidents import GroupIncidentEngine, GroupIncidentEvent
from sqe.core.grouping import GroupResolver
from sqe.core.incidents import IncidentEngine, IncidentEvent
from sqe.core.sample import Sample, parse_sample
from sqe.integration.publisher import JsonLinesPublisher
from sqe.replay.schema import validate_scan_record
from sqe.ops.service import RealtimeQualityService


def run_replay(
    input_jsonl_path: str,
    config_path: str,
    groups_config_path: Optional[str],
    out_dir: str,
    write_processed: bool = True,
    max_scans: Optional[int] = None,
) -> None:
    """Run deterministic replay of scan inputs."""
    config = load_config(config_path)
    configure_logging(config)
    scan_interval = get_engine_scan_interval(config)
    logging_settings = {
        "log_scan_timing": False,
        "log_quality_changes": False,
        "log_anomalies": False,
    }
    engine = SignalQualityEngine(
        scan_interval=scan_interval,
        auto_register=get_engine_auto_register(config),
        max_signals=get_engine_max_signals(config),
        treat_missing_signals_as_none=get_engine_treat_missing_signals_as_none(
            config
        ),
        unknown_signal_policy=get_engine_unknown_signal_policy(config),
        max_signals_policy=get_engine_max_signals_policy(config),
        log_scan_timing=logging_settings["log_scan_timing"],
        log_quality_changes=logging_settings["log_quality_changes"],
        log_anomalies=logging_settings["log_anomalies"],
    )

    if not engine.auto_register:
        signal_ids = _scan_signal_ids(input_jsonl_path)
        for signal_id in sorted(signal_ids):
            engine.register_signal(
                signal_id,
                build_signal_config(config, signal_id, scan_interval),
            )

    incident_engine = IncidentEngine(get_incident_policy(config))
    event_filter_policy = get_event_filter_policy(config)
    event_filter = EventFilter(event_filter_policy)

    group_resolver = None
    group_incident_engine = None
    if groups_config_path:
        group_config = load_groups_config(groups_config_path)
        grouping_config = get_grouping_config(group_config)
        group_policy = get_group_incident_policy(group_config, grouping_config)
        group_resolver = GroupResolver(grouping_config)
        group_incident_engine = GroupIncidentEngine(group_policy)

    service = RealtimeQualityService(
        engine,
        incident_engine,
        group_resolver=group_resolver,
        group_incident_engine=group_incident_engine,
        event_filter=event_filter,
        event_filter_policy=event_filter_policy,
    )

    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_path = output_dir / "processed.jsonl"
    processed_path.write_text("", encoding="utf-8")
    publisher = JsonLinesPublisher(output_dir)
    if write_processed:
        publisher.scans_path.write_text("", encoding="utf-8")
    publisher.incidents_path.write_text("", encoding="utf-8")
    publisher.group_incidents_path.write_text("", encoding="utf-8")

    try:
        with ExitStack() as stack:
            processed_handle = None
            if write_processed:
                processed_handle = stack.enter_context(
                    processed_path.open("a", encoding="utf-8")
                )
            for scan_offset, (scan_index, timestamp, samples) in enumerate(
                _iter_scans(input_jsonl_path)
            ):
                if max_scans is not None and scan_offset >= max_scans:
                    break
                service.scan_index = scan_index
                processed_scan, incident_events, group_events = (
                    service.process_scan_samples(samples, timestamp=timestamp)
                )

                if write_processed:
                    publisher.publish_processed(
                        timestamp,
                        processed_scan.processed_signals,
                        suppression_stats=processed_scan.suppression_stats,
                    )
                    processed_rows = _build_processed_rows(
                        timestamp,
                        processed_scan.processed_signals,
                        processed_scan.suppression_stats,
                    )
                    for row in processed_rows:
                        processed_handle.write(json.dumps(row, sort_keys=True))
                        processed_handle.write("\n")
                if incident_events:
                    ordered_incidents = sorted(incident_events, key=_incident_sort_key)
                    publisher.publish_incidents(ordered_incidents)
                if group_events:
                    ordered_groups = sorted(group_events, key=_group_incident_sort_key)
                    publisher.publish_group_incidents(ordered_groups)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in replay input: {exc}") from exc


def _scan_signal_ids(input_jsonl_path: str) -> List[str]:
    signal_ids: List[str] = []
    seen = set()
    with Path(input_jsonl_path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number}: {exc}"
                ) from exc
            validate_scan_record(record)
            for signal_id in record["signals"].keys():
                if signal_id not in seen:
                    seen.add(signal_id)
                    signal_ids.append(signal_id)
    return signal_ids


def _iter_scans(
    input_jsonl_path: str,
) -> Iterable[Tuple[int, float, Dict[str, Sample]]]:
    with Path(input_jsonl_path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            validate_scan_record(record)
            scan_index = record["scan_index"]
            timestamp = float(record["timestamp"])
            signals = record["signals"]
            if not isinstance(signals, dict):
                raise ValueError(
                    f"signals must be a mapping on line {line_number}"
                )
            converted: Dict[str, Sample] = {}
            for signal_id, value in signals.items():
                try:
                    converted[signal_id] = parse_sample(value)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid value for {signal_id} on line {line_number}: {exc}"
                    ) from exc
            yield scan_index, timestamp, converted


def _build_processed_rows(
    scan_timestamp: float,
    processed: Dict[str, ProcessedSignal],
    suppression_stats: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    rows = []
    for signal_id in sorted(processed):
        signal = processed[signal_id]
        payload = {
            "scan_timestamp": scan_timestamp,
            "signal_id": signal_id,
            "timestamp": signal.timestamp,
            "sqi": signal.sqi,
            "quality_class": signal.quality_class,
            "dominant_cause": _dominant_cause(signal.sqi_components),
            "severity": _severity_from_signal(signal),
            "components": signal.sqi_components,
            "alert_level": signal.alert_level,
            "drift_alert": signal.drift_alert,
            "spike_alert": signal.spike_alert,
        }
        if suppression_stats is not None:
            payload["suppression_stats"] = suppression_stats
        rows.append(payload)
    return rows


def _build_incident_rows(events: List[IncidentEvent]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for event in sorted(events, key=_incident_sort_key):
        incident = event.incident
        rows.append(
            {
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
        )
    return rows


def _build_group_incident_rows(
    events: List[GroupIncidentEvent],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for event in sorted(events, key=_group_incident_sort_key):
        incident = event.incident
        details = incident.details or {}
        rows.append(
            {
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
        )
    return rows


def _incident_sort_key(event: IncidentEvent) -> Tuple[str, str]:
    return (event.incident.signal_id, event.event_type.value)


def _group_incident_sort_key(event: GroupIncidentEvent) -> Tuple[str, str]:
    return (event.incident.group_id, event.event_type.value)


def _dominant_cause(components: Dict[str, float]) -> str:
    if not components:
        return "unknown"
    return min(components.items(), key=lambda item: item[1])[0]


def _severity_from_signal(signal: ProcessedSignal) -> str:
    if signal.alert_level == "critical":
        return "critical"
    if signal.alert_level == "warning":
        return "warning"
    return "warning"
