"""Tests for topology-aware suppression."""

from dataclasses import dataclass
from typing import Dict, List, Optional

from sqe.topology.model import TopologySnapshot
from sqe.topology.index import TopologyIndex
from sqe.topology.loader import load_topology_dict
from sqe.rca.node_incidents import (
    NodeIncidentConfig,
    NodeIncidentTracker,
)
from sqe.rca.suppression import (
    SuppressionConfig,
    SuppressionManager,
    get_default_suppression_config,
    create_suppression_manager,
)


@dataclass
class MockEvidence:
    """Mock evidence for testing."""

    cause_mix: Dict[str, int]


@dataclass
class MockCandidate:
    """Mock candidate for testing."""

    node_id: str
    node_type: str
    confidence: float
    score: float
    representative_signals: List[str]
    evidence: Optional[MockEvidence] = None
    recommended_action_code: str = "INVESTIGATE"


def make_test_topology() -> TopologySnapshot:
    """Create a test topology.

    Structure:
        comms1 (comms_domain)
        ├── pg1 (poll_group)
        │   ├── rtu1 (rtu)
        │   │   ├── sig1 (signal)
        │   │   └── sig2 (signal)
        │   └── rtu2 (rtu)
        │       ├── sig3 (signal)
        │       └── sig4 (signal)
        └── pg2 (poll_group)
            └── rtu3 (rtu)
                ├── sig5 (signal)
                └── sig6 (signal)
    """
    return load_topology_dict({
        "nodes": [
            {"id": "comms1", "type": "comms_domain"},
            {"id": "pg1", "type": "poll_group"},
            {"id": "pg2", "type": "poll_group"},
            {"id": "rtu1", "type": "rtu"},
            {"id": "rtu2", "type": "rtu"},
            {"id": "rtu3", "type": "rtu"},
            {"id": "sig1", "type": "signal"},
            {"id": "sig2", "type": "signal"},
            {"id": "sig3", "type": "signal"},
            {"id": "sig4", "type": "signal"},
            {"id": "sig5", "type": "signal"},
            {"id": "sig6", "type": "signal"},
        ],
        "edges": [
            {"parent": "comms1", "child": "pg1"},
            {"parent": "comms1", "child": "pg2"},
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
    })


class TestSuppressionConfig:
    """Tests for SuppressionConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = get_default_suppression_config()
        assert config.enabled
        assert config.suppress_child_signals
        assert config.suppress_child_incidents
        assert "signal" in config.suppressed_types
        assert "comms_domain" in config.suppressor_types

    def test_custom_config(self):
        """Test custom configuration."""
        config = SuppressionConfig(
            enabled=False,
            suppress_child_signals=False,
            min_suppressor_confidence=0.8,
        )
        assert not config.enabled
        assert not config.suppress_child_signals
        assert config.min_suppressor_confidence == 0.8


class TestSuppressionManager:
    """Tests for SuppressionManager."""

    def test_signals_suppressed_when_rtu_incident_active(self):
        """Test that signals are suppressed when parent RTU has an incident."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        # Create incident on rtu1
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1", "sig2"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        # Create suppression manager
        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        # sig1 and sig2 should be suppressed (children of rtu1)
        assert manager.is_suppressed("sig1")
        assert manager.is_suppressed("sig2")

        # sig3-6 should not be suppressed (children of rtu2, rtu3)
        assert not manager.is_suppressed("sig3")
        assert not manager.is_suppressed("sig4")
        assert not manager.is_suppressed("sig5")
        assert not manager.is_suppressed("sig6")

    def test_signals_suppressed_when_comms_domain_incident_active(self):
        """Test that all signals are suppressed when comms_domain has an incident."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        # Create incident on comms1
        candidates = [
            MockCandidate(
                node_id="comms1",
                node_type="comms_domain",
                confidence=0.85,
                score=0.75,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        # All signals should be suppressed
        suppressed_signals = manager.list_suppressed_signals()
        assert len(suppressed_signals) == 6
        assert "sig1" in suppressed_signals
        assert "sig6" in suppressed_signals

        # All RTUs should be suppressed
        assert manager.is_suppressed("rtu1")
        assert manager.is_suppressed("rtu2")
        assert manager.is_suppressed("rtu3")

        # Poll groups should be suppressed
        assert manager.is_suppressed("pg1")
        assert manager.is_suppressed("pg2")

    def test_child_incidents_not_opened_while_parent_incident_open(self):
        """Test that should_suppress_incident returns True for child nodes."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        # Create incident on pg1
        candidates = [
            MockCandidate(
                node_id="pg1",
                node_type="poll_group",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        # rtu1, rtu2 incidents should be suppressed
        assert manager.should_suppress_incident("rtu1")
        assert manager.should_suppress_incident("rtu2")

        # rtu3 incident should NOT be suppressed (different branch)
        assert not manager.should_suppress_incident("rtu3")

    def test_suppression_disabled(self):
        """Test that suppression can be disabled."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        # Create incident on rtu1
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        config = SuppressionConfig(enabled=False)
        manager = SuppressionManager(topology, index, tracker, config)
        manager.update()

        # Nothing should be suppressed
        assert not manager.is_suppressed("sig1")
        assert not manager.is_suppressed("sig2")
        assert len(manager.list_suppressed_nodes()) == 0

    def test_min_suppressor_confidence(self):
        """Test that low-confidence incidents don't suppress."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker(
            NodeIncidentConfig(
                min_confidence_to_start=0.3,  # Low threshold to open incident
            )
        )

        # Create incident with low confidence
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.4,  # Above tracker threshold but below suppression threshold
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        config = SuppressionConfig(min_suppressor_confidence=0.5)
        manager = SuppressionManager(topology, index, tracker, config)
        manager.update()

        # Low-confidence incident should not suppress
        assert not manager.is_suppressed("sig1")
        assert not manager.is_suppressed("sig2")

    def test_get_suppressor(self):
        """Test getting the suppressor for a node."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        assert manager.get_suppressor("sig1") == "rtu1"
        assert manager.get_suppressor("sig2") == "rtu1"
        assert manager.get_suppressor("sig3") is None

    def test_filter_candidates(self):
        """Test filtering suppressed candidates."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        # Create incident on pg1
        candidates = [
            MockCandidate(
                node_id="pg1",
                node_type="poll_group",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        # Filter candidates including suppressed ones
        all_candidates = [
            MockCandidate("rtu1", "rtu", 0.7, 0.6, []),
            MockCandidate("rtu2", "rtu", 0.65, 0.55, []),
            MockCandidate("rtu3", "rtu", 0.6, 0.5, []),  # Not suppressed
        ]
        filtered = manager.filter_candidates(all_candidates)

        assert len(filtered) == 1
        assert filtered[0].node_id == "rtu3"

    def test_filter_alerts(self):
        """Test filtering suppressed alerts."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        # Filter alerts
        all_signals = ["sig1", "sig2", "sig3", "sig4"]
        filtered = manager.filter_alerts(all_signals)

        assert len(filtered) == 2
        assert "sig3" in filtered
        assert "sig4" in filtered
        assert "sig1" not in filtered

    def test_suppression_summary(self):
        """Test getting suppression summary."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        summary = manager.get_suppression_summary()
        assert summary["enabled"]
        assert summary["total_suppressed"] == 2  # sig1, sig2
        assert summary["suppressed_by_type"]["signal"] == 2
        assert "rtu1" in summary["active_suppressors"]

    def test_reset_clears_suppression(self):
        """Test that reset clears suppression state."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        assert manager.is_suppressed("sig1")

        manager.reset()
        assert not manager.is_suppressed("sig1")

    def test_suppression_updates_when_incidents_change(self):
        """Test that suppression updates when incidents are closed."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        # Open incident
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        assert manager.is_suppressed("sig1")

        # Close incident
        tracker.update([], scan_index=2, scan_timestamp=20.0)
        manager.update()

        # No longer suppressed
        assert not manager.is_suppressed("sig1")


class TestCreateSuppressionManager:
    """Tests for create_suppression_manager factory function."""

    def test_creates_with_default_config(self):
        """Test creation with default configuration."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        manager = create_suppression_manager(topology, index, tracker)
        assert manager.config.enabled
        assert manager.config.min_suppressor_confidence == 0.5

    def test_creates_with_custom_config(self):
        """Test creation with custom configuration dictionary."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        config_dict = {
            "enabled": True,
            "suppress_child_signals": False,
            "min_suppressor_confidence": 0.75,
        }
        manager = create_suppression_manager(topology, index, tracker, config_dict)

        assert manager.config.enabled
        assert not manager.config.suppress_child_signals
        assert manager.config.min_suppressor_confidence == 0.75


class TestMultipleSuppressionScenarios:
    """Tests for complex suppression scenarios."""

    def test_hierarchical_suppression(self):
        """Test that multiple levels of suppression work correctly."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        # Create incidents at multiple levels
        candidates = [
            MockCandidate(
                node_id="comms1",
                node_type="comms_domain",
                confidence=0.85,
                score=0.75,
                representative_signals=["sig1"],
            ),
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.75,
                score=0.65,
                representative_signals=["sig1"],
            ),
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        # All signals suppressed
        assert manager.is_suppressed("sig1")
        assert manager.is_suppressed("sig6")

        # RTUs suppressed by comms1
        assert manager.is_suppressed("rtu1")
        assert manager.is_suppressed("rtu3")

    def test_partial_suppression_different_branches(self):
        """Test suppression only affects affected branches."""
        topology = make_test_topology()
        index = TopologyIndex(topology)
        tracker = NodeIncidentTracker()

        # Create incident only on pg1
        candidates = [
            MockCandidate(
                node_id="pg1",
                node_type="poll_group",
                confidence=0.8,
                score=0.7,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        manager = SuppressionManager(topology, index, tracker)
        manager.update()

        # pg1 branch suppressed
        assert manager.is_suppressed("rtu1")
        assert manager.is_suppressed("rtu2")
        assert manager.is_suppressed("sig1")
        assert manager.is_suppressed("sig4")

        # pg2 branch NOT suppressed
        assert not manager.is_suppressed("pg2")
        assert not manager.is_suppressed("rtu3")
        assert not manager.is_suppressed("sig5")
        assert not manager.is_suppressed("sig6")
