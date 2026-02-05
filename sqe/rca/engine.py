"""RCA engine for root cause analysis integration.

Provides the main RCAEngine class that integrates topology, evidence,
scoring, and confidence into a unified analysis pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from sqe.comms.budget import UtilizationStatus
from sqe.comms.health import CommsHealthStatus, summarize_comms_health
from sqe.topology.model import NodeType, TopologySnapshot
from sqe.topology.index import TopologyIndex
from sqe.rca.schema import (
    CommsBudgetSummary,
    LeafObservation,
    NodeEvidence,
    RootCauseCandidate,
    TroubleshootReport,
    OverallState,
    SCHEMA_VERSION,
)
from sqe.rca.evidence import (
    build_leaf_observations,
    aggregate_node_evidence,
    select_representative_signals,
)
from sqe.rca.state import RCAState
from sqe.rca.scoring import (
    ScoringConfig,
    score_candidates,
    get_default_scoring_config,
    get_primary_and_secondary,
)
from sqe.rca.confidence import (
    ConfidenceConfig,
    compute_all_confidences,
    get_default_confidence_config,
)


class RCAEngine:
    """Root Cause Analysis Engine.

    Integrates topology, evidence aggregation, scoring, and confidence
    into a unified analysis pipeline that produces TroubleshootReports.
    """

    def __init__(
        self,
        topology_snapshot: TopologySnapshot,
        topology_index: Optional[TopologyIndex] = None,
        scoring_config: Optional[ScoringConfig] = None,
        confidence_config: Optional[ConfidenceConfig] = None,
        *,
        affected_classes: Optional[Set[str]] = None,
        missing_ratio_threshold: float = 0.2,
        use_active_incidents: bool = True,
        use_quality_class: bool = True,
        representative_signals_max: int = 12,
        supporting_incidents_max: int = 30,
        retention_scans: int = 2000,
        min_confidence_for_primary: float = 0.0,
    ) -> None:
        """Initialize RCA engine.

        Args:
            topology_snapshot: Topology snapshot
            topology_index: Optional precomputed index (created if not provided)
            scoring_config: Scoring configuration
            confidence_config: Confidence configuration
            affected_classes: Quality classes indicating affected state
            missing_ratio_threshold: Missing ratio threshold for affected
            use_active_incidents: Use active incidents for affected detection
            use_quality_class: Use quality class for affected detection
            representative_signals_max: Max representative signals in report
            supporting_incidents_max: Max supporting incidents in report
            retention_scans: State retention window
            min_confidence_for_primary: Minimum confidence for primary candidate
        """
        self._snapshot = topology_snapshot
        self._index = topology_index or TopologyIndex(topology_snapshot)
        self._scoring_config = scoring_config or get_default_scoring_config()
        self._confidence_config = confidence_config or get_default_confidence_config()
        self._state = RCAState(retention_scans=retention_scans)

        self._affected_classes = affected_classes or {"POOR", "BAD"}
        self._missing_ratio_threshold = missing_ratio_threshold
        self._use_active_incidents = use_active_incidents
        self._use_quality_class = use_quality_class
        self._representative_signals_max = representative_signals_max
        self._supporting_incidents_max = supporting_incidents_max
        self._min_confidence_for_primary = min_confidence_for_primary

        # Apply representative_signals_max to scoring config
        self._scoring_config.representative_signals_max = representative_signals_max

    @property
    def topology_snapshot(self) -> TopologySnapshot:
        """Get underlying topology snapshot."""
        return self._snapshot

    @property
    def topology_index(self) -> TopologyIndex:
        """Get underlying topology index."""
        return self._index

    @property
    def state(self) -> RCAState:
        """Get RCA state."""
        return self._state

    def analyze(
        self,
        processed_signals: Dict[str, Any],
        scan_index: int,
        scan_timestamp: float,
        *,
        incident_events: Optional[List[Dict[str, Any]]] = None,
        missing_ratios: Optional[Dict[str, float]] = None,
        comms_health_statuses: Optional[List[CommsHealthStatus]] = None,
        comms_report_top_n: int = 10,
        comms_budget_statuses: Optional[List[UtilizationStatus]] = None,
        comms_budget_report_top_n: int = 10,
    ) -> TroubleshootReport:
        """Perform root cause analysis for a scan.

        Args:
            processed_signals: Dict of signal_id to ProcessedSignal or dict
            scan_index: Current scan index
            scan_timestamp: Current scan timestamp
            incident_events: Optional list of active incident events
            missing_ratios: Optional dict of signal_id to missing ratio

        Returns:
            TroubleshootReport with analysis results
        """
        # Build leaf observations
        observations = build_leaf_observations(
            processed_signals,
            incident_events=incident_events,
            missing_ratios=missing_ratios,
            affected_classes=self._affected_classes,
            missing_ratio_threshold=self._missing_ratio_threshold,
            use_active_incidents=self._use_active_incidents,
            use_quality_class=self._use_quality_class,
        )

        # Aggregate evidence
        evidence = aggregate_node_evidence(
            self._snapshot,
            self._index,
            observations,
            self._state,
            scan_index,
            scan_timestamp,
            coherence_k_scans=self._scoring_config.coherence_k_scans,
        )

        # Score candidates
        candidates = score_candidates(
            self._snapshot,
            self._index,
            evidence,
            observations,
            self._state,
            self._scoring_config,
        )

        # Compute confidence
        compute_all_confidences(
            candidates,
            self._state,
            self._confidence_config,
            min_confidence_threshold=self._min_confidence_for_primary,
        )

        # Build report
        return self._build_report(
            candidates,
            observations,
            evidence,
            incident_events,
            scan_index,
            scan_timestamp,
            comms_health_statuses,
            comms_report_top_n,
            comms_budget_statuses,
            comms_budget_report_top_n,
        )

    def _build_report(
        self,
        candidates: List[RootCauseCandidate],
        observations: Dict[str, LeafObservation],
        evidence: Dict[str, NodeEvidence],
        incident_events: Optional[List[Dict[str, Any]]],
        scan_index: int,
        scan_timestamp: float,
        comms_health_statuses: Optional[List[CommsHealthStatus]],
        comms_report_top_n: int,
        comms_budget_statuses: Optional[List[UtilizationStatus]],
        comms_budget_report_top_n: int,
    ) -> TroubleshootReport:
        """Build troubleshoot report from analysis results."""
        # Determine overall state
        affected_count = sum(1 for obs in observations.values() if obs.is_affected)
        total_count = len(observations)

        if affected_count == 0:
            overall_state = OverallState.OK
        elif total_count > 0 and affected_count / total_count > 0.5:
            overall_state = OverallState.OUTAGE
        else:
            overall_state = OverallState.DEGRADED

        # Get primary and secondary candidates
        primary, secondary = get_primary_and_secondary(
            candidates,
            max_secondary=5,
        )

        # Filter primary by confidence threshold
        if primary and primary.confidence < self._min_confidence_for_primary:
            primary = None

        # Build impacted nodes by type
        impacted_nodes: Dict[str, List[str]] = {}
        for node_id, node_evidence in evidence.items():
            if node_evidence.affected_children > 0:
                node_type = node_evidence.node_type
                if node_type not in impacted_nodes:
                    impacted_nodes[node_type] = []
                impacted_nodes[node_type].append(node_id)

        # Sort impacted lists
        for node_type in impacted_nodes:
            impacted_nodes[node_type] = sorted(impacted_nodes[node_type])

        # Select supporting incidents (bounded)
        supporting_incidents: List[Dict[str, Any]] = []
        if incident_events:
            # Sort by severity (lower SQI first), then by signal_id
            sorted_incidents = sorted(
                incident_events,
                key=lambda e: (
                    e.get("sqi", 100.0),
                    e.get("signal_id", ""),
                ),
            )
            supporting_incidents = sorted_incidents[:self._supporting_incidents_max]

        comms_summary = None
        if comms_health_statuses:
            comms_summary = summarize_comms_health(
                comms_health_statuses, top_n=comms_report_top_n
            )

        comms_budget_summary = None
        if comms_budget_statuses:
            comms_budget_summary = _summarize_comms_budget(
                comms_budget_statuses,
                top_n=comms_budget_report_top_n,
            )

        return TroubleshootReport(
            schema_version=SCHEMA_VERSION,
            scan_index=scan_index,
            scan_timestamp=scan_timestamp,
            topology_version_hash=self._snapshot.version_hash,
            overall_state=overall_state,
            primary=primary,
            secondary=secondary,
            impacted_nodes=impacted_nodes,
            supporting_incidents=supporting_incidents,
            comms_summary=comms_summary,
            comms_budget_summary=comms_budget_summary,
        )

    def reset(self) -> None:
        """Reset engine state."""
        self._state.reset()

    def prune_state(self) -> int:
        """Prune old state entries.

        Returns:
            Number of entries pruned
        """
        return self._state.prune_inactive()


def create_rca_engine_from_config(
    topology_snapshot: TopologySnapshot,
    config: Dict[str, Any],
) -> RCAEngine:
    """Create RCA engine from configuration dictionary.

    Args:
        topology_snapshot: Topology snapshot
        config: Configuration dictionary (from defaults.yaml rca section)

    Returns:
        Configured RCAEngine
    """
    # Extract affected policy
    affected_policy = config.get("affected_policy", {})
    affected_classes = set(affected_policy.get("affected_classes", ["POOR", "BAD"]))
    missing_ratio_threshold = affected_policy.get("missing_ratio_threshold", 0.2)
    use_active_incidents = affected_policy.get("use_active_incidents", True)
    use_quality_class = affected_policy.get("use_quality_class", True)

    # Extract scoring config
    scoring_dict = config.get("scoring", {})
    scoring_config = ScoringConfig(
        weights=scoring_dict.get("weights", {
            "coverage": 0.45,
            "concentration": 0.25,
            "coherence": 0.20,
            "signature": 0.10,
        }),
        coherence_k_scans=scoring_dict.get("coherence_k_scans", 5),
        min_fraction_by_type=scoring_dict.get("min_fraction_by_type"),
        type_score_norm=scoring_dict.get("type_score_norm"),
    )

    # Extract confidence config
    confidence_dict = config.get("confidence", {})
    confidence_config = ConfidenceConfig(
        required_scans=confidence_dict.get("required_scans", 2),
        margin_scale=confidence_dict.get("margin_scale", 0.2),
    )

    # Node incidents config for min confidence
    node_incidents = config.get("node_incidents", {})
    min_confidence = node_incidents.get("min_confidence_to_start", 0.0)

    return RCAEngine(
        topology_snapshot=topology_snapshot,
        scoring_config=scoring_config,
        confidence_config=confidence_config,
        affected_classes=affected_classes,
        missing_ratio_threshold=missing_ratio_threshold,
        use_active_incidents=use_active_incidents,
        use_quality_class=use_quality_class,
        representative_signals_max=config.get("representative_signals_max", 12),
        supporting_incidents_max=config.get("supporting_incidents_max", 30),
        retention_scans=config.get("retention_scans", 2000),
        min_confidence_for_primary=min_confidence,
    )


def _summarize_comms_budget(
    statuses: List[UtilizationStatus],
    *,
    top_n: int,
) -> CommsBudgetSummary:
    non_ok = [
        status for status in statuses if status.level in {"CRITICAL", "DEGRADED"}
    ]
    ordered = sorted(non_ok, key=_comms_budget_sort_key)
    bottleneck = ordered[0] if ordered else None
    critical = [
        status for status in ordered if status.level == "CRITICAL"
    ][:top_n]
    degraded = [
        status for status in ordered if status.level == "DEGRADED"
    ][:top_n]

    return CommsBudgetSummary(
        bottleneck_node=bottleneck,
        critical_utilization_nodes=critical,
        degraded_utilization_nodes=degraded,
    )


def _comms_budget_sort_key(status: UtilizationStatus) -> tuple[int, float, int, str]:
    node_type_priority = {"COMMS_DOMAIN": 0, "POLL_GROUP": 1, "RTU": 2}
    level_priority = {"CRITICAL": 0, "DEGRADED": 1, "OK": 2}
    return (
        level_priority.get(status.level, 99),
        -status.utilization,
        node_type_priority.get(status.node_type, 99),
        status.node_id,
    )
