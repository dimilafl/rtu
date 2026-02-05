"""Topology data model for node hierarchy representation.

Provides deterministic, immutable topology snapshots with stable ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Union


class NodeType(Enum):
    """Node types in the topology hierarchy (ordered from root to leaf)."""

    COMMS_DOMAIN = "comms_domain"
    POLL_GROUP = "poll_group"
    RTU = "rtu"
    SIGNAL = "signal"

    def __lt__(self, other: "NodeType") -> bool:
        """Enable sorting by hierarchy level (root first)."""
        order = [
            NodeType.COMMS_DOMAIN,
            NodeType.POLL_GROUP,
            NodeType.RTU,
            NodeType.SIGNAL,
        ]
        return order.index(self) < order.index(other)


# Type alias for node attribute values
AttrValue = Union[str, int, float, bool]


@dataclass(frozen=True)
class Node:
    """A node in the topology hierarchy.

    Attributes:
        node_id: Unique identifier for the node
        node_type: Type of node (SIGNAL, RTU, POLL_GROUP, COMMS_DOMAIN)
        attrs: Optional attributes dict (bounded set of types)
    """

    node_id: str
    node_type: NodeType
    attrs: Dict[str, AttrValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate node attributes."""
        if not self.node_id:
            raise ValueError("node_id cannot be empty")
        for key, value in self.attrs.items():
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    f"Attribute {key} has invalid type {type(value).__name__}; "
                    "must be str, int, float, or bool"
                )


@dataclass(frozen=True)
class Edge:
    """A parent-child edge in the topology hierarchy.

    Attributes:
        parent_id: Node ID of the parent
        child_id: Node ID of the child
    """

    parent_id: str
    child_id: str


@dataclass
class TopologySnapshot:
    """Immutable snapshot of topology with precomputed indexes.

    All collections are sorted deterministically for stable iteration.

    Attributes:
        nodes: Dict mapping node_id to Node
        children: Dict mapping parent_id to sorted list of child_ids
        parent: Dict mapping child_id to parent_id
        version_hash: SHA256 hash of canonicalized topology
        node_order: Stable ordering of all node_ids by (type priority, id)
    """

    nodes: Dict[str, Node]
    children: Dict[str, List[str]]
    parent: Dict[str, str]
    version_hash: str
    node_order: List[str]

    def get_node(self, node_id: str) -> Optional[Node]:
        """Get node by ID."""
        return self.nodes.get(node_id)

    def get_children(self, node_id: str) -> List[str]:
        """Get sorted list of children for a node."""
        return self.children.get(node_id, [])

    def get_parent(self, node_id: str) -> Optional[str]:
        """Get parent node ID, or None if root/orphan."""
        return self.parent.get(node_id)

    def get_nodes_by_type(self, node_type: NodeType) -> List[str]:
        """Get all node IDs of a given type in stable order."""
        return [
            node_id
            for node_id in self.node_order
            if self.nodes[node_id].node_type == node_type
        ]

    def get_root_nodes(self) -> List[str]:
        """Get nodes with no parent (roots) in stable order."""
        return [
            node_id
            for node_id in self.node_order
            if node_id not in self.parent
        ]

    def get_leaf_nodes(self) -> List[str]:
        """Get nodes with no children (leaves) in stable order."""
        return [
            node_id
            for node_id in self.node_order
            if node_id not in self.children or len(self.children[node_id]) == 0
        ]

    def __len__(self) -> int:
        """Return number of nodes."""
        return len(self.nodes)
