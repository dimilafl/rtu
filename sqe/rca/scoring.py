"""Root cause scoring for candidate ranking.

Deterministic scoring algorithm for ranking root cause candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from sqe.topology.model import NodeType, TopologySnapshot
from sqe.topology.index import TopologyIndex
from sqe.rca.schema import (
    LeafObservation,
    NodeEvidence,
    RootCauseCandidate,
)
from sqe.rca.state import RCAState
from sqe.rca.evidence import select_representative_signals


@dataclass
class ScoringConfig:
    """Configuration for root cause scoring.

    Attributes:
        weights: Weight for each score component
        coherence_k_scans: K parameter for coherence computation
        min_fraction_by_type: Minimum affected fraction to be a candidate
        type_score_norm: Normalization parameters per type
        representative_signals_max: Max representative signals to include
    """

    weights: Dict[str, float]
    coherence_k_scans: int = 5
    min_fraction_by_type: Dict[str, float] = None
    type_score_norm: Dict[str, Dict[str, float]] = None
    representative_signals_max: int = 12

    def __post_init__(self):
        if self.min_fraction_by_type is None:
            self.min_fraction_by_type = {
                "comms_domain": 0.25,
                "poll_group": 0.25,
                "rtu": 0.50,
                "signal": 1.00,
            }
        if self.type_score_norm is None:
            self.type_score_norm = {
                "comms_domain": {"floor": 0.0, "ceiling": 1.2},
                "poll_group": {"floor": 0.0, "ceiling": 1.2},
                "rtu": {"floor": 0.0, "ceiling": 1.2},
                "signal": {"floor": 0.0, "ceiling": 1.2},
            }


def get_default_scoring_config() -> ScoringConfig:
    """Get default scoring configuration."""
    return ScoringConfig(
        weights={
            "coverage": 0.45,
            "concentration": 0.25,
            "coherence": 0.20,
            "signature": 0.10,
        },
    )


def score_candidates(
    topology_snapshot: TopologySnapshot,
    topology_index: TopologyIndex,
    node_evidence: Dict[str, NodeEvidence],
    observations: Dict[str, LeafObservation],
    state: RCAState,
    config: ScoringConfig,
) -> List[RootCauseCandidate]:
    """Score and rank root cause candidates.

    Args:
        topology_snapshot: Topology snapshot
        topology_index: Topology index
        node_evidence: Evidence for each node
        observations: Leaf observations
        state: RCA state
        config: Scoring configuration

    Returns:
        List of candidates sorted by score descending
    """
    candidates: List[RootCauseCandidate] = []

    # Type priority for tie-breaking (root-level types first)
    type_priority = {
        NodeType.COMMS_DOMAIN: 0,
        NodeType.POLL_GROUP: 1,
        NodeType.RTU: 2,
        NodeType.SIGNAL: 3,
    }

    for node_id, evidence in node_evidence.items():
        node = topology_snapshot.get_node(node_id)
        if node is None:
            continue

        # Check minimum fraction threshold
        node_type_str = node.node_type.value
        min_fraction = config.min_fraction_by_type.get(node_type_str, 0.0)
        if evidence.affected_fraction < min_fraction:
            continue

        # Compute score components
        score_components = _compute_score_components(
            evidence,
            config.weights,
        )

        # Compute total score
        total_score = sum(
            config.weights.get(component, 0.0) * value
            for component, value in score_components.items()
        )

        # Normalize score by type
        norm_params = config.type_score_norm.get(
            node_type_str,
            {"floor": 0.0, "ceiling": 1.2},
        )
        normalized_score = _normalize_score(
            total_score,
            norm_params["floor"],
            norm_params["ceiling"],
        )

        # Get representative signals
        affected_signals = [
            sig_id for sig_id, obs in observations.items()
            if obs.is_affected and sig_id in topology_index.get_descendants(node_id)
        ]
        representative = select_representative_signals(
            observations,
            affected_signals,
            config.representative_signals_max,
        )

        # Determine recommended action
        action_code = _determine_action_code(evidence, node.node_type)

        candidates.append(RootCauseCandidate(
            node_id=node_id,
            node_type=node_type_str,
            score=normalized_score,
            score_components=score_components,
            confidence=0.0,  # Will be computed later
            evidence=evidence,
            recommended_action_code=action_code,
            representative_signals=representative,
        ))

    # Sort candidates deterministically
    # Primary: score descending
    # Secondary: type priority (root-level first)
    # Tertiary: node_id ascending
    def sort_key(c: RootCauseCandidate) -> tuple:
        node = topology_snapshot.get_node(c.node_id)
        type_prio = type_priority.get(node.node_type, 999) if node else 999
        return (-c.score, type_prio, c.node_id)

    candidates.sort(key=sort_key)

    return candidates


def _compute_score_components(
    evidence: NodeEvidence,
    weights: Dict[str, float],
) -> Dict[str, float]:
    """Compute individual score components.

    All components normalized to [0, 1] range.
    """
    components: Dict[str, float] = {}

    # Coverage: affected fraction
    coverage = evidence.affected_fraction
    components["coverage"] = coverage

    # Concentration: how focused vs siblings
    # Already computed in evidence, clamp to [0, 1]
    concentration = max(0.0, min(1.0, (evidence.concentration_score + 1.0) / 2.0))
    components["concentration"] = concentration

    # Coherence: temporal clustering
    coherence = evidence.coherence_score
    components["coherence"] = coherence

    # Signature: comms-like signature
    # Higher signature score if cause mix is missing/stale heavy
    signature = evidence.comms_signature_score
    components["signature"] = signature

    return components


def _normalize_score(
    score: float,
    floor: float,
    ceiling: float,
) -> float:
    """Normalize score to [0, 1] range based on floor/ceiling."""
    if ceiling <= floor:
        return 0.0
    normalized = (score - floor) / (ceiling - floor)
    return max(0.0, min(1.0, normalized))


def _determine_action_code(
    evidence: NodeEvidence,
    node_type: NodeType,
) -> str:
    """Determine recommended action code based on evidence."""
    # Check cause mix for dominant cause
    cause_mix = evidence.cause_mix
    total_causes = sum(cause_mix.values())

    if total_causes == 0:
        return "INVESTIGATE"

    # Check for comms-related issues
    comms_count = cause_mix.get("missing", 0) + cause_mix.get("stale", 0)
    if comms_count / total_causes > 0.7:
        if node_type == NodeType.COMMS_DOMAIN:
            return "CHECK_NETWORK_INFRASTRUCTURE"
        elif node_type == NodeType.POLL_GROUP:
            return "CHECK_POLL_GROUP_CONFIG"
        elif node_type == NodeType.RTU:
            return "CHECK_RTU_CONNECTIVITY"
        else:
            return "CHECK_SIGNAL_PATH"

    # Check for signal quality issues
    quality_count = (
        cause_mix.get("noise", 0) +
        cause_mix.get("drift", 0) +
        cause_mix.get("spikes", 0) +
        cause_mix.get("oscillation", 0)
    )
    if quality_count / total_causes > 0.5:
        return "CHECK_SENSOR_CALIBRATION"

    return "INVESTIGATE"


def filter_candidates_by_threshold(
    candidates: List[RootCauseCandidate],
    min_score: float = 0.0,
    min_confidence: float = 0.0,
) -> List[RootCauseCandidate]:
    """Filter candidates by score and confidence thresholds."""
    return [
        c for c in candidates
        if c.score >= min_score and c.confidence >= min_confidence
    ]


def get_primary_and_secondary(
    candidates: List[RootCauseCandidate],
    max_secondary: int = 5,
) -> tuple:
    """Get primary candidate and secondary candidates.

    Returns:
        Tuple of (primary, secondary_list)
    """
    if not candidates:
        return None, []

    primary = candidates[0]
    secondary = candidates[1:max_secondary + 1]

    return primary, secondary
