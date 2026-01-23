"""Realtime quality service orchestrating SQE and incidents."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from sqe.core.engine import ProcessedSignal, SignalQualityEngine
from sqe.core.incidents import IncidentEngine, IncidentEvent
from sqe.core.group_incidents import GroupIncidentEngine, GroupIncidentEvent
from sqe.core.grouping import GroupResolver
from sqe.core.sample import Sample


class RealtimeQualityService:
    """Scan-driven service that emits processed signals and incident events."""

    def __init__(
        self,
        engine: SignalQualityEngine,
        incident_engine: IncidentEngine,
        group_resolver: Optional[GroupResolver] = None,
        group_incident_engine: Optional[GroupIncidentEngine] = None,
    ) -> None:
        self.engine = engine
        self.incident_engine = incident_engine
        self.group_resolver = group_resolver
        self.group_incident_engine = group_incident_engine
        self.scan_index = 0

    def process_scan(
        self,
        signals: Dict[str, Optional[float]],
        timestamp: Optional[float] = None,
    ) -> Tuple[
        Dict[str, ProcessedSignal],
        List[IncidentEvent],
        List[GroupIncidentEvent],
    ]:
        if timestamp is None:
            timestamp = time.time()

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
        if self.group_resolver and self.group_incident_engine:
            group_id_to_member_status: Dict[str, Dict[str, Dict[str, Any]]] = {}
            for signal_id, status in statuses.items():
                group_id = self.group_resolver.resolve_group_id(signal_id)
                if group_id is None:
                    continue
                group_id_to_member_status.setdefault(group_id, {})[signal_id] = status
            group_events = self.group_incident_engine.update_scan(
                scan_index=self.scan_index,
                timestamp=timestamp,
                group_id_to_member_status=group_id_to_member_status,
            )
        self.scan_index += 1
        return processed, events, group_events

    def process_scan_samples(
        self,
        samples: Dict[str, Sample],
        timestamp: Optional[float] = None,
    ) -> Tuple[
        Dict[str, ProcessedSignal],
        List[IncidentEvent],
        List[GroupIncidentEvent],
    ]:
        if timestamp is None:
            timestamp = time.time()

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
        if self.group_resolver and self.group_incident_engine:
            group_id_to_member_status: Dict[str, Dict[str, Dict[str, Any]]] = {}
            for signal_id, status in statuses.items():
                group_id = self.group_resolver.resolve_group_id(signal_id)
                if group_id is None:
                    continue
                group_id_to_member_status.setdefault(group_id, {})[
                    signal_id
                ] = status
            group_events = self.group_incident_engine.update_scan(
                scan_index=self.scan_index,
                timestamp=timestamp,
                group_id_to_member_status=group_id_to_member_status,
            )
        self.scan_index += 1
        return processed, events, group_events
