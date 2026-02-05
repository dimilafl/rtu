"""Tests for CommsTopologyIndex."""

from sqe.comms.topology_index import CommsTopologyIndex
from sqe.topology.loader import load_topology_dict


def _make_snapshot():
    return load_topology_dict(
        {
            "nodes": [
                {"id": "D", "type": "comms_domain"},
                {"id": "P", "type": "poll_group"},
                {"id": "R1", "type": "rtu"},
                {"id": "R2", "type": "rtu"},
                {"id": "s1", "type": "signal"},
                {"id": "s2", "type": "signal"},
                {"id": "s3", "type": "signal"},
            ],
            "edges": [
                {"parent": "D", "child": "P"},
                {"parent": "P", "child": "R1"},
                {"parent": "P", "child": "R2"},
                {"parent": "R1", "child": "s1"},
                {"parent": "R1", "child": "s2"},
                {"parent": "R2", "child": "s3"},
            ],
        }
    )


def test_descendant_signal_counts():
    snapshot = _make_snapshot()
    index = CommsTopologyIndex(snapshot)
    assert index.descendant_signal_count("D") == 3
    assert index.descendant_signal_count("P") == 3
    assert index.descendant_signal_count("R1") == 2
    assert index.descendant_signal_count("R2") == 1


def test_counts_are_stable_across_construction():
    snapshot = _make_snapshot()
    index_one = CommsTopologyIndex(snapshot)
    index_two = CommsTopologyIndex(snapshot)
    assert index_one.descendant_signal_count("D") == index_two.descendant_signal_count("D")
    assert index_one.descendant_signal_count("P") == index_two.descendant_signal_count("P")
    assert index_one.descendant_signal_count("R1") == index_two.descendant_signal_count("R1")
    assert index_one.descendant_signal_count("R2") == index_two.descendant_signal_count("R2")
