"""Topology index for comms descendant signal counts."""

from __future__ import annotations

from typing import Dict, List

from sqe.topology.model import NodeType, TopologySnapshot


class CommsTopologyIndex:
    """Precompute descendant signal counts for comms nodes."""

    def __init__(self, snapshot: TopologySnapshot) -> None:
        self._snapshot = snapshot
        self._counts: Dict[str, int] = {}
        self._initialize_counts()

    def _initialize_counts(self) -> None:
        postorder: List[str] = []
        roots = self._snapshot.get_root_nodes()
        stack: List[tuple[str, bool]] = []
        for root in reversed(roots):
            stack.append((root, False))

        while stack:
            node_id, visited = stack.pop()
            if visited:
                postorder.append(node_id)
                continue
            stack.append((node_id, True))
            children = self._snapshot.get_children(node_id)
            for child_id in reversed(children):
                stack.append((child_id, False))

        for node_id in postorder:
            node = self._snapshot.get_node(node_id)
            if node is None:
                self._counts[node_id] = 0
                continue
            if node.node_type == NodeType.SIGNAL:
                self._counts[node_id] = 1
            else:
                total = 0
                for child_id in self._snapshot.get_children(node_id):
                    total += self._counts.get(child_id, 0)
                self._counts[node_id] = total

    def descendant_signal_count(self, node_id: str) -> int:
        """Return descendant signal count for a node."""
        return int(self._counts.get(node_id, 0))

    def counts_by_type(self, node_type: str) -> Dict[str, int]:
        """Return mapping of node_id to counts for a node type."""
        normalized = node_type.lower()
        type_map = {
            "comms_domain": NodeType.COMMS_DOMAIN,
            "poll_group": NodeType.POLL_GROUP,
            "rtu": NodeType.RTU,
            "signal": NodeType.SIGNAL,
        }
        if normalized not in type_map:
            raise ValueError(f"Unknown node type: {node_type}")
        target = type_map[normalized]
        return {
            node_id: self._counts.get(node_id, 0)
            for node_id in self._snapshot.get_nodes_by_type(target)
        }
