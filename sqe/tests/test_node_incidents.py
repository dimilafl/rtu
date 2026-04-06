"""Tests for node incident tracking."""

from dataclasses import dataclass
from typing import Dict, List, Optional

from sqe.rca.node_incidents import (
    NodeIncident,
    NodeIncidentConfig,
    NodeIncidentTracker,
    get_default_incident_config,
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


class TestNodeIncident:
    """Tests for NodeIncident dataclass."""

    def test_incident_creation(self):
        """Test basic incident creation."""
        incident = NodeIncident(
            node_id="rtu1",
            node_type="rtu",
            start_scan=100,
            start_timestamp=1000.0,
        )
        assert incident.node_id == "rtu1"
        assert incident.node_type == "rtu"
        assert incident.start_scan == 100
        assert incident.is_active
        assert incident.end_scan is None

    def test_incident_is_active(self):
        """Test is_active property."""
        incident = NodeIncident(
            node_id="rtu1",
            node_type="rtu",
            start_scan=100,
            start_timestamp=1000.0,
        )
        assert incident.is_active

        incident.end_scan = 110
        incident.end_timestamp = 1100.0
        assert not incident.is_active

    def test_incident_duration(self):
        """Test duration_scans property."""
        incident = NodeIncident(
            node_id="rtu1",
            node_type="rtu",
            start_scan=100,
            start_timestamp=1000.0,
        )
        # Active incident has duration 0
        assert incident.duration_scans == 0

        incident.end_scan = 115
        assert incident.duration_scans == 15

    def test_incident_to_dict(self):
        """Test serialization to dictionary."""
        incident = NodeIncident(
            node_id="rtu1",
            node_type="rtu",
            start_scan=100,
            start_timestamp=1000.0,
            peak_confidence=0.85,
            peak_score=0.72,
            supporting_signals=["sig1", "sig2"],
            cause_summary={"missing": 2, "stale": 1},
            recommended_action="CHECK_RTU_CONNECTIVITY",
        )

        d = incident.to_dict()
        assert d["node_id"] == "rtu1"
        assert d["node_type"] == "rtu"
        assert d["start_scan"] == 100
        assert d["peak_confidence"] == 0.85
        assert d["supporting_signals"] == ["sig1", "sig2"]
        assert d["cause_summary"] == {"missing": 2, "stale": 1}
        assert d["is_active"]


class TestNodeIncidentConfig:
    """Tests for NodeIncidentConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = get_default_incident_config()
        assert config.min_confidence_to_start == 0.7
        assert config.min_confidence_to_continue == 0.3
        assert config.min_score_to_start == 0.5
        assert config.min_score_to_continue == 0.2
        assert config.supporting_signals_max == 10
        assert config.cooldown_scans == 3

    def test_custom_config(self):
        """Test custom configuration."""
        config = NodeIncidentConfig(
            min_confidence_to_start=0.8,
            min_confidence_to_continue=0.4,
            cooldown_scans=5,
        )
        assert config.min_confidence_to_start == 0.8
        assert config.min_confidence_to_continue == 0.4
        assert config.cooldown_scans == 5


class TestNodeIncidentTracker:
    """Tests for NodeIncidentTracker."""

    def test_incident_opens_when_threshold_crossed(self):
        """Test that incident opens when confidence/score thresholds are met."""
        config = NodeIncidentConfig(
            min_confidence_to_start=0.7,
            min_score_to_start=0.5,
        )
        tracker = NodeIncidentTracker(config)

        # Candidate below threshold - no incident
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.5,
                score=0.4,
                representative_signals=["sig1"],
            )
        ]
        actions = tracker.update(candidates, scan_index=1, scan_timestamp=10.0)
        assert "rtu1" not in actions
        assert tracker.active_count() == 0

        # Candidate above threshold - incident opens
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1", "sig2"],
                evidence=MockEvidence(cause_mix={"missing": 2}),
            )
        ]
        actions = tracker.update(candidates, scan_index=2, scan_timestamp=20.0)
        assert actions["rtu1"] == "opened"
        assert tracker.active_count() == 1
        assert tracker.has_active_incident("rtu1")

    def test_incident_closes_when_confidence_drops(self):
        """Test that incident closes when confidence drops below threshold."""
        config = NodeIncidentConfig(
            min_confidence_to_start=0.7,
            min_confidence_to_continue=0.3,
        )
        tracker = NodeIncidentTracker(config)

        # Open incident
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)
        assert tracker.active_count() == 1

        # Confidence drops below continue threshold
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.2,  # Below 0.3
                score=0.6,
                representative_signals=["sig1"],
            )
        ]
        actions = tracker.update(candidates, scan_index=2, scan_timestamp=20.0)
        assert actions["rtu1"] == "closed"
        assert tracker.active_count() == 0
        assert not tracker.has_active_incident("rtu1")

    def test_incident_closes_when_score_drops(self):
        """Test that incident closes when score drops below threshold."""
        config = NodeIncidentConfig(
            min_score_to_start=0.5,
            min_score_to_continue=0.2,
        )
        tracker = NodeIncidentTracker(config)

        # Open incident
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        # Score drops below continue threshold
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.1,  # Below 0.2
                representative_signals=["sig1"],
            )
        ]
        actions = tracker.update(candidates, scan_index=2, scan_timestamp=20.0)
        assert actions["rtu1"] == "closed"
        assert tracker.active_count() == 0

    def test_incident_closes_when_candidate_disappears(self):
        """Test that incident closes when node no longer a candidate."""
        tracker = NodeIncidentTracker()

        # Open incident
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        # Candidate disappears
        actions = tracker.update([], scan_index=2, scan_timestamp=20.0)
        assert actions["rtu1"] == "closed"
        assert tracker.active_count() == 0

    def test_cooldown_prevents_immediate_reopen(self):
        """Test that cooldown prevents immediate reopen after close."""
        config = NodeIncidentConfig(
            min_confidence_to_start=0.7,
            cooldown_scans=3,
        )
        tracker = NodeIncidentTracker(config)

        # Open incident
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        # Close incident
        tracker.update([], scan_index=2, scan_timestamp=20.0)
        assert tracker.active_count() == 0

        # Try to reopen during cooldown - should not open
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.9,
                score=0.8,
                representative_signals=["sig1"],
            )
        ]
        actions = tracker.update(candidates, scan_index=3, scan_timestamp=30.0)
        assert "rtu1" not in actions
        assert tracker.active_count() == 0

        # After cooldown, can reopen (cooldown ends at scan 2 + 3 = 5)
        actions = tracker.update(candidates, scan_index=5, scan_timestamp=50.0)
        assert actions["rtu1"] == "opened"
        assert tracker.active_count() == 1

    def test_list_active_incidents_deterministic(self):
        """Test that list_active_incidents returns deterministic order."""
        tracker = NodeIncidentTracker()

        # Open multiple incidents
        candidates = [
            MockCandidate(
                node_id="rtu3",
                node_type="rtu",
                confidence=0.75,
                score=0.6,
                representative_signals=[],
            ),
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.85,
                score=0.7,
                representative_signals=[],
            ),
            MockCandidate(
                node_id="rtu2",
                node_type="rtu",
                confidence=0.85,
                score=0.65,
                representative_signals=[],
            ),
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        active = tracker.list_active_incidents()
        assert len(active) == 3

        # Should be sorted by confidence desc, then node_id asc
        # rtu1 and rtu2 both have 0.85 confidence, so rtu1 comes first
        assert active[0].node_id == "rtu1"
        assert active[1].node_id == "rtu2"
        assert active[2].node_id == "rtu3"

    def test_peak_confidence_tracked(self):
        """Test that peak confidence is tracked during incident."""
        tracker = NodeIncidentTracker()

        # Open with 0.75 confidence
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.75,
                score=0.6,
                representative_signals=[],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        # Update with 0.9 confidence
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.9,
                score=0.6,
                representative_signals=[],
            )
        ]
        tracker.update(candidates, scan_index=2, scan_timestamp=20.0)

        # Update with 0.8 confidence (lower than peak)
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=[],
            )
        ]
        tracker.update(candidates, scan_index=3, scan_timestamp=30.0)

        incident = tracker.get_incident("rtu1")
        assert incident.peak_confidence == 0.9

    def test_supporting_signals_bounded(self):
        """Test that supporting signals are bounded."""
        config = NodeIncidentConfig(supporting_signals_max=3)
        tracker = NodeIncidentTracker(config)

        # Open with many signals
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1", "sig2", "sig3", "sig4", "sig5"],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        incident = tracker.get_incident("rtu1")
        assert len(incident.supporting_signals) == 3
        assert incident.supporting_signals == ["sig1", "sig2", "sig3"]

    def test_closed_incidents_tracked(self):
        """Test that closed incidents are tracked."""
        tracker = NodeIncidentTracker()

        # Open and close incident
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=[],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)
        tracker.update([], scan_index=5, scan_timestamp=50.0)

        closed = tracker.list_closed_incidents()
        assert len(closed) == 1
        assert closed[0].node_id == "rtu1"
        assert closed[0].start_scan == 1
        assert closed[0].end_scan == 5

    def test_list_closed_since_scan(self):
        """Test filtering closed incidents by scan."""
        tracker = NodeIncidentTracker(NodeIncidentConfig(cooldown_scans=0))

        # Open and close multiple incidents
        for i, node in enumerate(["rtu1", "rtu2", "rtu3"]):
            candidates = [
                MockCandidate(
                    node_id=node,
                    node_type="rtu",
                    confidence=0.8,
                    score=0.6,
                    representative_signals=[],
                )
            ]
            tracker.update(candidates, scan_index=i * 10, scan_timestamp=float(i * 100))
            tracker.update([], scan_index=i * 10 + 5, scan_timestamp=float(i * 100 + 50))

        # Get all closed
        closed = tracker.list_closed_incidents()
        assert len(closed) == 3

        # Get closed since scan 10
        closed = tracker.list_closed_incidents(since_scan=10)
        assert len(closed) == 2  # rtu2 (closed at 15) and rtu3 (closed at 25)

    def test_reset_clears_all_state(self):
        """Test that reset clears all state."""
        tracker = NodeIncidentTracker()

        # Create some state
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=[],
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        assert tracker.active_count() == 1

        tracker.reset()
        assert tracker.active_count() == 0
        assert len(tracker.list_closed_incidents()) == 0

    def test_state_serialization(self):
        """Test state serialization and deserialization."""
        tracker1 = NodeIncidentTracker()

        # Create some state
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1", "sig2"],
                evidence=MockEvidence(cause_mix={"missing": 2}),
            )
        ]
        tracker1.update(candidates, scan_index=1, scan_timestamp=10.0)

        # Serialize
        state = tracker1.to_state_dict()
        assert "active" in state
        assert "closed" in state

        # Deserialize into new tracker
        tracker2 = NodeIncidentTracker()
        tracker2.load_state_dict(state)

        assert tracker2.active_count() == 1
        incident = tracker2.get_incident("rtu1")
        assert incident.node_id == "rtu1"
        assert incident.peak_confidence == 0.8
        assert incident.supporting_signals == ["sig1", "sig2"]

    def test_prune_closed_incidents(self):
        """Test pruning old closed incidents."""
        tracker = NodeIncidentTracker(NodeIncidentConfig(cooldown_scans=0))

        # Create many closed incidents
        for i in range(20):
            candidates = [
                MockCandidate(
                    node_id=f"rtu{i}",
                    node_type="rtu",
                    confidence=0.8,
                    score=0.6,
                    representative_signals=[],
                )
            ]
            tracker.update(candidates, scan_index=i * 10, scan_timestamp=float(i * 100))
            tracker.update([], scan_index=i * 10 + 5, scan_timestamp=float(i * 100 + 50))

        assert len(tracker.list_closed_incidents()) == 20

        # Prune to keep only 5
        pruned = tracker.prune_closed(keep_count=5)
        assert pruned == 15
        assert len(tracker.list_closed_incidents()) == 5


class TestIncidentCauseSummary:
    """Tests for cause summary tracking."""

    def test_cause_summary_from_evidence(self):
        """Test that cause summary is extracted from evidence."""
        tracker = NodeIncidentTracker()

        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1"],
                evidence=MockEvidence(cause_mix={"missing": 3, "stale": 2, "noise": 1}),
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        incident = tracker.get_incident("rtu1")
        assert incident.cause_summary == {"missing": 3, "stale": 2, "noise": 1}

    def test_cause_summary_updated(self):
        """Test that cause summary is updated on each scan."""
        tracker = NodeIncidentTracker()

        # Initial cause summary
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1"],
                evidence=MockEvidence(cause_mix={"missing": 3}),
            )
        ]
        tracker.update(candidates, scan_index=1, scan_timestamp=10.0)

        # Updated cause summary
        candidates = [
            MockCandidate(
                node_id="rtu1",
                node_type="rtu",
                confidence=0.8,
                score=0.6,
                representative_signals=["sig1"],
                evidence=MockEvidence(cause_mix={"missing": 1, "stale": 4}),
            )
        ]
        tracker.update(candidates, scan_index=2, scan_timestamp=20.0)

        incident = tracker.get_incident("rtu1")
        assert incident.cause_summary == {"missing": 1, "stale": 4}
