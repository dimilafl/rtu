"""Realtime quality service orchestrating SQE and incidents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqe.core.engine import ProcessedSignal, SignalQualityEngine
from sqe.core.event_filter import EventFilter, EventFilterPolicy
from sqe.core.incidents import IncidentEngine, IncidentEvent
from sqe.core.group_incidents import GroupIncidentEngine, GroupIncidentEvent
from sqe.core.grouping import GroupResolver
from sqe.core.sample import Sample
from sqe.comms.health import (
    CommsHealthStatus,
    CommsHealthThresholds,
    aggregate_comms_metrics,
    classify_comms_health,
)
from sqe.comms.schema import CommsMetrics
from sqe.schema import SCHEMA_VERSION


@dataclass(frozen=True)
class ProcessedScan:
    processed_signals: Dict[str, ProcessedSignal]
    suppression_stats: Optional[Dict[str, int]] = None
    comms_health: Optional[List[CommsHealthStatus]] = None
    schema_version: str = SCHEMA_VERSION


class RealtimeQualityService:
    """Scan-driven service that emits processed signals and incident events."""

    def __init__(
        self,
        engine: SignalQualityEngine,
        incident_engine: IncidentEngine,
        group_resolver: Optional[GroupResolver] = None,
        group_incident_engine: Optional[GroupIncidentEngine] = None,
        event_filter: Optional[EventFilter] = None,
        event_filter_policy: Optional[EventFilterPolicy] = None,
        *,
        comms_enabled: bool = False,
        comms_thresholds: Optional[CommsHealthThresholds] = None,
    ) -> None:
        self.engine = engine
        self.incident_engine = incident_engine
        self.group_resolver = group_resolver
        self.group_incident_engine = group_incident_engine
        self.event_filter = event_filter
        self.event_filter_policy = event_filter_policy
        self.comms_enabled = comms_enabled
        self.comms_thresholds = (
            comms_thresholds or CommsHealthThresholds.from_config({})
        )
        self.scan_index = 0

    def process_scan(
        self,
        signals: Dict[str, Optional[float]],
        timestamp: Optional[float] = None,
        comms_health_by_signal: Optional[Dict[str, Dict[str, Any]]] = None,
        comms_metrics: Optional[List[CommsMetrics]] = None,
    ) -> Tuple[ProcessedScan, List[IncidentEvent], List[GroupIncidentEvent]]:
        timestamp = self.engine._resolve_scan_timestamp(timestamp)

        processed = self.engine.update(signals, timestamp=timestamp)

        missing_ratio_by_signal = {
            signal_id: processor.get_effective_missing_ratio()
            for signal_id, processor in self.engine.processors.items()
        }
        raw_missing_ratio_by_signal = {
            signal_id: processor.missing_buffer.get_missing_ratio()
            for signal_id, processor in self.engine.processors.items()
        }

        statuses = self.incident_engine.evaluate_signal_statuses(
            processed_signals=processed,
            missing_ratio_by_signal=missing_ratio_by_signal,
            raw_missing_ratio_by_signal=raw_missing_ratio_by_signal,
        )
        events = self.incident_engine.update_scan(
            scan_index=self.scan_index,
            timestamp=timestamp,
            processed_signals=processed,
            missing_ratio_by_signal=missing_ratio_by_signal,
            raw_missing_ratio_by_signal=raw_missing_ratio_by_signal,
        )
        group_events: List[GroupIncidentEvent] = []
        signal_id_to_group_id: Dict[str, str] = {}
        if self.group_resolver and self.group_incident_engine:
            group_id_to_member_status: Dict[str, Dict[str, Dict[str, Any]]] = {}
            for signal_id, status in statuses.items():
                group_id = self.group_resolver.resolve_group_id(signal_id)
                if group_id is None:
                    continue
                enriched = dict(status)
                if comms_health_by_signal and signal_id in comms_health_by_signal:
                    enriched["comms"] = comms_health_by_signal[signal_id]
                group_id_to_member_status.setdefault(group_id, {})[signal_id] = enriched
                signal_id_to_group_id[signal_id] = group_id
            group_events = self.group_incident_engine.update_scan(
                scan_index=self.scan_index,
                timestamp=timestamp,
                group_id_to_member_status=group_id_to_member_status,
            )
        suppression_stats: Optional[Dict[str, int]] = None
        if self.event_filter and self.event_filter_policy:
            active_group_incidents = (
                self.group_incident_engine.get_active_incidents()
                if self.group_incident_engine
                else {}
            )
            events, stats = self.event_filter.filter_events(
                scan_index=self.scan_index,
                timestamp=timestamp,
                signal_events=events,
                group_events=group_events,
                active_group_incidents=active_group_incidents,
                signal_id_to_group_id=signal_id_to_group_id,
            )
            if stats:
                suppression_stats = stats
        self.scan_index += 1
        comms_health: Optional[List[CommsHealthStatus]] = None
        if self.comms_enabled and comms_metrics:
            aggregates = aggregate_comms_metrics(comms_metrics)
            comms_health = [
                classify_comms_health(aggregate, self.comms_thresholds)
                for _, aggregate in sorted(aggregates.items())
            ]
        return (
            ProcessedScan(
                processed, suppression_stats, comms_health=comms_health
            ),
            events,
            group_events,
        )

    def process_scan_samples(
        self,
        samples: Dict[str, Sample],
        timestamp: Optional[float] = None,
        comms_health_by_signal: Optional[Dict[str, Dict[str, Any]]] = None,
        comms_metrics: Optional[List[CommsMetrics]] = None,
    ) -> Tuple[ProcessedScan, List[IncidentEvent], List[GroupIncidentEvent]]:
        timestamp = self.engine._resolve_scan_timestamp(timestamp)

        processed = self.engine.update_samples(samples, timestamp=timestamp)

        missing_ratio_by_signal = {
            signal_id: processor.get_effective_missing_ratio()
            for signal_id, processor in self.engine.processors.items()
        }
        raw_missing_ratio_by_signal = {
            signal_id: processor.missing_buffer.get_missing_ratio()
            for signal_id, processor in self.engine.processors.items()
        }

        statuses = self.incident_engine.evaluate_signal_statuses(
            processed_signals=processed,
            missing_ratio_by_signal=missing_ratio_by_signal,
            raw_missing_ratio_by_signal=raw_missing_ratio_by_signal,
        )
        events = self.incident_engine.update_scan(
            scan_index=self.scan_index,
            timestamp=timestamp,
            processed_signals=processed,
            missing_ratio_by_signal=missing_ratio_by_signal,
            raw_missing_ratio_by_signal=raw_missing_ratio_by_signal,
        )
        group_events: List[GroupIncidentEvent] = []
        signal_id_to_group_id: Dict[str, str] = {}
        if self.group_resolver and self.group_incident_engine:
            group_id_to_member_status: Dict[str, Dict[str, Dict[str, Any]]] = {}
            for signal_id, status in statuses.items():
                group_id = self.group_resolver.resolve_group_id(signal_id)
                if group_id is None:
                    continue
                enriched = dict(status)
                if comms_health_by_signal and signal_id in comms_health_by_signal:
                    enriched["comms"] = comms_health_by_signal[signal_id]
                group_id_to_member_status.setdefault(group_id, {})[signal_id] = enriched
                signal_id_to_group_id[signal_id] = group_id
            group_events = self.group_incident_engine.update_scan(
                scan_index=self.scan_index,
                timestamp=timestamp,
                group_id_to_member_status=group_id_to_member_status,
            )
        suppression_stats: Optional[Dict[str, int]] = None
        if self.event_filter and self.event_filter_policy:
            active_group_incidents = (
                self.group_incident_engine.get_active_incidents()
                if self.group_incident_engine
                else {}
            )
            events, stats = self.event_filter.filter_events(
                scan_index=self.scan_index,
                timestamp=timestamp,
                signal_events=events,
                group_events=group_events,
                active_group_incidents=active_group_incidents,
                signal_id_to_group_id=signal_id_to_group_id,
            )
            if stats:
                suppression_stats = stats
        self.scan_index += 1
        comms_health: Optional[List[CommsHealthStatus]] = None
        if self.comms_enabled and comms_metrics:
            aggregates = aggregate_comms_metrics(comms_metrics)
            comms_health = [
                classify_comms_health(aggregate, self.comms_thresholds)
                for _, aggregate in sorted(aggregates.items())
            ]
        return (
            ProcessedScan(
                processed, suppression_stats, comms_health=comms_health
            ),
            events,
            group_events,
        )
