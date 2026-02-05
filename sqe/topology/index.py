"""Topology index for fast lookups and ancestor/descendant queries.

Precomputes all traversal paths at load time to avoid O(n) per-scan traversals.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Optional, Set

from sqe.topology.model import NodeType, TopologySnapshot


class TopologyIndex:
    """Precomputed index for fast topology queries.

    All maps are computed once at construction time.
    Per-scan operations are O(1) dictionary lookups.
    """

    def __init__(self, snapshot: TopologySnapshot) -> None:
        """Build index from topology snapshot.

        Args:
            snapshot: Validated topology snapshot
        """
        self._snapshot = snapshot

        # Direct mappings by type
        self._signal_to_rtu: Dict[str, str] = {}
        self._rtu_to_poll_group: Dict[str, str] = {}
        self._poll_group_to_comms_domain: Dict[str, str] = {}

        # Precomputed descendants (signals under each node)
        self._descendants: Dict[str, FrozenSet[str]] = {}
        self._ancestors: Dict[str, List[str]] = {}  # Ordered root-to-leaf

        # Build all indexes
        self._build_type_maps()
        self._build_descendant_maps()
        self._build_ancestor_maps()

    @property
    def snapshot(self) -> TopologySnapshot:
        """Access underlying topology snapshot."""
        return self._snapshot

    def _build_type_maps(self) -> None:
        """Build direct parent maps for each node type layer."""
        for node_id, node in self._snapshot.nodes.items():
            parent_id = self._snapshot.get_parent(node_id)
            if parent_id is None:
                continue

            parent_node = self._snapshot.get_node(parent_id)
            if parent_node is None:
                continue

            if node.node_type == NodeType.SIGNAL:
                if parent_node.node_type == NodeType.RTU:
                    self._signal_to_rtu[node_id] = parent_id
            elif node.node_type == NodeType.RTU:
                if parent_node.node_type == NodeType.POLL_GROUP:
                    self._rtu_to_poll_group[node_id] = parent_id
            elif node.node_type == NodeType.POLL_GROUP:
                if parent_node.node_type == NodeType.COMMS_DOMAIN:
                    self._poll_group_to_comms_domain[node_id] = parent_id

    def _build_descendant_maps(self) -> None:
        """Precompute all descendant signals for each node."""
        # Process in reverse order (leaves first) for efficiency
        for node_id in reversed(self._snapshot.node_order):
            node = self._snapshot.get_node(node_id)
            if node is None:
                continue

            children = self._snapshot.get_children(node_id)
            if not children:
                # Leaf node - descendants is just itself if it's a signal
                if node.node_type == NodeType.SIGNAL:
                    self._descendants[node_id] = frozenset([node_id])
                else:
                    self._descendants[node_id] = frozenset()
            else:
                # Internal node - union of children's descendants
                desc: Set[str] = set()
                for child_id in children:
                    desc.update(self._descendants.get(child_id, frozenset()))
                self._descendants[node_id] = frozenset(desc)

    def _build_ancestor_maps(self) -> None:
        """Precompute ancestor chains for each node (root to node order)."""
        for node_id in self._snapshot.node_order:
            ancestors: List[str] = []
            current = self._snapshot.get_parent(node_id)
            while current is not None:
                ancestors.append(current)
                current = self._snapshot.get_parent(current)
            # Reverse to get root-to-parent order
            ancestors.reverse()
            self._ancestors[node_id] = ancestors

    def signal_to_rtu(self, signal_id: str) -> Optional[str]:
        """Get RTU parent for a signal."""
        return self._signal_to_rtu.get(signal_id)

    def rtu_to_poll_group(self, rtu_id: str) -> Optional[str]:
        """Get poll group parent for an RTU."""
        return self._rtu_to_poll_group.get(rtu_id)

    def poll_group_to_comms_domain(self, poll_group_id: str) -> Optional[str]:
        """Get comms domain parent for a poll group."""
        return self._poll_group_to_comms_domain.get(poll_group_id)

    def get_descendants(self, node_id: str) -> FrozenSet[str]:
        """Get all descendant signal IDs for a node (precomputed)."""
        return self._descendants.get(node_id, frozenset())

    def get_ancestors(self, node_id: str) -> List[str]:
        """Get ancestor chain from root to parent (precomputed)."""
        return self._ancestors.get(node_id, [])

    def get_ancestor_at_type(
        self,
        node_id: str,
        node_type: NodeType,
    ) -> Optional[str]:
        """Get ancestor of specific type for a node."""
        for ancestor_id in self._ancestors.get(node_id, []):
            ancestor = self._snapshot.get_node(ancestor_id)
            if ancestor and ancestor.node_type == node_type:
                return ancestor_id
        return None

    def get_signals_for_rtu(self, rtu_id: str) -> List[str]:
        """Get all signal IDs under an RTU (sorted)."""
        return sorted(self._descendants.get(rtu_id, frozenset()))

    def get_signals_for_poll_group(self, poll_group_id: str) -> List[str]:
        """Get all signal IDs under a poll group (sorted)."""
        return sorted(self._descendants.get(poll_group_id, frozenset()))

    def get_signals_for_comms_domain(self, comms_domain_id: str) -> List[str]:
        """Get all signal IDs under a comms domain (sorted)."""
        return sorted(self._descendants.get(comms_domain_id, frozenset()))

    def get_rtus_for_poll_group(self, poll_group_id: str) -> List[str]:
        """Get RTU IDs directly under a poll group (sorted)."""
        children = self._snapshot.get_children(poll_group_id)
        return [
            c for c in children
            if self._snapshot.nodes.get(c, None)
            and self._snapshot.nodes[c].node_type == NodeType.RTU
        ]

    def get_poll_groups_for_comms_domain(self, comms_domain_id: str) -> List[str]:
        """Get poll group IDs directly under a comms domain (sorted)."""
        children = self._snapshot.get_children(comms_domain_id)
        return [
            c for c in children
            if self._snapshot.nodes.get(c, None)
            and self._snapshot.nodes[c].node_type == NodeType.POLL_GROUP
        ]

    def get_siblings(self, node_id: str) -> List[str]:
        """Get sibling node IDs (sorted, excluding self)."""
        parent_id = self._snapshot.get_parent(node_id)
        if parent_id is None:
            # Root nodes - other roots of same type
            node = self._snapshot.get_node(node_id)
            if node is None:
                return []
            return [
                n_id for n_id in self._snapshot.get_root_nodes()
                if n_id != node_id
                and self._snapshot.nodes[n_id].node_type == node.node_type
            ]
        # Non-root - siblings are other children of same parent
        siblings = self._snapshot.get_children(parent_id)
        return [s for s in siblings if s != node_id]

    def count_descendants(self, node_id: str) -> int:
        """Count number of descendant signals for a node."""
        return len(self._descendants.get(node_id, frozenset()))

    def get_all_nodes_by_type(self, node_type: NodeType) -> List[str]:
        """Get all node IDs of a type (sorted)."""
        return self._snapshot.get_nodes_by_type(node_type)
