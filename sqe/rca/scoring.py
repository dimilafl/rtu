"""Root cause scoring for candidate ranking.

Deterministic scoring algorithm for ranking root cause candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Any, Dict, List, Optional, Tuple

from sqe.comms.budget import UtilizationStatus
from sqe.comms.health import CommsHealthStatus
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
        comms_scoring: Configuration for comms-aware scoring terms
    """

    weights: Dict[str, float]
    coherence_k_scans: int = 5
    min_fraction_by_type: Dict[str, float] = None
    type_score_norm: Dict[str, Dict[str, float]] = None
    representative_signals_max: int = 12
    comms_scoring: "CommsScoringConfig" = None

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
        if self.comms_scoring is None:
            self.comms_scoring = CommsScoringConfig()


@dataclass
class CommsScoringConfig:
    """Configuration for comms-aware RCA scoring terms."""

    enabled: bool = True
    leaf_comms_gate: float = 0.35
    coherence_k_scans: int = 4
    weights: Dict[str, float] = None
    node_type_multiplier: Dict[str, float] = None
    leaf_likeness_weights: Dict[str, float] = None
    normalization: Dict[str, float] = None

    def __post_init__(self) -> None:
        if self.weights is None:
            self.weights = {
                "comms_boost": 0.35,
                "comms_counter": 0.25,
            }
        if self.node_type_multiplier is None:
            self.node_type_multiplier = {
                "comms_domain": 1.0,
                "poll_group": 1.0,
                "rtu": 0.5,
                "signal": 0.0,
            }
        if self.leaf_likeness_weights is None:
            self.leaf_likeness_weights = {
                "missing_fraction": 0.6,
                "coherence": 0.5,
                "non_missing_fraction": 0.9,
            }
        if self.normalization is None:
            self.normalization = {
                "utilization_degraded": 0.70,
                "utilization_critical": 0.90,
                "timeout_rate_degraded": 0.02,
                "timeout_rate_critical": 0.10,
                "jitter_ms_degraded": 250,
                "jitter_ms_critical": 750,
            }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CommsScoringConfig":
        if not data:
            return cls()
        return cls(
            enabled=data.get("enabled", True),
            leaf_comms_gate=data.get("leaf_comms_gate", 0.35),
            coherence_k_scans=data.get("coherence_k_scans", 4),
            weights=data.get("weights"),
            node_type_multiplier=data.get("node_type_multiplier"),
            leaf_likeness_weights=data.get("leaf_likeness_weights"),
            normalization=data.get("normalization"),
        )


def get_default_scoring_config() -> ScoringConfig:
    """Get default scoring configuration."""
    return ScoringConfig(
        weights={
            "coverage": 0.45,
            "concentration": 0.25,
            "coherence": 0.20,
            "signature": 0.10,
        },
        comms_scoring=CommsScoringConfig(),
    )


def score_candidates(
    topology_snapshot: TopologySnapshot,
    topology_index: TopologyIndex,
    node_evidence: Dict[str, NodeEvidence],
    observations: Dict[str, LeafObservation],
    state: RCAState,
    config: ScoringConfig,
    *,
    comms_budget_statuses: Optional[List[UtilizationStatus]] = None,
    comms_health_statuses: Optional[List[CommsHealthStatus]] = None,
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

    comms_config = config.comms_scoring
    has_comms_inputs = bool(comms_budget_statuses or comms_health_statuses)
    leaf_comms_likeness = _compute_leaf_comms_likeness(
        observations,
        comms_config,
        enabled=comms_config.enabled and has_comms_inputs,
    )
    util_map, health_map = _index_comms_statuses(
        comms_budget_statuses,
        comms_health_statuses,
    )

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
        base_components = _compute_score_components(
            evidence,
            config.weights,
        )

        comms_components = _compute_comms_components(
            evidence,
            node.node_type.value,
            leaf_comms_likeness,
            comms_config,
            util_map,
            health_map,
            enabled=comms_config.enabled and has_comms_inputs,
        )

        score_components = {**base_components, **comms_components}

        # Compute total score
        total_score = sum(
            config.weights.get(component, 0.0) * value
            for component, value in base_components.items()
        )
        total_score += score_components["comms_boost"]
        total_score -= score_components["comms_counter"]

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


def _compute_leaf_comms_likeness(
    observations: Dict[str, LeafObservation],
    comms_config: CommsScoringConfig,
    *,
    enabled: bool,
) -> float:
    if not enabled or not observations:
        return 0.0

    affected_ids = [
        signal_id
        for signal_id in sorted(observations.keys())
        if observations[signal_id].is_affected
    ]
    affected_count = len(affected_ids)
    if affected_count == 0:
        return 0.0

    missing_like = {"missing", "stale"}
    missing_ids = [
        signal_id
        for signal_id in affected_ids
        if observations[signal_id].cause in missing_like
    ]
    missing_count = len(missing_ids)
    non_missing_count = affected_count - missing_count

    missing_fraction = missing_count / affected_count
    non_missing_fraction = non_missing_count / affected_count

    onset_scans = [
        observations[signal_id].onset_scan
        for signal_id in missing_ids
        if observations[signal_id].onset_scan is not None
    ]
    if onset_scans and comms_config.coherence_k_scans > 0:
        onset_span = max(onset_scans) - min(onset_scans)
        coherence = exp(-onset_span / comms_config.coherence_k_scans)
    else:
        coherence = 0.0

    weights = comms_config.leaf_likeness_weights
    raw_score = (
        weights.get("missing_fraction", 0.0) * missing_fraction
        + weights.get("coherence", 0.0) * coherence
        - weights.get("non_missing_fraction", 0.0) * non_missing_fraction
    )
    leaf_comms_likeness = _clamp01(raw_score)
    if leaf_comms_likeness < comms_config.leaf_comms_gate:
        return 0.0
    return leaf_comms_likeness


def _index_comms_statuses(
    comms_budget_statuses: Optional[List[UtilizationStatus]],
    comms_health_statuses: Optional[List[CommsHealthStatus]],
) -> Tuple[Dict[Tuple[str, str], UtilizationStatus], Dict[Tuple[str, str], CommsHealthStatus]]:
    util_map: Dict[Tuple[str, str], UtilizationStatus] = {}
    health_map: Dict[Tuple[str, str], CommsHealthStatus] = {}

    if comms_budget_statuses:
        for status in sorted(
            comms_budget_statuses,
            key=lambda s: (s.node_type, s.node_id),
        ):
            util_map[(status.node_type.lower(), status.node_id)] = status

    if comms_health_statuses:
        for status in sorted(
            comms_health_statuses,
            key=lambda s: (s.node_type, s.node_id),
        ):
            health_map[(status.node_type.lower(), status.node_id)] = status

    return util_map, health_map


def _compute_node_comms_strength(
    node_type: str,
    node_id: str,
    comms_config: CommsScoringConfig,
    util_map: Dict[Tuple[str, str], UtilizationStatus],
    health_map: Dict[Tuple[str, str], CommsHealthStatus],
) -> float:
    util_status = util_map.get((node_type, node_id))
    health_status = health_map.get((node_type, node_id))
    if util_status is None or health_status is None:
        return 0.0

    normalization = comms_config.normalization
    util_norm = _normalize_value(
        util_status.utilization,
        normalization["utilization_degraded"],
        normalization["utilization_critical"],
    )
    timeout_norm = _normalize_value(
        health_status.timeout_rate,
        normalization["timeout_rate_degraded"],
        normalization["timeout_rate_critical"],
    )
    jitter_value = health_status.avg_jitter_ms
    if jitter_value is None:
        return 0.0
    jitter_norm = _normalize_value(
        jitter_value,
        normalization["jitter_ms_degraded"],
        normalization["jitter_ms_critical"],
    )

    return _clamp01((util_norm + timeout_norm + jitter_norm) / 3.0)


def _compute_comms_components(
    evidence: NodeEvidence,
    node_type: str,
    leaf_comms_likeness: float,
    comms_config: CommsScoringConfig,
    util_map: Dict[Tuple[str, str], UtilizationStatus],
    health_map: Dict[Tuple[str, str], CommsHealthStatus],
    *,
    enabled: bool,
) -> Dict[str, float]:
    components: Dict[str, float] = {
        "comms_boost": 0.0,
        "comms_counter": 0.0,
        "leaf_comms_likeness": leaf_comms_likeness if enabled else 0.0,
        "node_comms_strength": 0.0,
        "alignment": 0.0,
    }

    if not enabled or leaf_comms_likeness <= 0.0:
        return components

    multiplier = comms_config.node_type_multiplier.get(node_type, 0.0)
    if multiplier <= 0.0:
        return components

    node_strength = _compute_node_comms_strength(
        node_type,
        evidence.node_id,
        comms_config,
        util_map,
        health_map,
    )
    alignment = _clamp01(evidence.affected_fraction) * _clamp01(
        max(0.0, evidence.concentration_score),
    )
    weights = comms_config.weights
    components["comms_boost"] = (
        weights.get("comms_boost", 0.0)
        * multiplier
        * leaf_comms_likeness
        * node_strength
        * alignment
    )
    components["comms_counter"] = (
        weights.get("comms_counter", 0.0)
        * multiplier
        * leaf_comms_likeness
        * (1.0 - node_strength)
        * _clamp01(evidence.affected_fraction)
    )
    components["node_comms_strength"] = node_strength
    components["alignment"] = alignment
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


def _normalize_value(value: float, degraded: float, critical: float) -> float:
    if critical <= degraded:
        return 0.0
    return _clamp01((value - degraded) / (critical - degraded))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


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
