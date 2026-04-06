"""Tests for RCA evidence aggregation."""

from __future__ import annotations

import pytest

from sqe.topology.loader import load_topology_dict
from sqe.topology.index import TopologyIndex
from sqe.rca.schema import LeafObservation
from sqe.rca.evidence import (
    build_leaf_observations,
    aggregate_node_evidence,
    select_representative_signals,
)
from sqe.rca.state import RCAState


@pytest.fixture
def test_topology():
    """Test topology: 1 comms_domain, 2 poll_groups, 4 RTUs, 8 signals."""
    data = {
        "nodes": [
            {"id": "cd1", "type": "comms_domain"},
            {"id": "pg1", "type": "poll_group"},
            {"id": "pg2", "type": "poll_group"},
            {"id": "rtu1", "type": "rtu"},
            {"id": "rtu2", "type": "rtu"},
            {"id": "rtu3", "type": "rtu"},
            {"id": "rtu4", "type": "rtu"},
            {"id": "sig1", "type": "signal"},
            {"id": "sig2", "type": "signal"},
            {"id": "sig3", "type": "signal"},
            {"id": "sig4", "type": "signal"},
            {"id": "sig5", "type": "signal"},
            {"id": "sig6", "type": "signal"},
            {"id": "sig7", "type": "signal"},
            {"id": "sig8", "type": "signal"},
        ],
        "edges": [
            {"parent": "cd1", "child": "pg1"},
            {"parent": "cd1", "child": "pg2"},
            {"parent": "pg1", "child": "rtu1"},
            {"parent": "pg1", "child": "rtu2"},
            {"parent": "pg2", "child": "rtu3"},
            {"parent": "pg2", "child": "rtu4"},
            {"parent": "rtu1", "child": "sig1"},
            {"parent": "rtu1", "child": "sig2"},
            {"parent": "rtu2", "child": "sig3"},
            {"parent": "rtu2", "child": "sig4"},
            {"parent": "rtu3", "child": "sig5"},
            {"parent": "rtu3", "child": "sig6"},
            {"parent": "rtu4", "child": "sig7"},
            {"parent": "rtu4", "child": "sig8"},
        ],
    }
    snapshot = load_topology_dict(data)
    index = TopologyIndex(snapshot)
    return snapshot, index


class TestBuildLeafObservations:
    """Test leaf observation building."""

    def test_builds_observations_from_processed_signals(self):
        """Test building observations from signal data."""
        processed = {
            "sig1": {
                "quality_class": "GOOD",
                "sqi": 85.0,
                "sqi_components": {"noise": 90, "drift": 80},
            },
            "sig2": {
                "quality_class": "POOR",
                "sqi": 40.0,
                "sqi_components": {"noise": 30, "drift": 50},
            },
        }

        observations = build_leaf_observations(processed)

        assert len(observations) == 2
        assert not observations["sig1"].is_affected
        assert observations["sig2"].is_affected
        assert observations["sig2"].cause == "noise"  # Lowest component

    def test_uses_active_incidents(self):
        """Test that active incidents affect state."""
        processed = {
            "sig1": {"quality_class": "GOOD", "sqi": 90.0},
        }
        incidents = [
            {"signal_id": "sig1", "event_type": "started", "cause": "drift"},
        ]

        observations = build_leaf_observations(
            processed,
            incident_events=incidents,
            use_active_incidents=True,
        )

        assert observations["sig1"].is_affected
        assert observations["sig1"].cause == "drift"
        assert observations["sig1"].has_active_incident

    def test_uses_missing_ratio_threshold(self):
        """Test that high missing ratio triggers affected state."""
        processed = {
            "sig1": {"quality_class": "GOOD", "sqi": 90.0},
        }
        missing_ratios = {"sig1": 0.5}

        observations = build_leaf_observations(
            processed,
            missing_ratios=missing_ratios,
            missing_ratio_threshold=0.2,
        )

        assert observations["sig1"].is_affected
        assert observations["sig1"].cause == "missing"

    def test_normalizes_causes(self):
        """Test that causes are normalized to bounded set."""
        processed = {
            "sig1": {"quality_class": "POOR", "sqi": 40.0, "sqi_components": {}},
        }
        incidents = [
            {"signal_id": "sig1", "event_type": "started", "cause": "UNKNOWN_CAUSE"},
        ]

        observations = build_leaf_observations(processed, incident_events=incidents)

        assert observations["sig1"].cause == "unknown"


class TestAggregateNodeEvidence:
    """Test evidence aggregation."""

    def test_aggregates_affected_counts(self, test_topology):
        """Test that affected counts are aggregated correctly."""
        snapshot, index = test_topology
        state = RCAState()

        # Make sig1, sig2, sig3, sig4 (all under pg1) affected
        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="missing", sqi=20),
            "sig2": LeafObservation("sig2", is_affected=True, cause="missing", sqi=25),
            "sig3": LeafObservation("sig3", is_affected=True, cause="missing", sqi=30),
            "sig4": LeafObservation("sig4", is_affected=True, cause="missing", sqi=35),
            "sig5": LeafObservation("sig5", is_affected=False, sqi=90),
            "sig6": LeafObservation("sig6", is_affected=False, sqi=95),
            "sig7": LeafObservation("sig7", is_affected=False, sqi=90),
            "sig8": LeafObservation("sig8", is_affected=False, sqi=95),
        }

        evidence = aggregate_node_evidence(
            snapshot, index, observations, state,
            scan_index=1, scan_timestamp=1.0,
        )

        # pg1 has 4 signals, all affected
        assert evidence["pg1"].total_children == 4
        assert evidence["pg1"].affected_children == 4
        assert evidence["pg1"].affected_fraction == 1.0

        # pg2 has 4 signals, none affected
        assert evidence["pg2"].total_children == 4
        assert evidence["pg2"].affected_children == 0
        assert evidence["pg2"].affected_fraction == 0.0

        # cd1 has 8 signals, 4 affected
        assert evidence["cd1"].total_children == 8
        assert evidence["cd1"].affected_children == 4
        assert evidence["cd1"].affected_fraction == 0.5

    def test_computes_cause_mix(self, test_topology):
        """Test that cause mix is computed correctly."""
        snapshot, index = test_topology
        state = RCAState()

        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="missing"),
            "sig2": LeafObservation("sig2", is_affected=True, cause="missing"),
            "sig3": LeafObservation("sig3", is_affected=True, cause="drift"),
            "sig4": LeafObservation("sig4", is_affected=False),
            "sig5": LeafObservation("sig5", is_affected=False),
            "sig6": LeafObservation("sig6", is_affected=False),
            "sig7": LeafObservation("sig7", is_affected=False),
            "sig8": LeafObservation("sig8", is_affected=False),
        }

        evidence = aggregate_node_evidence(
            snapshot, index, observations, state,
            scan_index=1, scan_timestamp=1.0,
        )

        assert evidence["pg1"].cause_mix == {"drift": 1, "missing": 2}

    def test_computes_onset_span(self, test_topology):
        """Test that onset span is computed from state."""
        snapshot, index = test_topology
        state = RCAState()

        # Simulate signals becoming affected at different scans
        observations1 = {
            f"sig{i}": LeafObservation(f"sig{i}", is_affected=i <= 2, cause="missing")
            for i in range(1, 9)
        }
        evidence1 = aggregate_node_evidence(
            snapshot, index, observations1, state,
            scan_index=10, scan_timestamp=10.0,
        )

        # sig1, sig2 became affected at scan 10
        assert evidence1["pg1"].onset_scan_min == 10
        assert evidence1["pg1"].onset_scan_max == 10
        assert evidence1["pg1"].onset_span_scans == 0

        # Now sig3 becomes affected at scan 15
        observations2 = {
            f"sig{i}": LeafObservation(f"sig{i}", is_affected=i <= 3, cause="missing")
            for i in range(1, 9)
        }
        evidence2 = aggregate_node_evidence(
            snapshot, index, observations2, state,
            scan_index=15, scan_timestamp=15.0,
        )

        # Onset span should now be 5 (15 - 10)
        assert evidence2["pg1"].onset_scan_min == 10
        assert evidence2["pg1"].onset_scan_max == 15
        assert evidence2["pg1"].onset_span_scans == 5

    def test_computes_coherence_score(self, test_topology):
        """Test coherence score computation."""
        snapshot, index = test_topology
        state = RCAState()

        # All affected at same scan = high coherence
        observations = {
            f"sig{i}": LeafObservation(f"sig{i}", is_affected=True, cause="missing")
            for i in range(1, 9)
        }

        evidence = aggregate_node_evidence(
            snapshot, index, observations, state,
            scan_index=1, scan_timestamp=1.0,
            coherence_k_scans=5,
        )

        # Onset span = 0, coherence = exp(0) = 1.0
        assert evidence["cd1"].coherence_score == 1.0

    def test_computes_comms_signature(self, test_topology):
        """Test comms signature score computation."""
        snapshot, index = test_topology
        state = RCAState()

        # All missing = 100% comms signature
        observations = {
            f"sig{i}": LeafObservation(f"sig{i}", is_affected=True, cause="missing")
            for i in range(1, 9)
        }

        evidence = aggregate_node_evidence(
            snapshot, index, observations, state,
            scan_index=1, scan_timestamp=1.0,
        )

        assert evidence["cd1"].comms_signature_score == 1.0

        # Mixed causes = lower comms signature
        state2 = RCAState()
        observations2 = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="missing"),
            "sig2": LeafObservation("sig2", is_affected=True, cause="drift"),
            "sig3": LeafObservation("sig3", is_affected=True, cause="spikes"),
            "sig4": LeafObservation("sig4", is_affected=True, cause="noise"),
            "sig5": LeafObservation("sig5", is_affected=False),
            "sig6": LeafObservation("sig6", is_affected=False),
            "sig7": LeafObservation("sig7", is_affected=False),
            "sig8": LeafObservation("sig8", is_affected=False),
        }

        evidence2 = aggregate_node_evidence(
            snapshot, index, observations2, state2,
            scan_index=1, scan_timestamp=1.0,
        )

        # 1 missing out of 4 affected = 0.25
        assert evidence2["pg1"].comms_signature_score == 0.25

    def test_computes_concentration_score(self, test_topology):
        """Test concentration score (vs siblings)."""
        snapshot, index = test_topology
        state = RCAState()

        # Only pg1 signals affected, pg2 signals healthy
        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="missing"),
            "sig2": LeafObservation("sig2", is_affected=True, cause="missing"),
            "sig3": LeafObservation("sig3", is_affected=True, cause="missing"),
            "sig4": LeafObservation("sig4", is_affected=True, cause="missing"),
            "sig5": LeafObservation("sig5", is_affected=False),
            "sig6": LeafObservation("sig6", is_affected=False),
            "sig7": LeafObservation("sig7", is_affected=False),
            "sig8": LeafObservation("sig8", is_affected=False),
        }

        evidence = aggregate_node_evidence(
            snapshot, index, observations, state,
            scan_index=1, scan_timestamp=1.0,
        )

        # pg1: affected_fraction=1.0, sibling pg2 has 0.0
        # concentration = 1.0 - 0.0 = 1.0
        assert evidence["pg1"].concentration_score == 1.0

        # pg2: affected_fraction=0.0, sibling pg1 has 1.0
        # concentration = 0.0 - 1.0 = -1.0
        assert evidence["pg2"].concentration_score == -1.0

    def test_evidence_deterministic(self, test_topology):
        """Test that evidence aggregation is deterministic."""
        snapshot, index = test_topology

        observations = {
            f"sig{i}": LeafObservation(f"sig{i}", is_affected=i <= 4, cause="missing")
            for i in range(1, 9)
        }

        # Run twice with fresh state
        state1 = RCAState()
        evidence1 = aggregate_node_evidence(
            snapshot, index, observations, state1,
            scan_index=1, scan_timestamp=1.0,
        )

        state2 = RCAState()
        evidence2 = aggregate_node_evidence(
            snapshot, index, observations, state2,
            scan_index=1, scan_timestamp=1.0,
        )

        # Evidence should be identical
        for node_id in evidence1:
            e1 = evidence1[node_id].to_dict()
            e2 = evidence2[node_id].to_dict()
            assert e1 == e2, f"Evidence differs for {node_id}"


class TestSelectRepresentativeSignals:
    """Test representative signal selection."""

    def test_selects_by_severity(self):
        """Test that signals are selected by severity (lowest SQI first)."""
        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, sqi=50.0),
            "sig2": LeafObservation("sig2", is_affected=True, sqi=20.0),
            "sig3": LeafObservation("sig3", is_affected=True, sqi=80.0),
        }

        selected = select_representative_signals(
            observations,
            ["sig1", "sig2", "sig3"],
            max_signals=2,
        )

        # Should select sig2 (sqi=20) and sig1 (sqi=50)
        assert selected == ["sig2", "sig1"]

    def test_respects_max_signals(self):
        """Test that max_signals limit is respected."""
        observations = {
            f"sig{i}": LeafObservation(f"sig{i}", is_affected=True, sqi=50.0)
            for i in range(1, 20)
        }

        selected = select_representative_signals(
            observations,
            list(observations.keys()),
            max_signals=5,
        )

        assert len(selected) == 5

    def test_deterministic_ordering(self):
        """Test that selection is deterministic."""
        observations = {
            "sig_a": LeafObservation("sig_a", is_affected=True, sqi=50.0),
            "sig_b": LeafObservation("sig_b", is_affected=True, sqi=50.0),
            "sig_c": LeafObservation("sig_c", is_affected=True, sqi=50.0),
        }

        # Same SQI, should sort by ID
        selected1 = select_representative_signals(
            observations,
            ["sig_c", "sig_a", "sig_b"],
            max_signals=3,
        )
        selected2 = select_representative_signals(
            observations,
            ["sig_b", "sig_c", "sig_a"],
            max_signals=3,
        )

        assert selected1 == selected2
        assert selected1 == ["sig_a", "sig_b", "sig_c"]


class TestRCAState:
    """Test RCA state management."""

    def test_tracks_onset_scans(self):
        """Test that onset scans are tracked correctly."""
        state = RCAState()

        # Signal becomes affected at scan 5
        state.advance_scan(5)
        onset = state.update_signal("sig1", is_affected=True)
        assert onset == 5

        # Signal remains affected at scan 6 - onset unchanged
        state.advance_scan(6)
        onset = state.update_signal("sig1", is_affected=True)
        assert onset == 5

        # Signal recovers at scan 7
        state.advance_scan(7)
        onset = state.update_signal("sig1", is_affected=False)
        assert onset is None

        # Signal becomes affected again at scan 8 - new onset
        state.advance_scan(8)
        onset = state.update_signal("sig1", is_affected=True)
        assert onset == 8

    def test_prunes_inactive_signals(self):
        """Test that inactive signals are pruned."""
        state = RCAState(retention_scans=10)

        # Add signals at scan 0
        state.advance_scan(0)
        state.update_signal("sig1", is_affected=True)
        state.update_signal("sig2", is_affected=True)

        # Update sig1 at scan 5
        state.advance_scan(5)
        state.update_signal("sig1", is_affected=True)

        # At scan 15, sig2 should be pruneable (last seen at 0, cutoff at 5)
        state.advance_scan(15)
        pruned = state.prune_inactive()

        assert pruned == 1
        assert state.get_signal_state("sig1") is not None
        assert state.get_signal_state("sig2") is None

    def test_serialization_roundtrip(self):
        """Test state serialization and restoration."""
        state = RCAState(retention_scans=100)

        state.advance_scan(10)
        state.update_signal("sig1", is_affected=True, cause="drift")
        state.update_signal("sig2", is_affected=False)
        state.update_candidate_stability("rtu1", 0.8, 0.9, 0.75)

        # Serialize and restore
        data = state.to_dict()
        restored = RCAState.from_dict(data)

        assert restored.current_scan == 10
        assert restored.get_signal_onset("sig1") == 10
        assert restored.get_signal_state("sig1").last_cause == "drift"
        assert restored.get_candidate_stability("rtu1").consecutive_above_threshold == 1
