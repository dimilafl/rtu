"""Evidence aggregation for root cause analysis.

Builds leaf observations from processed signals and aggregates
evidence up the topology hierarchy.
"""

from __future__ import annotations

from collections import defaultdict
from math import exp
from typing import Any, Dict, List, Optional, Set

from sqe.topology.model import NodeType, TopologySnapshot
from sqe.topology.index import TopologyIndex
from sqe.rca.schema import (
    LeafObservation,
    NodeEvidence,
    normalize_cause,
    normalize_quality_class,
)
from sqe.rca.state import RCAState


def build_leaf_observations(
    processed_signals: Dict[str, Any],
    incident_events: Optional[List[Dict[str, Any]]] = None,
    missing_ratios: Optional[Dict[str, float]] = None,
    *,
    affected_classes: Optional[Set[str]] = None,
    missing_ratio_threshold: float = 0.2,
    use_active_incidents: bool = True,
    use_quality_class: bool = True,
) -> Dict[str, LeafObservation]:
    """Build leaf observations from processed signals.

    Args:
        processed_signals: Dict of signal_id to ProcessedSignal or dict
        incident_events: Optional list of active incident events
        missing_ratios: Optional dict of signal_id to missing ratio
        affected_classes: Quality classes that indicate affected state
        missing_ratio_threshold: Missing ratio threshold for affected state
        use_active_incidents: Use active incidents to determine affected state
        use_quality_class: Use quality class to determine affected state

    Returns:
        Dict of signal_id to LeafObservation
    """
    if affected_classes is None:
        affected_classes = {"POOR", "BAD"}

    # Build set of signals with active incidents
    active_incident_signals: Set[str] = set()
    incident_causes: Dict[str, str] = {}

    if incident_events and use_active_incidents:
        for event in incident_events:
            signal_id = event.get("signal_id")
            event_type = event.get("event_type", "")
            if signal_id and event_type in ("started", "updated"):
                active_incident_signals.add(signal_id)
                cause = event.get("cause", "unknown")
                incident_causes[signal_id] = normalize_cause(cause)

    observations: Dict[str, LeafObservation] = {}

    for signal_id, processed in processed_signals.items():
        # Extract fields from ProcessedSignal or dict
        if hasattr(processed, "to_dict"):
            data = processed.to_dict()
        elif isinstance(processed, dict):
            data = processed
        else:
            continue

        quality_class = normalize_quality_class(data.get("quality_class", "GOOD"))
        sqi = data.get("sqi", 100.0)
        missing_ratio = 0.0

        if missing_ratios and signal_id in missing_ratios:
            missing_ratio = missing_ratios[signal_id]

        # Determine if affected
        is_affected = False
        cause = None

        # Check active incidents
        if use_active_incidents and signal_id in active_incident_signals:
            is_affected = True
            cause = incident_causes.get(signal_id, "unknown")

        # Check quality class
        if use_quality_class and quality_class in affected_classes:
            is_affected = True
            if cause is None:
                # Infer cause from signal data
                cause = _infer_cause_from_signal(data)

        # Check missing ratio
        if missing_ratio >= missing_ratio_threshold:
            is_affected = True
            if cause is None:
                cause = "missing"

        observations[signal_id] = LeafObservation(
            signal_id=signal_id,
            is_affected=is_affected,
            cause=cause,
            quality_class=quality_class,
            missing_ratio=missing_ratio,
            sqi=sqi,
            has_active_incident=signal_id in active_incident_signals,
        )

    return observations


def _infer_cause_from_signal(data: Dict[str, Any]) -> str:
    """Infer primary cause from signal data.

    Uses SQI components to determine dominant cause.
    """
    components = data.get("sqi_components", {})
    if not components:
        return "unknown"

    # Find lowest scoring component
    min_score = 100.0
    min_cause = "unknown"

    cause_mapping = {
        "noise": "noise",
        "drift": "drift",
        "spikes": "spikes",
        "oscillation": "oscillation",
        "missing": "missing",
        "stale": "stale",
        "step": "step",
        "plausibility": "plausibility",
    }

    for component, score in components.items():
        if component in cause_mapping and score < min_score:
            min_score = score
            min_cause = cause_mapping[component]

    return min_cause


def aggregate_node_evidence(
    topology_snapshot: TopologySnapshot,
    topology_index: TopologyIndex,
    observations: Dict[str, LeafObservation],
    state: RCAState,
    scan_index: int,
    scan_timestamp: float,
    *,
    coherence_k_scans: int = 5,
) -> Dict[str, NodeEvidence]:
    """Aggregate evidence from leaf observations to all nodes.

    Args:
        topology_snapshot: Topology snapshot
        topology_index: Precomputed topology index
        observations: Leaf observations by signal_id
        state: RCA state for onset tracking
        scan_index: Current scan index
        scan_timestamp: Current scan timestamp
        coherence_k_scans: K parameter for coherence score

    Returns:
        Dict of node_id to NodeEvidence for all nodes with descendants
    """
    # Update state with current scan
    state.advance_scan(scan_index)

    # Update signal states and get onset scans
    for signal_id, obs in observations.items():
        onset = state.update_signal(
            signal_id,
            obs.is_affected,
            obs.cause,
            obs.quality_class,
        )
        if onset is not None:
            obs.onset_scan = onset

    # Aggregate evidence for each node type (bottom up)
    evidence: Dict[str, NodeEvidence] = {}

    # Process all nodes that have descendants
    for node_id in topology_snapshot.node_order:
        node = topology_snapshot.get_node(node_id)
        if node is None:
            continue

        # Get descendant signals
        descendants = topology_index.get_descendants(node_id)
        if not descendants:
            continue

        total = len(descendants)
        affected_count = 0
        cause_counts: Dict[str, int] = defaultdict(int)
        class_counts: Dict[str, int] = defaultdict(int)
        onset_scans: List[int] = []

        for desc_id in sorted(descendants):
            obs = observations.get(desc_id)
            if obs is None:
                continue

            if obs.is_affected:
                affected_count += 1
                if obs.cause:
                    cause_counts[normalize_cause(obs.cause)] += 1
                class_counts[obs.quality_class] += 1
                if obs.onset_scan is not None:
                    onset_scans.append(obs.onset_scan)

        # Compute metrics
        affected_fraction = affected_count / total if total > 0 else 0.0

        onset_min = min(onset_scans) if onset_scans else None
        onset_max = max(onset_scans) if onset_scans else None
        onset_span = (onset_max - onset_min) if onset_min is not None and onset_max is not None else 0

        # Coherence: exponential decay based on onset span
        coherence = exp(-onset_span / coherence_k_scans) if onset_span >= 0 else 0.0

        # Comms signature: fraction of missing/stale causes
        comms_causes = cause_counts.get("missing", 0) + cause_counts.get("stale", 0)
        comms_signature = comms_causes / affected_count if affected_count > 0 else 0.0

        # Concentration score: compare to siblings
        concentration = _compute_concentration(
            node_id,
            node,
            affected_fraction,
            topology_snapshot,
            topology_index,
            observations,
        )

        # Build counterevidence
        counterevidence: Dict[str, float] = {}
        if affected_fraction < 1.0 and node.node_type != NodeType.SIGNAL:
            counterevidence["partial_impact"] = 1.0 - affected_fraction

        evidence[node_id] = NodeEvidence(
            node_id=node_id,
            node_type=node.node_type.value,
            scan_index=scan_index,
            scan_timestamp=scan_timestamp,
            total_children=total,
            affected_children=affected_count,
            affected_fraction=affected_fraction,
            cause_mix=dict(sorted(cause_counts.items())),
            class_mix=dict(sorted(class_counts.items())),
            onset_scan_min=onset_min,
            onset_scan_max=onset_max,
            onset_span_scans=onset_span,
            comms_signature_score=comms_signature,
            coherence_score=coherence,
            concentration_score=concentration,
            counterevidence=counterevidence,
        )

    return evidence


def _compute_concentration(
    node_id: str,
    node,
    affected_fraction: float,
    topology_snapshot: TopologySnapshot,
    topology_index: TopologyIndex,
    observations: Dict[str, LeafObservation],
) -> float:
    """Compute concentration score (how focused the impact is on this node vs siblings).

    Returns:
        Score: affected_fraction - max(sibling_affected_fractions)
        Positive means this node is more affected than siblings.
    """
    siblings = topology_index.get_siblings(node_id)
    if not siblings:
        return 0.0

    max_sibling_fraction = 0.0

    for sibling_id in siblings:
        sibling_descendants = topology_index.get_descendants(sibling_id)
        if not sibling_descendants:
            continue

        sibling_total = len(sibling_descendants)
        sibling_affected = sum(
            1 for d in sibling_descendants
            if d in observations and observations[d].is_affected
        )
        sibling_fraction = sibling_affected / sibling_total if sibling_total > 0 else 0.0
        max_sibling_fraction = max(max_sibling_fraction, sibling_fraction)

    return affected_fraction - max_sibling_fraction


def select_representative_signals(
    observations: Dict[str, LeafObservation],
    affected_signal_ids: List[str],
    max_signals: int = 12,
) -> List[str]:
    """Select representative signals from affected set.

    Deterministic selection sorted by (severity, onset_scan, signal_id).

    Args:
        observations: Leaf observations
        affected_signal_ids: List of affected signal IDs
        max_signals: Maximum number to return

    Returns:
        Sorted list of representative signal IDs
    """
    if not affected_signal_ids:
        return []

    # Sort by severity (lower SQI = more severe), onset scan, then ID for tie-break
    def sort_key(signal_id: str) -> tuple:
        obs = observations.get(signal_id)
        if obs is None:
            return (100.0, 999999999, signal_id)
        onset = obs.onset_scan if obs.onset_scan is not None else 999999999
        return (obs.sqi, onset, signal_id)

    sorted_signals = sorted(affected_signal_ids, key=sort_key)
    return sorted_signals[:max_signals]
