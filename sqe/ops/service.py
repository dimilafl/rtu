"""Realtime quality service orchestrating SQE and incidents."""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from sqe.core.engine import ProcessedSignal, SignalQualityEngine
from sqe.core.incidents import IncidentEngine, IncidentEvent


class RealtimeQualityService:
    """Scan-driven service that emits processed signals and incident events."""

    def __init__(
        self,
        engine: SignalQualityEngine,
        incident_engine: IncidentEngine,
    ) -> None:
        self.engine = engine
        self.incident_engine = incident_engine
        self.scan_index = 0

    def process_scan(
        self,
        signals: Dict[str, Optional[float]],
        timestamp: Optional[float] = None,
    ) -> Tuple[Dict[str, ProcessedSignal], List[IncidentEvent]]:
        if timestamp is None:
            timestamp = time.time()

        processed = self.engine.update(signals, timestamp=timestamp)

        missing_ratio_by_signal = {
            signal_id: processor.missing_buffer.get_missing_ratio()
            for signal_id, processor in self.engine.processors.items()
        }

        events = self.incident_engine.update_scan(
            scan_index=self.scan_index,
            timestamp=timestamp,
            processed_signals=processed,
            missing_ratio_by_signal=missing_ratio_by_signal,
        )
        self.scan_index += 1
        return processed, events
