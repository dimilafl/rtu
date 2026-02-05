"""Topology-aware suppression for root cause analysis.

Provides mechanisms to suppress child incidents and alerts when a parent
node has an active incident, reducing noise and alert fatigue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from sqe.topology.model import NodeType, TopologySnapshot
from sqe.topology.index import TopologyIndex
from sqe.rca.node_incidents import NodeIncident, NodeIncidentTracker


@dataclass
class SuppressionConfig:
    """Configuration for topology-aware suppression.

    Attributes:
        enabled: Whether suppression is enabled
        suppress_child_signals: Suppress signal-level alerts when parent incident active
        suppress_child_incidents: Suppress child node incidents when parent incident active
        suppressed_types: Node types that can be suppressed
        suppressor_types: Node types that can suppress children
        min_suppressor_confidence: Minimum confidence for a node to suppress children
    """

    enabled: bool = True
    suppress_child_signals: bool = True
    suppress_child_incidents: bool = True
    suppressed_types: Set[str] = field(
        default_factory=lambda: {"signal", "rtu", "poll_group"}
    )
    suppressor_types: Set[str] = field(
        default_factory=lambda: {"comms_domain", "poll_group", "rtu"}
    )
    min_suppressor_confidence: float = 0.5


class SuppressionManager:
    """Manages topology-aware suppression of incidents and alerts.

    When a parent node (e.g., RTU, poll_group, comms_domain) has an active
    incident with sufficient confidence, child nodes are suppressed.
    This reduces alert noise when a root cause is already identified.
    """

    def __init__(
        self,
        topology_snapshot: TopologySnapshot,
        topology_index: TopologyIndex,
        incident_tracker: NodeIncidentTracker,
        config: Optional[SuppressionConfig] = None,
    ) -> None:
        """Initialize suppression manager.

        Args:
            topology_snapshot: Topology snapshot
            topology_index: Topology index for ancestor lookups
            incident_tracker: Node incident tracker
            config: Suppression configuration
        """
        self._snapshot = topology_snapshot
        self._index = topology_index
        self._tracker = incident_tracker
        self._config = config or SuppressionConfig()

        # Cache of currently suppressed nodes
        self._suppressed_nodes: Dict[str, str] = {}  # node_id -> suppressor_id

    @property
    def config(self) -> SuppressionConfig:
        """Get suppression configuration."""
        return self._config

    def update(self) -> Dict[str, str]:
        """Update suppression state based on active incidents.

        Returns:
            Dict mapping suppressed node IDs to suppressor node IDs
        """
        if not self._config.enabled:
            self._suppressed_nodes.clear()
            return {}

        new_suppressed: Dict[str, str] = {}

        # Get all active incidents
        active_incidents = self._tracker.list_active_incidents()

        # Find nodes that are suppressors
        suppressors: List[NodeIncident] = []
        for incident in active_incidents:
            if (
                incident.node_type in self._config.suppressor_types
                and incident.peak_confidence >= self._config.min_suppressor_confidence
            ):
                suppressors.append(incident)

        # For each suppressor, mark all descendants as suppressed
        # Note: We need to get ALL descendants, not just signal descendants
        for suppressor in suppressors:
            all_descendants = self._get_all_descendants(suppressor.node_id)
            for desc_id in all_descendants:
                node = self._snapshot.get_node(desc_id)
                if node is None:
                    continue

                node_type = node.node_type.value
                if node_type in self._config.suppressed_types:
                    # Only suppress if not already suppressed by a closer ancestor
                    if desc_id not in new_suppressed:
                        new_suppressed[desc_id] = suppressor.node_id

        self._suppressed_nodes = new_suppressed
        return new_suppressed

    def _get_all_descendants(self, node_id: str) -> Set[str]:
        """Get all descendants of a node (not just signals).

        Args:
            node_id: Node to get descendants for

        Returns:
            Set of all descendant node IDs
        """
        descendants: Set[str] = set()
        to_visit = list(self._snapshot.get_children(node_id))

        while to_visit:
            child_id = to_visit.pop()
            if child_id not in descendants:
                descendants.add(child_id)
                to_visit.extend(self._snapshot.get_children(child_id))

        return descendants

    def is_suppressed(self, node_id: str) -> bool:
        """Check if a node is currently suppressed.

        Args:
            node_id: Node ID to check

        Returns:
            True if node is suppressed by an ancestor incident
        """
        return node_id in self._suppressed_nodes

    def get_suppressor(self, node_id: str) -> Optional[str]:
        """Get the suppressor for a node.

        Args:
            node_id: Node ID to check

        Returns:
            ID of suppressing node, or None if not suppressed
        """
        return self._suppressed_nodes.get(node_id)

    def list_suppressed_nodes(self) -> List[str]:
        """Get list of all suppressed node IDs.

        Returns:
            Sorted list of suppressed node IDs
        """
        return sorted(self._suppressed_nodes.keys())

    def list_suppressed_signals(self) -> List[str]:
        """Get list of suppressed signal IDs.

        Returns:
            Sorted list of suppressed signal IDs
        """
        suppressed = []
        for node_id in self._suppressed_nodes:
            node = self._snapshot.get_node(node_id)
            if node and node.node_type == NodeType.SIGNAL:
                suppressed.append(node_id)
        return sorted(suppressed)

    def should_suppress_incident(self, node_id: str) -> bool:
        """Check if an incident should be suppressed for a node.

        Args:
            node_id: Node ID to check

        Returns:
            True if incident should be suppressed
        """
        if not self._config.enabled or not self._config.suppress_child_incidents:
            return False
        return node_id in self._suppressed_nodes

    def should_suppress_alert(self, signal_id: str) -> bool:
        """Check if an alert should be suppressed for a signal.

        Args:
            signal_id: Signal ID to check

        Returns:
            True if alert should be suppressed
        """
        if not self._config.enabled or not self._config.suppress_child_signals:
            return False
        return signal_id in self._suppressed_nodes

    def get_suppression_summary(self) -> Dict[str, Any]:
        """Get summary of current suppression state.

        Returns:
            Dictionary with suppression statistics and details
        """
        # Count by type
        by_type: Dict[str, int] = {}
        for node_id in self._suppressed_nodes:
            node = self._snapshot.get_node(node_id)
            if node:
                node_type = node.node_type.value
                by_type[node_type] = by_type.get(node_type, 0) + 1

        # Group by suppressor
        by_suppressor: Dict[str, List[str]] = {}
        for node_id, suppressor_id in self._suppressed_nodes.items():
            if suppressor_id not in by_suppressor:
                by_suppressor[suppressor_id] = []
            by_suppressor[suppressor_id].append(node_id)

        # Sort lists for determinism
        for suppressor_id in by_suppressor:
            by_suppressor[suppressor_id] = sorted(by_suppressor[suppressor_id])

        return {
            "enabled": self._config.enabled,
            "total_suppressed": len(self._suppressed_nodes),
            "suppressed_by_type": by_type,
            "suppressed_by_source": {
                k: len(v) for k, v in sorted(by_suppressor.items())
            },
            "active_suppressors": sorted(by_suppressor.keys()),
        }

    def filter_candidates(
        self,
        candidates: List[Any],  # List[RootCauseCandidate]
    ) -> List[Any]:
        """Filter candidates to remove suppressed ones.

        Args:
            candidates: List of RootCauseCandidate

        Returns:
            Filtered list with suppressed candidates removed
        """
        if not self._config.enabled or not self._config.suppress_child_incidents:
            return candidates

        return [c for c in candidates if c.node_id not in self._suppressed_nodes]

    def filter_alerts(
        self,
        signal_ids: List[str],
    ) -> List[str]:
        """Filter signal IDs to remove suppressed ones.

        Args:
            signal_ids: List of signal IDs

        Returns:
            Filtered list with suppressed signals removed
        """
        if not self._config.enabled or not self._config.suppress_child_signals:
            return signal_ids

        return [s for s in signal_ids if s not in self._suppressed_nodes]

    def reset(self) -> None:
        """Reset suppression state."""
        self._suppressed_nodes.clear()


def get_default_suppression_config() -> SuppressionConfig:
    """Get default suppression configuration."""
    return SuppressionConfig()


def create_suppression_manager(
    topology_snapshot: TopologySnapshot,
    topology_index: TopologyIndex,
    incident_tracker: NodeIncidentTracker,
    config_dict: Optional[Dict[str, Any]] = None,
) -> SuppressionManager:
    """Create suppression manager from configuration dictionary.

    Args:
        topology_snapshot: Topology snapshot
        topology_index: Topology index
        incident_tracker: Node incident tracker
        config_dict: Optional configuration dictionary

    Returns:
        Configured SuppressionManager
    """
    if config_dict is None:
        config = get_default_suppression_config()
    else:
        config = SuppressionConfig(
            enabled=config_dict.get("enabled", True),
            suppress_child_signals=config_dict.get("suppress_child_signals", True),
            suppress_child_incidents=config_dict.get("suppress_child_incidents", True),
            suppressed_types=set(
                config_dict.get("suppressed_types", ["signal", "rtu", "poll_group"])
            ),
            suppressor_types=set(
                config_dict.get("suppressor_types", ["comms_domain", "poll_group", "rtu"])
            ),
            min_suppressor_confidence=config_dict.get("min_suppressor_confidence", 0.5),
        )

    return SuppressionManager(
        topology_snapshot,
        topology_index,
        incident_tracker,
        config,
    )
