"""RCA schema definitions for evidence and reports.

All dataclasses designed for deterministic serialization with stable ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from sqe.topology.model import NodeType


class OverallState(Enum):
    """Overall system health state."""

    OK = "OK"
    DEGRADED = "DEGRADED"
    OUTAGE = "OUTAGE"


# Bounded set of known incident causes
KNOWN_CAUSES = frozenset([
    "noise",
    "drift",
    "spikes",
    "oscillation",
    "missing",
    "stale",
    "step",
    "plausibility",
    "comms",
    "unknown",
])

# Bounded set of known quality classes
KNOWN_QUALITY_CLASSES = frozenset([
    "EXCELLENT",
    "GOOD",
    "FAIR",
    "POOR",
    "BAD",
])

# Schema version for troubleshoot reports
SCHEMA_VERSION = "1.0.0"


@dataclass
class LeafObservation:
    """Observation for a single signal (leaf node) at a scan.

    Attributes:
        signal_id: Signal identifier
        is_affected: Whether signal is in affected state
        cause: Primary cause if affected (from bounded set)
        quality_class: SQI quality classification
        missing_ratio: Missing sample ratio (0..1)
        sqi: Signal quality index value
        has_active_incident: Whether signal has active incident
        onset_scan: Scan index when signal became affected (if known)
    """

    signal_id: str
    is_affected: bool
    cause: Optional[str] = None
    quality_class: str = "GOOD"
    missing_ratio: float = 0.0
    sqi: float = 100.0
    has_active_incident: bool = False
    onset_scan: Optional[int] = None


@dataclass
class NodeEvidence:
    """Aggregated evidence for a topology node.

    Attributes:
        node_id: Node identifier
        node_type: Type of node (NodeType enum value string)
        scan_index: Current scan index
        scan_timestamp: Current scan timestamp
        total_children: Total number of descendant signals
        affected_children: Number of affected descendant signals
        affected_fraction: Ratio of affected to total (0..1)
        cause_mix: Count of each cause type among affected children
        class_mix: Count of each quality class among affected children
        onset_scan_min: Earliest onset scan among affected children
        onset_scan_max: Latest onset scan among affected children
        onset_span_scans: Span of onset scans (max - min)
        comms_signature_score: Score indicating comms-like signature (0..1)
        coherence_score: Score indicating temporal coherence (0..1)
        concentration_score: Score indicating fault concentration vs siblings
        counterevidence: Factors that argue against this node as root cause
    """

    node_id: str
    node_type: str
    scan_index: int
    scan_timestamp: float
    total_children: int
    affected_children: int
    affected_fraction: float
    cause_mix: Dict[str, int] = field(default_factory=dict)
    class_mix: Dict[str, int] = field(default_factory=dict)
    onset_scan_min: Optional[int] = None
    onset_scan_max: Optional[int] = None
    onset_span_scans: int = 0
    comms_signature_score: float = 0.0
    coherence_score: float = 0.0
    concentration_score: float = 0.0
    counterevidence: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with stable key ordering."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "scan_index": self.scan_index,
            "scan_timestamp": self.scan_timestamp,
            "total_children": self.total_children,
            "affected_children": self.affected_children,
            "affected_fraction": self.affected_fraction,
            "cause_mix": dict(sorted(self.cause_mix.items())),
            "class_mix": dict(sorted(self.class_mix.items())),
            "onset_scan_min": self.onset_scan_min,
            "onset_scan_max": self.onset_scan_max,
            "onset_span_scans": self.onset_span_scans,
            "comms_signature_score": self.comms_signature_score,
            "coherence_score": self.coherence_score,
            "concentration_score": self.concentration_score,
            "counterevidence": dict(sorted(self.counterevidence.items())),
        }


@dataclass
class RootCauseCandidate:
    """A candidate root cause node with scoring.

    Attributes:
        node_id: Node identifier
        node_type: Type of node (NodeType enum value string)
        score: Overall root cause score
        score_components: Breakdown of score by component
        confidence: Confidence level (0..1)
        evidence: Underlying node evidence
        recommended_action_code: Code for recommended action
        representative_signals: Sample of affected signals (bounded list)
    """

    node_id: str
    node_type: str
    score: float
    score_components: Dict[str, float]
    confidence: float
    evidence: NodeEvidence
    recommended_action_code: str = "INVESTIGATE"
    representative_signals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with stable key ordering."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "score": self.score,
            "score_components": dict(sorted(self.score_components.items())),
            "confidence": self.confidence,
            "evidence": self.evidence.to_dict(),
            "recommended_action_code": self.recommended_action_code,
            "representative_signals": list(self.representative_signals),
        }


@dataclass
class TroubleshootReport:
    """Complete troubleshoot report for a scan.

    All lists are bounded and deterministically ordered.

    Attributes:
        schema_version: Report schema version
        scan_index: Scan index for this report
        scan_timestamp: Scan timestamp
        topology_version_hash: Hash of topology used
        overall_state: OK, DEGRADED, or OUTAGE
        primary: Primary root cause candidate (if any)
        secondary: Secondary candidates (bounded list)
        impacted_nodes: Nodes impacted by type
        supporting_incidents: Supporting incident events (bounded list)
    """

    schema_version: str
    scan_index: int
    scan_timestamp: float
    topology_version_hash: str
    overall_state: OverallState
    primary: Optional[RootCauseCandidate] = None
    secondary: List[RootCauseCandidate] = field(default_factory=list)
    impacted_nodes: Dict[str, List[str]] = field(default_factory=dict)
    supporting_incidents: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with stable key ordering."""
        # Sort impacted_nodes by type
        sorted_impacted = {}
        for node_type in sorted(self.impacted_nodes.keys()):
            sorted_impacted[node_type] = sorted(self.impacted_nodes[node_type])

        return {
            "schema_version": self.schema_version,
            "scan_index": self.scan_index,
            "scan_timestamp": self.scan_timestamp,
            "topology_version_hash": self.topology_version_hash,
            "overall_state": self.overall_state.value,
            "primary": self.primary.to_dict() if self.primary else None,
            "secondary": [c.to_dict() for c in self.secondary],
            "impacted_nodes": sorted_impacted,
            "supporting_incidents": list(self.supporting_incidents),
        }

    @staticmethod
    def create_ok_report(
        scan_index: int,
        scan_timestamp: float,
        topology_version_hash: str,
    ) -> "TroubleshootReport":
        """Create an OK report with no issues."""
        return TroubleshootReport(
            schema_version=SCHEMA_VERSION,
            scan_index=scan_index,
            scan_timestamp=scan_timestamp,
            topology_version_hash=topology_version_hash,
            overall_state=OverallState.OK,
        )


def normalize_cause(cause: Optional[str]) -> str:
    """Normalize cause string to bounded set."""
    if cause is None:
        return "unknown"
    normalized = cause.lower().strip()
    if normalized in KNOWN_CAUSES:
        return normalized
    return "unknown"


def normalize_quality_class(quality_class: Optional[str]) -> str:
    """Normalize quality class to bounded set."""
    if quality_class is None:
        return "GOOD"
    normalized = quality_class.upper().strip()
    if normalized in KNOWN_QUALITY_CLASSES:
        return normalized
    return "GOOD"
