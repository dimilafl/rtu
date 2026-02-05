"""Node incident tracking for root cause analysis.

Tracks incidents at the node level based on confidence thresholds.
Provides deterministic, stable incident lifecycle management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NodeIncident:
    """An incident representing a root cause at a node.

    Attributes:
        node_id: The affected node ID
        node_type: Type of node (comms_domain, poll_group, rtu, signal)
        start_scan: Scan index when incident opened
        start_timestamp: Timestamp when incident opened
        end_scan: Scan index when incident closed (None if active)
        end_timestamp: Timestamp when incident closed (None if active)
        peak_confidence: Highest confidence seen during incident
        peak_score: Highest score seen during incident
        supporting_signals: Representative signals supporting this incident
        cause_summary: Summary of cause types (e.g., {"missing": 3, "stale": 2})
        recommended_action: Recommended action code
    """

    node_id: str
    node_type: str
    start_scan: int
    start_timestamp: float
    end_scan: Optional[int] = None
    end_timestamp: Optional[float] = None
    peak_confidence: float = 0.0
    peak_score: float = 0.0
    supporting_signals: List[str] = field(default_factory=list)
    cause_summary: Dict[str, int] = field(default_factory=dict)
    recommended_action: str = "INVESTIGATE"

    @property
    def is_active(self) -> bool:
        """Check if incident is still active."""
        return self.end_scan is None

    @property
    def duration_scans(self) -> int:
        """Get incident duration in scans."""
        if self.end_scan is None:
            return 0  # Still active, duration unknown
        return self.end_scan - self.start_scan

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "start_scan": self.start_scan,
            "start_timestamp": self.start_timestamp,
            "end_scan": self.end_scan,
            "end_timestamp": self.end_timestamp,
            "peak_confidence": self.peak_confidence,
            "peak_score": self.peak_score,
            "supporting_signals": self.supporting_signals,
            "cause_summary": self.cause_summary,
            "recommended_action": self.recommended_action,
            "is_active": self.is_active,
        }


@dataclass
class NodeIncidentConfig:
    """Configuration for node incident tracking.

    Attributes:
        min_confidence_to_start: Minimum confidence to open an incident
        min_confidence_to_continue: Minimum confidence to keep incident open
        min_score_to_start: Minimum score to open an incident
        min_score_to_continue: Minimum score to keep incident open
        supporting_signals_max: Maximum supporting signals per incident
        cooldown_scans: Scans after close before node can reopen incident
    """

    min_confidence_to_start: float = 0.7
    min_confidence_to_continue: float = 0.3
    min_score_to_start: float = 0.5
    min_score_to_continue: float = 0.2
    supporting_signals_max: int = 10
    cooldown_scans: int = 3


class NodeIncidentTracker:
    """Tracks node incidents with deterministic lifecycle management.

    Incidents are opened when a node crosses confidence and score thresholds.
    Incidents are closed when confidence or score drops below continue thresholds.
    """

    def __init__(self, config: Optional[NodeIncidentConfig] = None) -> None:
        """Initialize tracker.

        Args:
            config: Incident configuration
        """
        self._config = config or NodeIncidentConfig()
        self._active_incidents: Dict[str, NodeIncident] = {}
        self._closed_incidents: List[NodeIncident] = []
        self._cooldown_until: Dict[str, int] = {}  # node_id -> scan_index

    @property
    def config(self) -> NodeIncidentConfig:
        """Get incident configuration."""
        return self._config

    def update(
        self,
        candidates: List[Any],  # List[RootCauseCandidate]
        scan_index: int,
        scan_timestamp: float,
    ) -> Dict[str, str]:
        """Update incident state from candidates.

        Args:
            candidates: List of RootCauseCandidate from scoring
            scan_index: Current scan index
            scan_timestamp: Current scan timestamp

        Returns:
            Dict of node_id -> action taken ("opened", "updated", "closed", None)
        """
        actions: Dict[str, str] = {}
        candidate_map = {c.node_id: c for c in candidates}

        # Check for incidents to close (candidates no longer present or below threshold)
        nodes_to_close = []
        for node_id, incident in self._active_incidents.items():
            candidate = candidate_map.get(node_id)
            should_close = False

            if candidate is None:
                # Node no longer a candidate
                should_close = True
            elif (
                candidate.confidence < self._config.min_confidence_to_continue
                or candidate.score < self._config.min_score_to_continue
            ):
                # Below continuation thresholds
                should_close = True

            if should_close:
                nodes_to_close.append(node_id)

        # Close incidents (separate loop to avoid modifying dict during iteration)
        for node_id in nodes_to_close:
            self._close_incident(node_id, scan_index, scan_timestamp)
            actions[node_id] = "closed"

        # Check for incidents to open or update
        for candidate in candidates:
            node_id = candidate.node_id

            # Check cooldown
            cooldown_end = self._cooldown_until.get(node_id, 0)
            if scan_index < cooldown_end:
                continue

            if node_id in self._active_incidents:
                # Update existing incident
                incident = self._active_incidents[node_id]
                self._update_incident(incident, candidate)
                if node_id not in actions:
                    actions[node_id] = "updated"
            else:
                # Check if should open new incident
                if (
                    candidate.confidence >= self._config.min_confidence_to_start
                    and candidate.score >= self._config.min_score_to_start
                ):
                    self._open_incident(candidate, scan_index, scan_timestamp)
                    actions[node_id] = "opened"

        return actions

    def _open_incident(
        self,
        candidate: Any,  # RootCauseCandidate
        scan_index: int,
        scan_timestamp: float,
    ) -> None:
        """Open a new incident for a candidate."""
        # Get supporting signals (bounded)
        supporting = (
            candidate.representative_signals[: self._config.supporting_signals_max]
            if hasattr(candidate, "representative_signals")
            else []
        )

        # Get cause summary from evidence
        cause_summary = {}
        if hasattr(candidate, "evidence") and candidate.evidence:
            cause_summary = dict(candidate.evidence.cause_mix)

        incident = NodeIncident(
            node_id=candidate.node_id,
            node_type=candidate.node_type,
            start_scan=scan_index,
            start_timestamp=scan_timestamp,
            peak_confidence=candidate.confidence,
            peak_score=candidate.score,
            supporting_signals=list(supporting),
            cause_summary=cause_summary,
            recommended_action=getattr(
                candidate, "recommended_action_code", "INVESTIGATE"
            ),
        )
        self._active_incidents[candidate.node_id] = incident

    def _update_incident(
        self,
        incident: NodeIncident,
        candidate: Any,  # RootCauseCandidate
    ) -> None:
        """Update an existing incident with new candidate data."""
        # Update peak values
        if candidate.confidence > incident.peak_confidence:
            incident.peak_confidence = candidate.confidence
        if candidate.score > incident.peak_score:
            incident.peak_score = candidate.score

        # Update supporting signals if changed significantly
        if hasattr(candidate, "representative_signals"):
            new_signals = candidate.representative_signals[
                : self._config.supporting_signals_max
            ]
            # Only update if new signals are different (to maintain stability)
            if set(new_signals) != set(incident.supporting_signals):
                # Merge: keep old signals that are still relevant, add new ones
                merged = []
                for sig in incident.supporting_signals:
                    if sig in new_signals:
                        merged.append(sig)
                for sig in new_signals:
                    if sig not in merged and len(merged) < self._config.supporting_signals_max:
                        merged.append(sig)
                incident.supporting_signals = merged

        # Update cause summary
        if hasattr(candidate, "evidence") and candidate.evidence:
            incident.cause_summary = dict(candidate.evidence.cause_mix)

    def _close_incident(
        self,
        node_id: str,
        scan_index: int,
        scan_timestamp: float,
    ) -> None:
        """Close an active incident."""
        if node_id not in self._active_incidents:
            return

        incident = self._active_incidents.pop(node_id)
        incident.end_scan = scan_index
        incident.end_timestamp = scan_timestamp
        self._closed_incidents.append(incident)

        # Set cooldown
        self._cooldown_until[node_id] = scan_index + self._config.cooldown_scans

    def list_active_incidents(self) -> List[NodeIncident]:
        """Get list of active incidents, sorted deterministically.

        Returns:
            List of active incidents sorted by (confidence desc, node_id asc)
        """
        incidents = list(self._active_incidents.values())
        incidents.sort(key=lambda i: (-i.peak_confidence, i.node_id))
        return incidents

    def list_closed_incidents(
        self,
        since_scan: Optional[int] = None,
    ) -> List[NodeIncident]:
        """Get list of closed incidents.

        Args:
            since_scan: Only return incidents closed at or after this scan

        Returns:
            List of closed incidents sorted by close time desc
        """
        if since_scan is not None:
            incidents = [
                i for i in self._closed_incidents
                if i.end_scan is not None and i.end_scan >= since_scan
            ]
        else:
            incidents = list(self._closed_incidents)

        # Sort by close scan descending, then node_id
        incidents.sort(key=lambda i: (-(i.end_scan or 0), i.node_id))
        return incidents

    def get_incident(self, node_id: str) -> Optional[NodeIncident]:
        """Get active incident for a node.

        Args:
            node_id: Node ID to look up

        Returns:
            Active incident or None
        """
        return self._active_incidents.get(node_id)

    def has_active_incident(self, node_id: str) -> bool:
        """Check if node has an active incident."""
        return node_id in self._active_incidents

    def active_count(self) -> int:
        """Get count of active incidents."""
        return len(self._active_incidents)

    def reset(self) -> None:
        """Reset all incident state."""
        self._active_incidents.clear()
        self._closed_incidents.clear()
        self._cooldown_until.clear()

    def prune_closed(self, keep_count: int = 1000) -> int:
        """Prune old closed incidents.

        Args:
            keep_count: Number of recent closed incidents to keep

        Returns:
            Number of incidents pruned
        """
        if len(self._closed_incidents) <= keep_count:
            return 0

        pruned = len(self._closed_incidents) - keep_count
        self._closed_incidents = self._closed_incidents[-keep_count:]
        return pruned

    def to_state_dict(self) -> Dict[str, Any]:
        """Serialize state for persistence."""
        return {
            "active": [i.to_dict() for i in self._active_incidents.values()],
            "closed": [i.to_dict() for i in self._closed_incidents[-100:]],
            "cooldown": dict(self._cooldown_until),
        }

    def load_state_dict(self, state: Dict[str, Any]) -> None:
        """Load state from persistence."""
        self._active_incidents.clear()
        self._closed_incidents.clear()
        self._cooldown_until.clear()

        for inc_dict in state.get("active", []):
            incident = _incident_from_dict(inc_dict)
            self._active_incidents[incident.node_id] = incident

        for inc_dict in state.get("closed", []):
            incident = _incident_from_dict(inc_dict)
            self._closed_incidents.append(incident)

        self._cooldown_until = dict(state.get("cooldown", {}))


def _incident_from_dict(data: Dict[str, Any]) -> NodeIncident:
    """Create NodeIncident from dictionary."""
    return NodeIncident(
        node_id=data["node_id"],
        node_type=data["node_type"],
        start_scan=data["start_scan"],
        start_timestamp=data["start_timestamp"],
        end_scan=data.get("end_scan"),
        end_timestamp=data.get("end_timestamp"),
        peak_confidence=data.get("peak_confidence", 0.0),
        peak_score=data.get("peak_score", 0.0),
        supporting_signals=data.get("supporting_signals", []),
        cause_summary=data.get("cause_summary", {}),
        recommended_action=data.get("recommended_action", "INVESTIGATE"),
    )


def get_default_incident_config() -> NodeIncidentConfig:
    """Get default incident configuration."""
    return NodeIncidentConfig()
