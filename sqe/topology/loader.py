"""Topology loader from YAML configuration.

Provides deterministic loading and validation of topology snapshots.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from sqe.topology.model import (
    AttrValue,
    Edge,
    Node,
    NodeType,
    TopologySnapshot,
)


class TopologyValidationError(Exception):
    """Raised when topology validation fails."""

    pass


def _parse_node_type(type_str: str) -> NodeType:
    """Parse node type string to enum."""
    type_map = {
        "signal": NodeType.SIGNAL,
        "rtu": NodeType.RTU,
        "poll_group": NodeType.POLL_GROUP,
        "comms_domain": NodeType.COMMS_DOMAIN,
    }
    normalized = type_str.lower().strip()
    if normalized not in type_map:
        raise TopologyValidationError(
            f"Unknown node type '{type_str}'; "
            f"must be one of {list(type_map.keys())}"
        )
    return type_map[normalized]


def _validate_attrs(attrs: Dict[str, Any], node_id: str) -> Dict[str, AttrValue]:
    """Validate and convert node attributes."""
    if attrs is None:
        return {}
    result: Dict[str, AttrValue] = {}
    for key, value in attrs.items():
        if not isinstance(key, str):
            raise TopologyValidationError(
                f"Node {node_id}: attribute key must be string, got {type(key).__name__}"
            )
        if not isinstance(value, (str, int, float, bool)):
            raise TopologyValidationError(
                f"Node {node_id}: attribute '{key}' has invalid type {type(value).__name__}; "
                "must be str, int, float, or bool"
            )
        result[key] = value
    return result


def _canonicalize_topology(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, str]],
) -> str:
    """Create canonical JSON representation for hashing."""
    # Sort nodes by (type, id) for canonical ordering
    sorted_nodes = sorted(
        nodes,
        key=lambda n: (n.get("type", ""), n.get("id", "")),
    )
    # Sort edges by (parent, child)
    sorted_edges = sorted(
        edges,
        key=lambda e: (e.get("parent", ""), e.get("child", "")),
    )
    canonical = {
        "nodes": sorted_nodes,
        "edges": sorted_edges,
    }
    return json.dumps(canonical, separators=(",", ":"), sort_keys=True)


def _compute_version_hash(canonical_json: str) -> str:
    """Compute SHA256 hash of canonical topology."""
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def load_topology_yaml(
    path: str,
    *,
    allow_orphan_signals: bool = False,
    node_type_priority: Optional[List[str]] = None,
) -> TopologySnapshot:
    """Load topology from YAML file.

    Args:
        path: Path to YAML topology file
        allow_orphan_signals: If False, signals without RTU parent raise error
        node_type_priority: Custom type ordering for node_order (default: root-to-leaf)

    Returns:
        TopologySnapshot with validated and indexed topology

    Raises:
        TopologyValidationError: If topology is invalid
        FileNotFoundError: If file doesn't exist
    """
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Topology file not found: {path}")

    with open(path_obj, "r") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise TopologyValidationError("Empty topology file")

    return load_topology_dict(
        data,
        allow_orphan_signals=allow_orphan_signals,
        node_type_priority=node_type_priority,
    )


def load_topology_dict(
    data: Dict[str, Any],
    *,
    allow_orphan_signals: bool = False,
    node_type_priority: Optional[List[str]] = None,
) -> TopologySnapshot:
    """Load topology from dictionary (parsed YAML/JSON).

    Args:
        data: Dictionary with 'nodes' and 'edges' keys
        allow_orphan_signals: If False, signals without RTU parent raise error
        node_type_priority: Custom type ordering for node_order

    Returns:
        TopologySnapshot with validated and indexed topology
    """
    # Parse nodes
    raw_nodes = data.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise TopologyValidationError("'nodes' must be a list")

    nodes: Dict[str, Node] = {}
    seen_ids: Set[str] = set()

    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            raise TopologyValidationError(f"Node must be a dict, got {type(raw_node)}")

        node_id = raw_node.get("id")
        if not node_id:
            raise TopologyValidationError("Node missing 'id' field")
        if not isinstance(node_id, str):
            node_id = str(node_id)

        if node_id in seen_ids:
            raise TopologyValidationError(f"Duplicate node id: {node_id}")
        seen_ids.add(node_id)

        type_str = raw_node.get("type")
        if not type_str:
            raise TopologyValidationError(f"Node {node_id} missing 'type' field")

        node_type = _parse_node_type(type_str)
        attrs = _validate_attrs(raw_node.get("attrs", {}), node_id)

        nodes[node_id] = Node(
            node_id=node_id,
            node_type=node_type,
            attrs=attrs,
        )

    # Parse edges
    raw_edges = data.get("edges", [])
    if not isinstance(raw_edges, list):
        raise TopologyValidationError("'edges' must be a list")

    edges: List[Edge] = []
    children: Dict[str, List[str]] = {}
    parent: Dict[str, str] = {}

    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            raise TopologyValidationError(f"Edge must be a dict, got {type(raw_edge)}")

        parent_id = raw_edge.get("parent")
        child_id = raw_edge.get("child")

        if not parent_id or not child_id:
            raise TopologyValidationError(
                f"Edge missing 'parent' or 'child': {raw_edge}"
            )

        if not isinstance(parent_id, str):
            parent_id = str(parent_id)
        if not isinstance(child_id, str):
            child_id = str(child_id)

        # Validate references
        if parent_id not in nodes:
            raise TopologyValidationError(
                f"Edge references unknown parent: {parent_id}"
            )
        if child_id not in nodes:
            raise TopologyValidationError(
                f"Edge references unknown child: {child_id}"
            )

        # Check for multiple parents
        if child_id in parent:
            raise TopologyValidationError(
                f"Node {child_id} has multiple parents: "
                f"{parent[child_id]} and {parent_id}"
            )

        edges.append(Edge(parent_id=parent_id, child_id=child_id))
        parent[child_id] = parent_id

        if parent_id not in children:
            children[parent_id] = []
        children[parent_id].append(child_id)

    # Sort children lists for determinism
    for parent_id in children:
        children[parent_id] = sorted(children[parent_id])

    # Validate signals have RTU parent (unless orphans allowed)
    if not allow_orphan_signals:
        for node_id, node in nodes.items():
            if node.node_type == NodeType.SIGNAL:
                if node_id not in parent:
                    raise TopologyValidationError(
                        f"Signal {node_id} has no parent RTU "
                        "(set allow_orphan_signals=True to allow)"
                    )
                parent_node = nodes.get(parent[node_id])
                if parent_node and parent_node.node_type != NodeType.RTU:
                    raise TopologyValidationError(
                        f"Signal {node_id} parent {parent[node_id]} "
                        f"is not an RTU (is {parent_node.node_type.value})"
                    )

    # Build node_order with stable sorting
    if node_type_priority is None:
        type_order = [
            NodeType.COMMS_DOMAIN,
            NodeType.POLL_GROUP,
            NodeType.RTU,
            NodeType.SIGNAL,
        ]
    else:
        type_order = [_parse_node_type(t) for t in node_type_priority]

    def sort_key(node_id: str) -> tuple:
        node = nodes[node_id]
        try:
            type_idx = type_order.index(node.node_type)
        except ValueError:
            type_idx = len(type_order)
        return (type_idx, node_id)

    node_order = sorted(nodes.keys(), key=sort_key)

    # Compute version hash from canonical representation
    raw_nodes_for_hash = [
        {
            "id": n.node_id,
            "type": n.node_type.value,
            "attrs": dict(sorted(n.attrs.items())),
        }
        for n in nodes.values()
    ]
    raw_edges_for_hash = [
        {"parent": e.parent_id, "child": e.child_id}
        for e in edges
    ]
    canonical_json = _canonicalize_topology(raw_nodes_for_hash, raw_edges_for_hash)
    version_hash = _compute_version_hash(canonical_json)

    return TopologySnapshot(
        nodes=nodes,
        children=children,
        parent=parent,
        version_hash=version_hash,
        node_order=node_order,
    )
