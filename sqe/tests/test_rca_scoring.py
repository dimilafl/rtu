"""Tests for RCA scoring and confidence."""

from __future__ import annotations

import pytest

from sqe.comms.budget import UtilizationStatus
from sqe.comms.health import CommsHealthClass, CommsHealthStatus
from sqe.topology.loader import load_topology_dict
from sqe.topology.index import TopologyIndex
from sqe.rca.schema import LeafObservation, NodeEvidence
from sqe.rca.evidence import aggregate_node_evidence
from sqe.rca.state import RCAState
from sqe.rca.scoring import (
    ScoringConfig,
    score_candidates,
    get_default_scoring_config,
    get_primary_and_secondary,
)
from sqe.rca.confidence import (
    ConfidenceConfig,
    compute_confidence,
    compute_all_confidences,
    get_default_confidence_config,
    get_confidence_assessment,
)


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


def _make_budget_status(
    node_type: str,
    node_id: str,
    utilization: float,
) -> UtilizationStatus:
    return UtilizationStatus(
        node_type=node_type,
        node_id=node_id,
        scan_index=1,
        scan_timestamp=1.0,
        descendant_signal_count=4,
        expected_bytes=1000,
        observed_bytes=2000,
        observed_bps=16000.0,
        utilization=utilization,
        headroom=1.0 - utilization,
        level="CRITICAL" if utilization >= 0.9 else "OK",
        reasons=[],
    )


def _make_health_status(
    node_type: str,
    node_id: str,
    timeout_rate: float,
    jitter_ms: float,
) -> CommsHealthStatus:
    health_class = CommsHealthClass.CRITICAL if timeout_rate >= 0.1 else CommsHealthClass.OK
    return CommsHealthStatus(
        node_id=node_id,
        node_type=node_type,
        scan_index=1,
        scan_timestamp=1.0,
        timeout_rate=timeout_rate,
        retry_rate=0.0,
        crc_error_rate=0.0,
        avg_poll_cycle_ms=100.0,
        avg_jitter_ms=jitter_ms,
        bytes_tx_total=1000,
        bytes_rx_total=1000,
        health_class=health_class,
        reasons=[],
    )


class TestScoringCandidates:
    """Test root cause candidate scoring."""

    def test_comms_domain_outage_scenario(self, test_topology):
        """All signals missing at same onset = COMMS_DOMAIN as primary."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

        # All signals affected with missing cause (comms-like)
        observations = {
            f"sig{i}": LeafObservation(
                f"sig{i}",
                is_affected=True,
                cause="missing",
                sqi=0.0,
            )
            for i in range(1, 9)
        }

        evidence = aggregate_node_evidence(
            snapshot, index, observations, state,
            scan_index=1, scan_timestamp=1.0,
        )

        candidates = score_candidates(
            snapshot, index, evidence, observations, state, config,
        )

        # Primary should be comms_domain (cd1)
        primary, secondary = get_primary_and_secondary(candidates)

        assert primary is not None
        assert primary.node_type == "comms_domain"
        assert primary.node_id == "cd1"
        assert primary.score > 0.5  # High score for full outage

    def test_poll_group_outage_scenario(self, test_topology):
        """Signals under one poll group affected = POLL_GROUP as primary."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

        # Only pg1 signals affected (sig1-4)
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

        candidates = score_candidates(
            snapshot, index, evidence, observations, state, config,
        )

        primary, secondary = get_primary_and_secondary(candidates)

        assert primary is not None
        # pg1 should score higher than cd1 due to concentration
        assert primary.node_type == "poll_group"
        assert primary.node_id == "pg1"

    def test_single_rtu_failure_scenario(self, test_topology):
        """Signals under one RTU affected = RTU as primary."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

        # Only rtu1 signals affected (sig1, sig2)
        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="missing"),
            "sig2": LeafObservation("sig2", is_affected=True, cause="missing"),
            "sig3": LeafObservation("sig3", is_affected=False),
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

        candidates = score_candidates(
            snapshot, index, evidence, observations, state, config,
        )

        primary, secondary = get_primary_and_secondary(candidates)

        assert primary is not None
        assert primary.node_type == "rtu"
        assert primary.node_id == "rtu1"

    def test_single_signal_drift_scenario(self, test_topology):
        """Single signal with non-comms cause = SIGNAL as primary."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

        # Only sig1 affected with drift (non-comms)
        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="drift"),
            "sig2": LeafObservation("sig2", is_affected=False),
            "sig3": LeafObservation("sig3", is_affected=False),
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

        candidates = score_candidates(
            snapshot, index, evidence, observations, state, config,
        )

        primary, secondary = get_primary_and_secondary(candidates)

        assert primary is not None
        assert primary.node_type == "signal"
        assert primary.node_id == "sig1"

    def test_signature_penalizes_non_comms_upstream(self, test_topology):
        """Non-comms causes should penalize upstream nodes via signature."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

        # All signals affected but with non-comms causes
        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="drift"),
            "sig2": LeafObservation("sig2", is_affected=True, cause="noise"),
            "sig3": LeafObservation("sig3", is_affected=True, cause="spikes"),
            "sig4": LeafObservation("sig4", is_affected=True, cause="oscillation"),
            "sig5": LeafObservation("sig5", is_affected=True, cause="drift"),
            "sig6": LeafObservation("sig6", is_affected=True, cause="noise"),
            "sig7": LeafObservation("sig7", is_affected=True, cause="spikes"),
            "sig8": LeafObservation("sig8", is_affected=True, cause="oscillation"),
        }

        evidence = aggregate_node_evidence(
            snapshot, index, observations, state,
            scan_index=1, scan_timestamp=1.0,
        )

        candidates = score_candidates(
            snapshot, index, evidence, observations, state, config,
        )

        # cd1 should have low signature score since no missing/stale
        cd1_evidence = evidence.get("cd1")
        assert cd1_evidence is not None
        assert cd1_evidence.comms_signature_score == 0.0

    def test_stable_ordering(self, test_topology):
        """Test that candidate ordering is deterministic."""
        snapshot, index = test_topology
        config = get_default_scoring_config()

        observations = {
            f"sig{i}": LeafObservation(f"sig{i}", is_affected=True, cause="missing")
            for i in range(1, 9)
        }

        # Run twice with fresh state
        state1 = RCAState()
        evidence1 = aggregate_node_evidence(
            snapshot, index, observations, state1,
            scan_index=1, scan_timestamp=1.0,
        )
        candidates1 = score_candidates(
            snapshot, index, evidence1, observations, state1, config,
        )

        state2 = RCAState()
        evidence2 = aggregate_node_evidence(
            snapshot, index, observations, state2,
            scan_index=1, scan_timestamp=1.0,
        )
        candidates2 = score_candidates(
            snapshot, index, evidence2, observations, state2, config,
        )

        # Same ordering
        assert [c.node_id for c in candidates1] == [c.node_id for c in candidates2]
        # Same scores
        for c1, c2 in zip(candidates1, candidates2):
            assert c1.score == c2.score


class TestCommsScoringTrackC:
    """Tests for Track C comms-aware RCA scoring."""

    def test_comms_like_with_saturation_boosts_poll_group(self, test_topology):
        """Comms-like outage with saturation should boost poll_group."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

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

        comms_budget_statuses = [
            _make_budget_status("POLL_GROUP", "pg1", utilization=0.95),
        ]
        comms_health_statuses = [
            _make_health_status("POLL_GROUP", "pg1", timeout_rate=0.12, jitter_ms=900.0),
        ]

        candidates = score_candidates(
            snapshot,
            index,
            evidence,
            observations,
            state,
            config,
            comms_budget_statuses=comms_budget_statuses,
            comms_health_statuses=comms_health_statuses,
        )

        primary, _ = get_primary_and_secondary(candidates)

        assert primary is not None
        assert primary.node_type == "poll_group"
        pg1_candidate = next((c for c in candidates if c.node_id == "pg1"), None)
        assert pg1_candidate is not None
        assert pg1_candidate.score_components["comms_boost"] > 0.0
        assert pg1_candidate.score_components["comms_counter"] <= 0.01

    def test_comms_like_without_saturation_adds_counter(self, test_topology):
        """Comms-like outage with normal utilization should add counterevidence."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

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

        comms_budget_statuses = [
            _make_budget_status("POLL_GROUP", "pg1", utilization=0.60),
        ]
        comms_health_statuses = [
            _make_health_status("POLL_GROUP", "pg1", timeout_rate=0.0, jitter_ms=50.0),
        ]

        candidates = score_candidates(
            snapshot,
            index,
            evidence,
            observations,
            state,
            config,
            comms_budget_statuses=comms_budget_statuses,
            comms_health_statuses=comms_health_statuses,
        )

        pg1_candidate = next((c for c in candidates if c.node_id == "pg1"), None)
        assert pg1_candidate is not None
        assert pg1_candidate.score_components["comms_boost"] == 0.0
        assert pg1_candidate.score_components["comms_counter"] > 0.0

    def test_non_comms_fault_does_not_trigger_boost(self, test_topology):
        """Non-comms faults should not get comms boost even with utilization."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="drift"),
            "sig2": LeafObservation("sig2", is_affected=True, cause="noise"),
            "sig3": LeafObservation("sig3", is_affected=False),
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

        comms_budget_statuses = [
            _make_budget_status("COMMS_DOMAIN", "cd1", utilization=0.95),
        ]
        comms_health_statuses = [
            _make_health_status("COMMS_DOMAIN", "cd1", timeout_rate=0.12, jitter_ms=900.0),
        ]

        candidates = score_candidates(
            snapshot,
            index,
            evidence,
            observations,
            state,
            config,
            comms_budget_statuses=comms_budget_statuses,
            comms_health_statuses=comms_health_statuses,
        )

        cd1_candidate = next((c for c in candidates if c.node_id == "cd1"), None)
        assert cd1_candidate is not None
        assert cd1_candidate.score_components["leaf_comms_likeness"] == 0.0
        assert cd1_candidate.score_components["comms_boost"] == 0.0
        assert cd1_candidate.score_components["comms_counter"] == 0.0
        primary, _ = get_primary_and_secondary(candidates)
        assert primary is not None
        assert primary.node_type != "comms_domain"

    def test_comms_scoring_deterministic_components(self, test_topology):
        """Comms scoring should be deterministic with identical inputs."""
        snapshot, index = test_topology
        config = get_default_scoring_config()

        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="missing"),
            "sig2": LeafObservation("sig2", is_affected=True, cause="missing"),
            "sig3": LeafObservation("sig3", is_affected=False),
            "sig4": LeafObservation("sig4", is_affected=False),
            "sig5": LeafObservation("sig5", is_affected=False),
            "sig6": LeafObservation("sig6", is_affected=False),
            "sig7": LeafObservation("sig7", is_affected=False),
            "sig8": LeafObservation("sig8", is_affected=False),
        }

        comms_budget_statuses = [
            _make_budget_status("POLL_GROUP", "pg1", utilization=0.95),
        ]
        comms_health_statuses = [
            _make_health_status("POLL_GROUP", "pg1", timeout_rate=0.12, jitter_ms=900.0),
        ]

        state1 = RCAState()
        evidence1 = aggregate_node_evidence(
            snapshot, index, observations, state1,
            scan_index=1, scan_timestamp=1.0,
        )
        candidates1 = score_candidates(
            snapshot,
            index,
            evidence1,
            observations,
            state1,
            config,
            comms_budget_statuses=comms_budget_statuses,
            comms_health_statuses=comms_health_statuses,
        )

        state2 = RCAState()
        evidence2 = aggregate_node_evidence(
            snapshot, index, observations, state2,
            scan_index=1, scan_timestamp=1.0,
        )
        candidates2 = score_candidates(
            snapshot,
            index,
            evidence2,
            observations,
            state2,
            config,
            comms_budget_statuses=comms_budget_statuses,
            comms_health_statuses=comms_health_statuses,
        )

        assert [c.node_id for c in candidates1] == [c.node_id for c in candidates2]
        for c1, c2 in zip(candidates1, candidates2):
            assert c1.score_components == c2.score_components


class TestConfidence:
    """Test confidence computation."""

    def test_confidence_increases_with_stability(self, test_topology):
        """Confidence should increase when candidate is stable across scans."""
        snapshot, index = test_topology
        state = RCAState()
        scoring_config = get_default_scoring_config()
        confidence_config = get_default_confidence_config()

        observations = {
            f"sig{i}": LeafObservation(f"sig{i}", is_affected=True, cause="missing")
            for i in range(1, 9)
        }

        confidences = []
        for scan in range(1, 5):
            state.advance_scan(scan)
            evidence = aggregate_node_evidence(
                snapshot, index, observations, state,
                scan_index=scan, scan_timestamp=float(scan),
            )
            candidates = score_candidates(
                snapshot, index, evidence, observations, state, scoring_config,
            )
            compute_all_confidences(candidates, state, confidence_config)

            if candidates:
                confidences.append(candidates[0].confidence)

        # Confidence should increase over scans
        assert len(confidences) >= 3
        assert confidences[-1] >= confidences[0]

    def test_confidence_margin_effect(self, test_topology):
        """Confidence should be higher when margin over runner-up is larger."""
        snapshot, index = test_topology
        state = RCAState()
        confidence_config = get_default_confidence_config()

        # Create two candidates with different margins
        evidence1 = NodeEvidence(
            node_id="pg1", node_type="poll_group",
            scan_index=1, scan_timestamp=1.0,
            total_children=4, affected_children=4,
            affected_fraction=1.0, coherence_score=1.0,
        )
        evidence2 = NodeEvidence(
            node_id="pg2", node_type="poll_group",
            scan_index=1, scan_timestamp=1.0,
            total_children=4, affected_children=2,
            affected_fraction=0.5, coherence_score=0.5,
        )

        from sqe.rca.schema import RootCauseCandidate

        # High-scoring primary with large margin
        primary_high = RootCauseCandidate(
            node_id="pg1", node_type="poll_group",
            score=0.9, score_components={}, confidence=0.0,
            evidence=evidence1,
        )
        runner_up_low = RootCauseCandidate(
            node_id="pg2", node_type="poll_group",
            score=0.3, score_components={}, confidence=0.0,
            evidence=evidence2,
        )

        conf_high_margin = compute_confidence(
            primary_high, runner_up_low, state, confidence_config,
        )

        # Same primary but smaller margin
        state2 = RCAState()
        runner_up_close = RootCauseCandidate(
            node_id="pg2", node_type="poll_group",
            score=0.85, score_components={}, confidence=0.0,
            evidence=evidence2,
        )

        conf_low_margin = compute_confidence(
            primary_high, runner_up_close, state2, confidence_config,
        )

        assert conf_high_margin > conf_low_margin

    def test_confidence_no_runner_up(self, test_topology):
        """Confidence with no runner-up should be high (uncontested)."""
        snapshot, index = test_topology
        state = RCAState()
        confidence_config = get_default_confidence_config()

        evidence = NodeEvidence(
            node_id="cd1", node_type="comms_domain",
            scan_index=1, scan_timestamp=1.0,
            total_children=8, affected_children=8,
            affected_fraction=1.0, coherence_score=1.0,
        )

        from sqe.rca.schema import RootCauseCandidate

        primary = RootCauseCandidate(
            node_id="cd1", node_type="comms_domain",
            score=0.9, score_components={}, confidence=0.0,
            evidence=evidence,
        )

        conf = compute_confidence(primary, None, state, confidence_config)

        # No runner-up = full margin term
        assert conf > 0.5

    def test_confidence_assessment_labels(self):
        """Test confidence assessment label mapping."""
        assert get_confidence_assessment(0.95) == "VERY_HIGH"
        assert get_confidence_assessment(0.80) == "HIGH"
        assert get_confidence_assessment(0.60) == "MODERATE"
        assert get_confidence_assessment(0.30) == "LOW"
        assert get_confidence_assessment(0.10) == "VERY_LOW"


class TestScoreComponents:
    """Test individual score component computation."""

    def test_coverage_component(self, test_topology):
        """Coverage should equal affected_fraction."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

        observations = {
            "sig1": LeafObservation("sig1", is_affected=True, cause="missing"),
            "sig2": LeafObservation("sig2", is_affected=True, cause="missing"),
            "sig3": LeafObservation("sig3", is_affected=False),
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

        candidates = score_candidates(
            snapshot, index, evidence, observations, state, config,
        )

        # rtu1 has 2/2 affected = 1.0 coverage
        rtu1_candidate = next((c for c in candidates if c.node_id == "rtu1"), None)
        assert rtu1_candidate is not None
        assert rtu1_candidate.score_components["coverage"] == 1.0

        # cd1 has 2/8 affected = 0.25 coverage
        cd1_candidate = next((c for c in candidates if c.node_id == "cd1"), None)
        assert cd1_candidate is not None
        assert cd1_candidate.score_components["coverage"] == 0.25

    def test_coherence_component(self, test_topology):
        """Coherence should be high when all affected at same onset."""
        snapshot, index = test_topology
        state = RCAState()
        config = get_default_scoring_config()

        # All signals affected at same scan
        observations = {
            f"sig{i}": LeafObservation(f"sig{i}", is_affected=True, cause="missing")
            for i in range(1, 9)
        }

        evidence = aggregate_node_evidence(
            snapshot, index, observations, state,
            scan_index=1, scan_timestamp=1.0,
        )

        candidates = score_candidates(
            snapshot, index, evidence, observations, state, config,
        )

        # All at same onset = coherence = 1.0
        cd1_candidate = next((c for c in candidates if c.node_id == "cd1"), None)
        assert cd1_candidate is not None
        assert cd1_candidate.score_components["coherence"] == 1.0


class TestMinFractionThreshold:
    """Test minimum fraction threshold filtering."""

    def test_filters_by_min_fraction(self, test_topology):
        """Candidates below min fraction should be filtered out."""
        snapshot, index = test_topology
        state = RCAState()

        # Config with high threshold for comms_domain
        config = ScoringConfig(
            weights={"coverage": 0.45, "concentration": 0.25, "coherence": 0.2, "signature": 0.1},
            min_fraction_by_type={
                "comms_domain": 0.9,  # Very high threshold
                "poll_group": 0.25,
                "rtu": 0.50,
                "signal": 1.00,
            },
        )

        # Only 50% of signals affected
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

        candidates = score_candidates(
            snapshot, index, evidence, observations, state, config,
        )

        # cd1 has 50% affected but threshold is 90%, should not be candidate
        cd1_candidate = next((c for c in candidates if c.node_id == "cd1"), None)
        assert cd1_candidate is None

        # pg1 has 100% affected with 25% threshold, should be candidate
        pg1_candidate = next((c for c in candidates if c.node_id == "pg1"), None)
        assert pg1_candidate is not None
