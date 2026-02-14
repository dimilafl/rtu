"""Quality incident engine for SQE outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from sqe.core.engine import ProcessedSignal
from sqe.schema import SCHEMA_VERSION


class IncidentEventType(str, Enum):
    """Incident event types."""

    STARTED = "started"
    UPDATED = "updated"
    RESOLVED = "resolved"


class IncidentSeverity(str, Enum):
    """Incident severity levels."""

    WARNING = "warning"
    CRITICAL = "critical"


class IncidentCause(str, Enum):
    """Dominant incident cause."""

    MISSING = "missing"
    STALE = "stale"
    STEP = "step"
    PLAUSIBILITY = "plausibility"
    NOISE = "noise"
    DRIFT = "drift"
    SPIKES = "spikes"
    OSCILLATION = "oscillation"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IncidentPolicy:
    start_sqi_threshold: float
    end_sqi_threshold: float
    start_persistence_scans: int
    end_persistence_scans: int
    critical_sqi_threshold: float
    component_score_floor: float
    state_retention_scans: int = 100000
    cause_priority: List[IncidentCause] = field(default_factory=list)
    hard_fault_causes: List[IncidentCause] = field(default_factory=list)
    emit_update_on_cause_change: bool = True
    emit_update_on_severity_change: bool = True


@dataclass
class QualityIncident:
    incident_id: str
    signal_id: str
    cause: IncidentCause
    severity: IncidentSeverity
    start_timestamp: float
    last_timestamp: float
    end_timestamp: Optional[float]
    min_sqi: float
    last_sqi: float
    start_scan_index: int
    last_scan_index: int
    details: Dict[str, Any]


@dataclass(frozen=True)
class IncidentEvent:
    event_type: IncidentEventType
    incident: QualityIncident
    message: str
    recommended_action: str
    schema_version: str = SCHEMA_VERSION


@dataclass
class _SignalIncidentState:
    active_incident: Optional[QualityIncident] = None
    degraded_streak: int = 0
    recovered_streak: int = 0
    last_seen_scan_index: Optional[int] = None


CAUSE_ACTIONS = {
    IncidentCause.MISSING: (
        "Check comms path, poll group, RTU health, and network stability."
    ),
    IncidentCause.STALE: (
        "Check sensor update path, frozen polls, and timestamp wiring."
    ),
    IncidentCause.STEP: (
        "Check sensor replacement, scaling changes, or swapped channels."
    ),
    IncidentCause.PLAUSIBILITY: (
        "Verify engineering limits, scaling, and sensor plausibility."
    ),
    IncidentCause.DRIFT: (
        "Check instrument calibration, impulse line, and sensor health."
    ),
    IncidentCause.SPIKES: "Check scaling, comm retries, and transient glitches.",
    IncidentCause.NOISE: (
        "Check wiring, grounding, and consider filtering or sensor replacement."
    ),
    IncidentCause.OSCILLATION: (
        "Check control loop stability, regulator hunting, and tuning."
    ),
    IncidentCause.UNKNOWN: "Inspect trend and raw quality flags for root cause.",
}


class IncidentEngine:
    """Scan-driven incident engine for SQI outputs."""

    def __init__(self, policy: IncidentPolicy, *, run_id: Optional[str] = None) -> None:
        self.policy = policy
        self._state_by_signal: Dict[str, _SignalIncidentState] = {}
        self._cause_priority = list(policy.cause_priority)
        self.run_id = run_id or uuid.uuid4().hex

    def update_scan(
        self,
        scan_index: int,
        timestamp: float,
        processed_signals: Dict[str, ProcessedSignal],
        missing_ratio_by_signal: Dict[str, float],
        raw_missing_ratio_by_signal: Optional[Dict[str, float]] = None,
    ) -> List[IncidentEvent]:
        events: List[IncidentEvent] = []

        evaluations = self.evaluate_signal_statuses(
            processed_signals=processed_signals,
            missing_ratio_by_signal=missing_ratio_by_signal,
            raw_missing_ratio_by_signal=raw_missing_ratio_by_signal,
            include_details=True,
        )

        for signal_id, evaluation in evaluations.items():
            processed = processed_signals.get(signal_id)
            state = self._state_by_signal.setdefault(signal_id, _SignalIncidentState())
            state.last_seen_scan_index = scan_index

            degraded = evaluation["degraded"]
            recovered = evaluation["recovered"]
            cause = evaluation["cause"]
            severity = evaluation["severity"]
            sqi_value = evaluation["sqi"]
            details = evaluation["details"]

            if state.active_incident is None:
                if degraded:
                    state.degraded_streak += 1
                else:
                    state.degraded_streak = 0
                state.recovered_streak = 0

                if degraded and state.degraded_streak >= self.policy.start_persistence_scans:
                    start_scan_index = (
                        scan_index - self.policy.start_persistence_scans + 1
                    )
                    incident = QualityIncident(
                        incident_id=f"{self.run_id}:{signal_id}:{start_scan_index}",
                        signal_id=signal_id,
                        cause=cause,
                        severity=severity,
                        start_timestamp=timestamp,
                        last_timestamp=timestamp,
                        end_timestamp=None,
                        min_sqi=sqi_value,
                        last_sqi=sqi_value,
                        start_scan_index=start_scan_index,
                        last_scan_index=scan_index,
                        details=details,
                    )
                    state.active_incident = incident
                    state.degraded_streak = 0
                    events.append(
                        IncidentEvent(
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
            if degraded:
                state.recovered_streak = 0
                incident.last_timestamp = timestamp
                incident.last_scan_index = scan_index
                incident.last_sqi = sqi_value
                incident.min_sqi = min(incident.min_sqi, sqi_value)
                incident.details = details

                cause_changed = incident.cause != cause
                severity_changed = incident.severity != severity
                if cause_changed:
                    incident.cause = cause
                if severity_changed:
                    incident.severity = severity

                should_emit = (
                    (cause_changed and self.policy.emit_update_on_cause_change)
                    or (severity_changed and self.policy.emit_update_on_severity_change)
                )
                if should_emit:
                    events.append(
                        IncidentEvent(
                            event_type=IncidentEventType.UPDATED,
                            incident=incident,
                            message=self._build_update_message(
                                incident,
                                cause_changed=cause_changed,
                                severity_changed=severity_changed,
                            ),
                            recommended_action=CAUSE_ACTIONS[incident.cause],
                        )
                    )
                continue

            if recovered:
                state.recovered_streak += 1
            else:
                state.recovered_streak = 0

            if state.recovered_streak >= self.policy.end_persistence_scans:
                incident.last_timestamp = timestamp
                incident.last_scan_index = scan_index
                incident.last_sqi = sqi_value
                incident.details = details
                incident.end_timestamp = timestamp
                events.append(
                    IncidentEvent(
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

        self._prune_state(scan_index)
        return events

    def evaluate_signal_statuses(
        self,
        processed_signals: Dict[str, ProcessedSignal],
        missing_ratio_by_signal: Dict[str, float],
        raw_missing_ratio_by_signal: Optional[Dict[str, float]] = None,
        include_details: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        evaluations: Dict[str, Dict[str, Any]] = {}
        for signal_id, missing_ratio in missing_ratio_by_signal.items():
            raw_missing_ratio = (
                raw_missing_ratio_by_signal.get(signal_id, missing_ratio)
                if raw_missing_ratio_by_signal is not None
                else missing_ratio
            )
            processed = processed_signals.get(signal_id)
            evaluation = self._evaluate_signal(
                processed=processed,
                missing_ratio=missing_ratio,
                raw_missing_ratio=raw_missing_ratio,
            )
            if not include_details:
                evaluation = {
                    key: evaluation[key]
                    for key in ("degraded", "recovered", "cause", "severity", "sqi")
                }
            evaluations[signal_id] = evaluation
        return evaluations

    def _evaluate_signal(
        self,
        processed: Optional[ProcessedSignal],
        missing_ratio: float,
        raw_missing_ratio: float,
    ) -> Dict[str, Any]:
        missing_score = self._missing_score(missing_ratio)
        if processed is None:
            degraded = missing_score <= self.policy.component_score_floor
            recovered = missing_score >= self.policy.component_score_floor
            cause = (
                IncidentCause.MISSING
                if degraded
                else IncidentCause.UNKNOWN
            )
            severity = IncidentSeverity.WARNING
            return {
                "degraded": degraded,
                "recovered": recovered,
                "cause": cause,
                "severity": severity,
                "sqi": missing_score,
                "details": self._build_details(
                    processed=processed,
                    missing_ratio=missing_ratio,
                    raw_missing_ratio=raw_missing_ratio,
                    missing_score=missing_score,
                ),
            }

        degraded = (
            processed.sqi <= self.policy.start_sqi_threshold
            or missing_score <= self.policy.component_score_floor
        )
        recovered = processed.sqi >= self.policy.end_sqi_threshold
        cause = self._select_cause(processed, missing_ratio, missing_score)
        severity = (
            IncidentSeverity.CRITICAL
            if processed.sqi <= self.policy.critical_sqi_threshold
            else IncidentSeverity.WARNING
        )

        return {
            "degraded": degraded,
            "recovered": recovered,
            "cause": cause,
            "severity": severity,
            "sqi": processed.sqi,
            "details": self._build_details(
                processed=processed,
                missing_ratio=missing_ratio,
                raw_missing_ratio=raw_missing_ratio,
                missing_score=missing_score,
            ),
        }

    def _select_cause(
        self,
        processed: ProcessedSignal,
        missing_ratio: float,
        missing_score: float,
    ) -> IncidentCause:
        component_causes = {
            "noise": IncidentCause.NOISE,
            "drift": IncidentCause.DRIFT,
            "spikes": IncidentCause.SPIKES,
            "oscillation": IncidentCause.OSCILLATION,
            "missing": IncidentCause.MISSING,
            "stale": IncidentCause.STALE,
            "step": IncidentCause.STEP,
            "plausibility": IncidentCause.PLAUSIBILITY,
        }
        candidates: List[Tuple[IncidentCause, float]] = []
        for name, score in processed.sqi_components.items():
            if score <= self.policy.component_score_floor:
                cause = component_causes.get(name)
                if cause and self._is_cause_eligible(cause, processed):
                    candidates.append((cause, score))

        if not candidates:
            if (
                missing_score <= self.policy.component_score_floor
                and self._is_cause_eligible(IncidentCause.MISSING, processed)
            ):
                return IncidentCause.MISSING
            return IncidentCause.UNKNOWN

        candidates.sort(
            key=lambda item: (
                item[1],
                self._cause_priority_index(item[0]),
            )
        )
        return candidates[0][0]

    def _is_cause_eligible(
        self,
        cause: IncidentCause,
        processed: ProcessedSignal,
    ) -> bool:
        if cause in self.policy.hard_fault_causes:
            return True
        component_name = {
            IncidentCause.NOISE: "noise",
            IncidentCause.DRIFT: "drift",
            IncidentCause.SPIKES: "spikes",
            IncidentCause.OSCILLATION: "oscillation",
            IncidentCause.MISSING: "missing",
            IncidentCause.STALE: "stale",
            IncidentCause.STEP: "step",
            IncidentCause.PLAUSIBILITY: "plausibility",
        }.get(cause)
        if component_name is None:
            return True
        weight = processed.sqi_weights.get(component_name, 0.0)
        return weight > 0

    def _cause_priority_index(self, cause: IncidentCause) -> int:
        if cause in self._cause_priority:
            return self._cause_priority.index(cause)
        return len(self._cause_priority)

    @staticmethod
    def _missing_score(missing_ratio: float) -> float:
        score = 100.0 * (1.0 - missing_ratio)
        return max(0.0, min(100.0, score))

    def _build_details(
        self,
        processed: Optional[ProcessedSignal],
        missing_ratio: float,
        raw_missing_ratio: float,
        missing_score: float,
    ) -> Dict[str, Any]:
        if processed is None:
            return {
                "components": {"missing": missing_score},
                "missing_ratio": raw_missing_ratio,
                "effective_missing_ratio": missing_ratio,
            }
        details = {
            "components": dict(processed.sqi_components),
            "missing_ratio": raw_missing_ratio,
            "effective_missing_ratio": missing_ratio,
            "alert_level": processed.alert_level,
            "drift_alert": processed.drift_alert,
            "spike_alert": processed.spike_alert,
            "quality_class": processed.quality_class,
        }
        if processed.innovation_z is not None:
            details["innovation_spike"] = {
                "z": processed.innovation_z,
                "abs_z": abs(processed.innovation_z),
                "z_spike": processed.innovation_z_spike,
                "residual": processed.innovation_residual,
                "S": processed.innovation_S,
                "v_hat": processed.innovation_v_hat,
                "eta": processed.innovation_eta,
                "spike_frequency": processed.spike_frequency,
                "is_spike": processed.is_spike,
            }
        return details

    def _build_message(
        self,
        incident: QualityIncident,
        event_type: IncidentEventType,
    ) -> str:
        if event_type == IncidentEventType.STARTED:
            return (
                f"Incident started for {incident.signal_id} "
                f"due to {incident.cause.value}."
            )
        if event_type == IncidentEventType.RESOLVED:
            return f"Incident resolved for {incident.signal_id}."
        return f"Incident updated for {incident.signal_id}."

    def _build_update_message(
        self,
        incident: QualityIncident,
        cause_changed: bool,
        severity_changed: bool,
    ) -> str:
        parts: List[str] = []
        if cause_changed:
            parts.append(f"cause {incident.cause.value}")
        if severity_changed:
            parts.append(f"severity {incident.severity.value}")
        detail = ", ".join(parts) if parts else "status"
        return f"Incident updated for {incident.signal_id} with {detail}."

    def _prune_state(self, scan_index: int) -> None:
        retention = self.policy.state_retention_scans
        if retention <= 0:
            return
        to_prune = [
            signal_id
            for signal_id, state in self._state_by_signal.items()
            if state.active_incident is None
            and state.last_seen_scan_index is not None
            and scan_index - state.last_seen_scan_index > retention
        ]
        for signal_id in to_prune:
            del self._state_by_signal[signal_id]


def required_causes_from_policy(policy: IncidentPolicy) -> Set[str]:
    """Return component names that must be computed for incidents."""
    return {cause.value for cause in policy.hard_fault_causes}
