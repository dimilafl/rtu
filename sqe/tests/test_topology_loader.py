"""Tests for topology loader and model."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sqe.topology.model import Node, NodeType, TopologySnapshot
from sqe.topology.loader import (
    TopologyValidationError,
    load_topology_dict,
    load_topology_yaml,
)
from sqe.topology.index import TopologyIndex


@pytest.fixture
def example_topology_dict():
    """Simple test topology with 1 comms_domain, 2 poll_groups, 3 RTUs, 6 signals."""
    return {
        "nodes": [
            {"id": "cd1", "type": "comms_domain", "attrs": {"region": "north"}},
            {"id": "pg1", "type": "poll_group", "attrs": {"interval": 100}},
            {"id": "pg2", "type": "poll_group", "attrs": {"interval": 500}},
            {"id": "rtu1", "type": "rtu", "attrs": {"ip": "192.168.1.1"}},
            {"id": "rtu2", "type": "rtu", "attrs": {"ip": "192.168.1.2"}},
            {"id": "rtu3", "type": "rtu", "attrs": {"ip": "192.168.1.3"}},
            {"id": "sig1", "type": "signal", "attrs": {"tag": "T1"}},
            {"id": "sig2", "type": "signal", "attrs": {"tag": "T2"}},
            {"id": "sig3", "type": "signal", "attrs": {"tag": "T3"}},
            {"id": "sig4", "type": "signal", "attrs": {"tag": "T4"}},
            {"id": "sig5", "type": "signal", "attrs": {"tag": "T5"}},
            {"id": "sig6", "type": "signal", "attrs": {"tag": "T6"}},
        ],
        "edges": [
            {"parent": "cd1", "child": "pg1"},
            {"parent": "cd1", "child": "pg2"},
            {"parent": "pg1", "child": "rtu1"},
            {"parent": "pg1", "child": "rtu2"},
            {"parent": "pg2", "child": "rtu3"},
            {"parent": "rtu1", "child": "sig1"},
            {"parent": "rtu1", "child": "sig2"},
            {"parent": "rtu2", "child": "sig3"},
            {"parent": "rtu2", "child": "sig4"},
            {"parent": "rtu3", "child": "sig5"},
            {"parent": "rtu3", "child": "sig6"},
        ],
    }


class TestTopologyLoader:
    """Test topology loading and validation."""

    def test_load_from_dict(self, example_topology_dict):
        """Test loading topology from dictionary."""
        snapshot = load_topology_dict(example_topology_dict)

        assert len(snapshot.nodes) == 12
        assert "cd1" in snapshot.nodes
        assert snapshot.nodes["cd1"].node_type == NodeType.COMMS_DOMAIN

    def test_version_hash_stable(self, example_topology_dict):
        """Test that version hash is deterministic."""
        snapshot1 = load_topology_dict(example_topology_dict)
        snapshot2 = load_topology_dict(example_topology_dict)

        assert snapshot1.version_hash == snapshot2.version_hash
        assert len(snapshot1.version_hash) == 64  # SHA256 hex

    def test_children_lists_sorted(self, example_topology_dict):
        """Test that children lists are sorted deterministically."""
        snapshot = load_topology_dict(example_topology_dict)

        # cd1 has pg1, pg2 as children
        assert snapshot.get_children("cd1") == ["pg1", "pg2"]

        # pg1 has rtu1, rtu2 as children
        assert snapshot.get_children("pg1") == ["rtu1", "rtu2"]

        # rtu1 has sig1, sig2 as children
        assert snapshot.get_children("rtu1") == ["sig1", "sig2"]

    def test_node_order_stable(self, example_topology_dict):
        """Test that node_order is stable and sorted by type then id."""
        snapshot = load_topology_dict(example_topology_dict)

        # Should be sorted by type priority (comms_domain first, then poll_group, etc.)
        expected_order = [
            "cd1",  # comms_domain
            "pg1", "pg2",  # poll_groups
            "rtu1", "rtu2", "rtu3",  # rtus
            "sig1", "sig2", "sig3", "sig4", "sig5", "sig6",  # signals
        ]
        assert snapshot.node_order == expected_order

    def test_parent_child_relationships(self, example_topology_dict):
        """Test parent-child relationship lookups."""
        snapshot = load_topology_dict(example_topology_dict)

        assert snapshot.get_parent("pg1") == "cd1"
        assert snapshot.get_parent("rtu1") == "pg1"
        assert snapshot.get_parent("sig1") == "rtu1"
        assert snapshot.get_parent("cd1") is None  # root

    def test_load_from_yaml_file(self, example_topology_dict):
        """Test loading from YAML file."""
        import yaml

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(example_topology_dict, f)
            f.flush()

            snapshot = load_topology_yaml(f.name)

        assert len(snapshot.nodes) == 12
        assert snapshot.version_hash  # Should have hash

    def test_duplicate_node_id_raises(self):
        """Test that duplicate node IDs raise error."""
        data = {
            "nodes": [
                {"id": "n1", "type": "signal"},
                {"id": "n1", "type": "rtu"},
            ],
            "edges": [],
        }
        with pytest.raises(TopologyValidationError, match="Duplicate node id"):
            load_topology_dict(data, allow_orphan_signals=True)

    def test_unknown_parent_raises(self):
        """Test that edges referencing unknown nodes raise error."""
        data = {
            "nodes": [
                {"id": "rtu1", "type": "rtu"},
            ],
            "edges": [
                {"parent": "unknown", "child": "rtu1"},
            ],
        }
        with pytest.raises(TopologyValidationError, match="unknown parent"):
            load_topology_dict(data)

    def test_multiple_parents_raises(self):
        """Test that child with multiple parents raises error."""
        data = {
            "nodes": [
                {"id": "pg1", "type": "poll_group"},
                {"id": "pg2", "type": "poll_group"},
                {"id": "rtu1", "type": "rtu"},
            ],
            "edges": [
                {"parent": "pg1", "child": "rtu1"},
                {"parent": "pg2", "child": "rtu1"},
            ],
        }
        with pytest.raises(TopologyValidationError, match="multiple parents"):
            load_topology_dict(data)

    def test_signal_without_rtu_parent_raises(self):
        """Test that signal without RTU parent raises error."""
        data = {
            "nodes": [
                {"id": "pg1", "type": "poll_group"},
                {"id": "sig1", "type": "signal"},
            ],
            "edges": [
                {"parent": "pg1", "child": "sig1"},
            ],
        }
        with pytest.raises(TopologyValidationError, match="not an RTU"):
            load_topology_dict(data)

    def test_orphan_signal_allowed_with_flag(self):
        """Test that orphan signals allowed when flag is set."""
        data = {
            "nodes": [
                {"id": "sig1", "type": "signal"},
            ],
            "edges": [],
        }
        snapshot = load_topology_dict(data, allow_orphan_signals=True)
        assert "sig1" in snapshot.nodes

    def test_invalid_node_type_raises(self):
        """Test that invalid node type raises error."""
        data = {
            "nodes": [
                {"id": "n1", "type": "invalid_type"},
            ],
            "edges": [],
        }
        with pytest.raises(TopologyValidationError, match="Unknown node type"):
            load_topology_dict(data)

    def test_node_attrs_validation(self):
        """Test that node attributes are validated."""
        data = {
            "nodes": [
                {"id": "sig1", "type": "signal", "attrs": {"valid_str": "hello"}},
                {"id": "rtu1", "type": "rtu", "attrs": {"valid_int": 42}},
            ],
            "edges": [
                {"parent": "rtu1", "child": "sig1"},
            ],
        }
        snapshot = load_topology_dict(data)
        assert snapshot.nodes["sig1"].attrs["valid_str"] == "hello"
        assert snapshot.nodes["rtu1"].attrs["valid_int"] == 42


class TestTopologyIndex:
    """Test topology index precomputation."""

    def test_signal_to_rtu_mapping(self, example_topology_dict):
        """Test signal to RTU mapping."""
        snapshot = load_topology_dict(example_topology_dict)
        index = TopologyIndex(snapshot)

        assert index.signal_to_rtu("sig1") == "rtu1"
        assert index.signal_to_rtu("sig2") == "rtu1"
        assert index.signal_to_rtu("sig3") == "rtu2"
        assert index.signal_to_rtu("sig5") == "rtu3"
        assert index.signal_to_rtu("unknown") is None

    def test_rtu_to_poll_group_mapping(self, example_topology_dict):
        """Test RTU to poll group mapping."""
        snapshot = load_topology_dict(example_topology_dict)
        index = TopologyIndex(snapshot)

        assert index.rtu_to_poll_group("rtu1") == "pg1"
        assert index.rtu_to_poll_group("rtu2") == "pg1"
        assert index.rtu_to_poll_group("rtu3") == "pg2"
        assert index.rtu_to_poll_group("unknown") is None

    def test_poll_group_to_comms_domain_mapping(self, example_topology_dict):
        """Test poll group to comms domain mapping."""
        snapshot = load_topology_dict(example_topology_dict)
        index = TopologyIndex(snapshot)

        assert index.poll_group_to_comms_domain("pg1") == "cd1"
        assert index.poll_group_to_comms_domain("pg2") == "cd1"
        assert index.poll_group_to_comms_domain("unknown") is None

    def test_descendants_precomputed(self, example_topology_dict):
        """Test descendant signals are precomputed."""
        snapshot = load_topology_dict(example_topology_dict)
        index = TopologyIndex(snapshot)

        # cd1 should have all 6 signals as descendants
        cd1_desc = index.get_descendants("cd1")
        assert len(cd1_desc) == 6
        assert "sig1" in cd1_desc
        assert "sig6" in cd1_desc

        # pg1 should have sig1-4
        pg1_desc = index.get_descendants("pg1")
        assert len(pg1_desc) == 4
        assert "sig1" in pg1_desc
        assert "sig5" not in pg1_desc

        # rtu1 should have sig1, sig2
        rtu1_desc = index.get_descendants("rtu1")
        assert rtu1_desc == frozenset(["sig1", "sig2"])

    def test_ancestors_precomputed(self, example_topology_dict):
        """Test ancestor chains are precomputed."""
        snapshot = load_topology_dict(example_topology_dict)
        index = TopologyIndex(snapshot)

        # sig1's ancestors: cd1 -> pg1 -> rtu1
        sig1_ancestors = index.get_ancestors("sig1")
        assert sig1_ancestors == ["cd1", "pg1", "rtu1"]

        # rtu1's ancestors: cd1 -> pg1
        rtu1_ancestors = index.get_ancestors("rtu1")
        assert rtu1_ancestors == ["cd1", "pg1"]

        # cd1 has no ancestors
        cd1_ancestors = index.get_ancestors("cd1")
        assert cd1_ancestors == []

    def test_get_ancestor_at_type(self, example_topology_dict):
        """Test getting ancestor of specific type."""
        snapshot = load_topology_dict(example_topology_dict)
        index = TopologyIndex(snapshot)

        assert index.get_ancestor_at_type("sig1", NodeType.RTU) == "rtu1"
        assert index.get_ancestor_at_type("sig1", NodeType.POLL_GROUP) == "pg1"
        assert index.get_ancestor_at_type("sig1", NodeType.COMMS_DOMAIN) == "cd1"
        assert index.get_ancestor_at_type("sig1", NodeType.SIGNAL) is None

    def test_get_siblings(self, example_topology_dict):
        """Test getting sibling nodes."""
        snapshot = load_topology_dict(example_topology_dict)
        index = TopologyIndex(snapshot)

        # pg1 and pg2 are siblings under cd1
        assert index.get_siblings("pg1") == ["pg2"]
        assert index.get_siblings("pg2") == ["pg1"]

        # rtu1 and rtu2 are siblings under pg1
        assert index.get_siblings("rtu1") == ["rtu2"]

        # sig1 and sig2 are siblings under rtu1
        assert index.get_siblings("sig1") == ["sig2"]

    def test_get_signals_for_rtu(self, example_topology_dict):
        """Test getting signals for RTU."""
        snapshot = load_topology_dict(example_topology_dict)
        index = TopologyIndex(snapshot)

        assert index.get_signals_for_rtu("rtu1") == ["sig1", "sig2"]
        assert index.get_signals_for_rtu("rtu3") == ["sig5", "sig6"]

    def test_count_descendants(self, example_topology_dict):
        """Test counting descendants."""
        snapshot = load_topology_dict(example_topology_dict)
        index = TopologyIndex(snapshot)

        assert index.count_descendants("cd1") == 6
        assert index.count_descendants("pg1") == 4
        assert index.count_descendants("pg2") == 2
        assert index.count_descendants("rtu1") == 2
        assert index.count_descendants("sig1") == 1  # Signal is its own descendant


class TestTopologyModel:
    """Test topology model dataclasses."""

    def test_node_creation(self):
        """Test Node dataclass creation."""
        node = Node(
            node_id="test",
            node_type=NodeType.SIGNAL,
            attrs={"tag": "T1", "units": "degC"},
        )
        assert node.node_id == "test"
        assert node.node_type == NodeType.SIGNAL
        assert node.attrs["tag"] == "T1"

    def test_node_empty_id_raises(self):
        """Test that empty node_id raises error."""
        with pytest.raises(ValueError, match="cannot be empty"):
            Node(node_id="", node_type=NodeType.SIGNAL)

    def test_node_type_ordering(self):
        """Test NodeType enum ordering."""
        assert NodeType.COMMS_DOMAIN < NodeType.POLL_GROUP
        assert NodeType.POLL_GROUP < NodeType.RTU
        assert NodeType.RTU < NodeType.SIGNAL

    def test_snapshot_helper_methods(self, example_topology_dict):
        """Test TopologySnapshot helper methods."""
        snapshot = load_topology_dict(example_topology_dict)

        # get_nodes_by_type
        signals = snapshot.get_nodes_by_type(NodeType.SIGNAL)
        assert len(signals) == 6
        assert signals == sorted(signals)  # Should be sorted

        rtus = snapshot.get_nodes_by_type(NodeType.RTU)
        assert len(rtus) == 3

        # get_root_nodes
        roots = snapshot.get_root_nodes()
        assert roots == ["cd1"]

        # get_leaf_nodes
        leaves = snapshot.get_leaf_nodes()
        assert len(leaves) == 6
        assert all(snapshot.nodes[l].node_type == NodeType.SIGNAL for l in leaves)


def test_loads_example_topology_file():
    """Test loading the example topology file."""
    example_path = Path(__file__).parent.parent / "config" / "topology_example.yaml"
    if example_path.exists():
        snapshot = load_topology_yaml(str(example_path))
        assert len(snapshot.nodes) > 0
        assert snapshot.version_hash
        # Verify stable hash
        snapshot2 = load_topology_yaml(str(example_path))
        assert snapshot.version_hash == snapshot2.version_hash
