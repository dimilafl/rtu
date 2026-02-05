"""Tests for troubleshoot report generation."""

from __future__ import annotations

import json

import pytest

from sqe.topology.loader import load_topology_dict
from sqe.topology.index import TopologyIndex
from sqe.comms.budget import UtilizationStatus
from sqe.comms.health import CommsHealthClass, CommsHealthStatus
from sqe.rca.schema import (
    LeafObservation,
    TroubleshootReport,
    OverallState,
    SCHEMA_VERSION,
)
from sqe.rca.engine import RCAEngine, create_rca_engine_from_config


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
    return load_topology_dict(data)


class TestTroubleshootReport:
    """Test troubleshoot report structure and serialization."""

    def test_schema_version_present(self, test_topology):
        """Test that schema version is present in report."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "GOOD", "sqi": 90.0}
            for i in range(1, 9)
        }

        report = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)

        assert report.schema_version == SCHEMA_VERSION

    def test_ordering_deterministic(self, test_topology):
        """Test that report ordering is deterministic."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "POOR", "sqi": 30.0}
            for i in range(1, 9)
        }

        # Generate two reports
        engine.reset()
        report1 = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)
        dict1 = report1.to_dict()

        engine.reset()
        report2 = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)
        dict2 = report2.to_dict()

        # JSON serialization should be identical
        json1 = json.dumps(dict1, sort_keys=True)
        json2 = json.dumps(dict2, sort_keys=True)

        assert json1 == json2

    def test_bounded_list_lengths_enforced(self, test_topology):
        """Test that list lengths are bounded."""
        engine = RCAEngine(
            test_topology,
            representative_signals_max=3,
            supporting_incidents_max=5,
        )

        # All signals affected
        processed = {
            f"sig{i}": {"quality_class": "POOR", "sqi": 20.0}
            for i in range(1, 9)
        }

        # Many incidents
        incidents = [
            {"signal_id": f"sig{i}", "event_type": "started", "cause": "missing", "sqi": 20.0}
            for i in range(1, 9)
        ]

        report = engine.analyze(
            processed,
            scan_index=1,
            scan_timestamp=1.0,
            incident_events=incidents,
        )

        # Supporting incidents bounded
        assert len(report.supporting_incidents) <= 5

        # Representative signals bounded (in primary candidate)
        if report.primary:
            assert len(report.primary.representative_signals) <= 3

    def test_overall_state_ok(self, test_topology):
        """Test OK state when no signals affected."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "GOOD", "sqi": 95.0}
            for i in range(1, 9)
        }

        report = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)

        assert report.overall_state == OverallState.OK
        assert report.primary is None

    def test_overall_state_degraded(self, test_topology):
        """Test DEGRADED state when some signals affected."""
        engine = RCAEngine(test_topology)

        # 2 of 8 signals affected = 25% < 50%
        processed = {
            "sig1": {"quality_class": "POOR", "sqi": 30.0},
            "sig2": {"quality_class": "POOR", "sqi": 30.0},
            "sig3": {"quality_class": "GOOD", "sqi": 90.0},
            "sig4": {"quality_class": "GOOD", "sqi": 90.0},
            "sig5": {"quality_class": "GOOD", "sqi": 90.0},
            "sig6": {"quality_class": "GOOD", "sqi": 90.0},
            "sig7": {"quality_class": "GOOD", "sqi": 90.0},
            "sig8": {"quality_class": "GOOD", "sqi": 90.0},
        }

        report = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)

        assert report.overall_state == OverallState.DEGRADED

    def test_overall_state_outage(self, test_topology):
        """Test OUTAGE state when majority signals affected."""
        engine = RCAEngine(test_topology)

        # 6 of 8 signals affected = 75% > 50%
        processed = {
            f"sig{i}": {"quality_class": "POOR" if i <= 6 else "GOOD", "sqi": 30.0 if i <= 6 else 90.0}
            for i in range(1, 9)
        }

        report = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)

        assert report.overall_state == OverallState.OUTAGE

    def test_impacted_nodes_sorted(self, test_topology):
        """Test that impacted nodes are sorted."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "POOR", "sqi": 30.0}
            for i in range(1, 9)
        }

        report = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)

        # All node types should be present and sorted
        for node_type, node_ids in report.impacted_nodes.items():
            assert node_ids == sorted(node_ids)

    def test_comms_summary_included_when_provided(self, test_topology):
        """Test that comms summary is included and sorted."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "GOOD", "sqi": 90.0}
            for i in range(1, 9)
        }

        statuses = [
            CommsHealthStatus(
                node_id="rtu2",
                node_type="RTU",
                scan_index=1,
                scan_timestamp=1.0,
                timeout_rate=0.4,
                retry_rate=0.0,
                crc_error_rate=0.0,
                avg_poll_cycle_ms=1000.0,
                avg_jitter_ms=10.0,
                bytes_tx_total=100,
                bytes_rx_total=200,
                health_class=CommsHealthClass.CRITICAL,
                reasons=["timeout_rate_critical"],
            ),
            CommsHealthStatus(
                node_id="rtu1",
                node_type="RTU",
                scan_index=1,
                scan_timestamp=1.0,
                timeout_rate=0.9,
                retry_rate=0.0,
                crc_error_rate=0.0,
                avg_poll_cycle_ms=1000.0,
                avg_jitter_ms=10.0,
                bytes_tx_total=100,
                bytes_rx_total=200,
                health_class=CommsHealthClass.CRITICAL,
                reasons=["timeout_rate_critical"],
            ),
            CommsHealthStatus(
                node_id="pg1",
                node_type="POLL_GROUP",
                scan_index=1,
                scan_timestamp=1.0,
                timeout_rate=0.2,
                retry_rate=0.0,
                crc_error_rate=0.0,
                avg_poll_cycle_ms=1000.0,
                avg_jitter_ms=10.0,
                bytes_tx_total=100,
                bytes_rx_total=200,
                health_class=CommsHealthClass.DEGRADED,
                reasons=["timeout_rate_degraded"],
            ),
        ]

        report = engine.analyze(
            processed,
            scan_index=1,
            scan_timestamp=1.0,
            comms_health_statuses=statuses,
            comms_report_top_n=10,
        )

        assert report.comms_summary is not None
        critical = report.comms_summary.critical_nodes
        degraded = report.comms_summary.degraded_nodes
        assert [status.node_id for status in critical] == ["rtu1", "rtu2"]
        assert [status.node_id for status in degraded] == ["pg1"]
        assert "comms_summary" in report.to_dict()

    def test_comms_budget_summary_included_when_provided(self, test_topology):
        """Test that comms budget summary is included and sorted."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "GOOD", "sqi": 90.0}
            for i in range(1, 9)
        }

        statuses = [
            UtilizationStatus(
                node_id="rtu2",
                node_type="RTU",
                scan_index=1,
                scan_timestamp=1.0,
                descendant_signal_count=2,
                expected_bytes=200,
                observed_bytes=1000,
                observed_bps=8000.0,
                utilization=0.95,
                headroom=0.05,
                level="CRITICAL",
                reasons=["UTILIZATION_CRITICAL"],
            ),
            UtilizationStatus(
                node_id="cd1",
                node_type="COMMS_DOMAIN",
                scan_index=1,
                scan_timestamp=1.0,
                descendant_signal_count=8,
                expected_bytes=300,
                observed_bytes=900,
                observed_bps=7200.0,
                utilization=0.92,
                headroom=0.08,
                level="CRITICAL",
                reasons=["UTILIZATION_CRITICAL"],
            ),
            UtilizationStatus(
                node_id="pg1",
                node_type="POLL_GROUP",
                scan_index=1,
                scan_timestamp=1.0,
                descendant_signal_count=4,
                expected_bytes=250,
                observed_bytes=600,
                observed_bps=4800.0,
                utilization=0.75,
                headroom=0.25,
                level="DEGRADED",
                reasons=["UTILIZATION_DEGRADED"],
            ),
            UtilizationStatus(
                node_id="rtu1",
                node_type="RTU",
                scan_index=1,
                scan_timestamp=1.0,
                descendant_signal_count=2,
                expected_bytes=210,
                observed_bytes=600,
                observed_bps=4800.0,
                utilization=0.75,
                headroom=0.25,
                level="DEGRADED",
                reasons=["UTILIZATION_DEGRADED"],
            ),
        ]

        report = engine.analyze(
            processed,
            scan_index=1,
            scan_timestamp=1.0,
            comms_budget_statuses=statuses,
            comms_budget_report_top_n=1,
        )

        assert report.comms_budget_summary is not None
        summary = report.comms_budget_summary
        assert summary.bottleneck_node is not None
        assert summary.bottleneck_node.node_id == "rtu2"
        assert [status.node_id for status in summary.critical_utilization_nodes] == [
            "rtu2"
        ]
        assert [status.node_id for status in summary.degraded_utilization_nodes] == [
            "pg1"
        ]
        assert "comms_budget_summary" in report.to_dict()

    def test_comms_budget_summary_deterministic(self, test_topology):
        """Test comms budget summary determinism across runs."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "GOOD", "sqi": 90.0}
            for i in range(1, 9)
        }

        statuses = [
            UtilizationStatus(
                node_id="pg1",
                node_type="POLL_GROUP",
                scan_index=1,
                scan_timestamp=1.0,
                descendant_signal_count=4,
                expected_bytes=250,
                observed_bytes=600,
                observed_bps=4800.0,
                utilization=0.8,
                headroom=0.2,
                level="DEGRADED",
                reasons=["UTILIZATION_DEGRADED"],
            ),
            UtilizationStatus(
                node_id="rtu1",
                node_type="RTU",
                scan_index=1,
                scan_timestamp=1.0,
                descendant_signal_count=2,
                expected_bytes=210,
                observed_bytes=700,
                observed_bps=5600.0,
                utilization=0.9,
                headroom=0.1,
                level="CRITICAL",
                reasons=["UTILIZATION_CRITICAL"],
            ),
        ]

        report1 = engine.analyze(
            processed,
            scan_index=1,
            scan_timestamp=1.0,
            comms_budget_statuses=statuses,
            comms_budget_report_top_n=10,
        )

        engine.reset()
        report2 = engine.analyze(
            processed,
            scan_index=1,
            scan_timestamp=1.0,
            comms_budget_statuses=statuses,
            comms_budget_report_top_n=10,
        )

        json1 = json.dumps(report1.to_dict(), sort_keys=True)
        json2 = json.dumps(report2.to_dict(), sort_keys=True)
        assert json1 == json2


class TestRCAEngine:
    """Test RCA engine functionality."""

    def test_analyze_returns_report(self, test_topology):
        """Test that analyze returns a TroubleshootReport."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "GOOD", "sqi": 90.0}
            for i in range(1, 9)
        }

        report = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)

        assert isinstance(report, TroubleshootReport)
        assert report.topology_version_hash == test_topology.version_hash

    def test_primary_candidate_present_on_outage(self, test_topology):
        """Test that primary candidate is present during outage."""
        engine = RCAEngine(test_topology)

        # All signals missing
        processed = {
            f"sig{i}": {"quality_class": "POOR", "sqi": 10.0}
            for i in range(1, 9)
        }

        report = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)

        assert report.primary is not None
        assert report.primary.node_type in ["comms_domain", "poll_group", "rtu", "signal"]

    def test_state_persistence_across_scans(self, test_topology):
        """Test that state persists across analyze calls."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "POOR", "sqi": 10.0}
            for i in range(1, 9)
        }

        # Multiple scans
        for scan in range(1, 5):
            report = engine.analyze(
                processed,
                scan_index=scan,
                scan_timestamp=float(scan),
            )

        # State should have signal entries
        assert engine.state.signal_count > 0

    def test_reset_clears_state(self, test_topology):
        """Test that reset clears engine state."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "POOR", "sqi": 10.0}
            for i in range(1, 9)
        }

        engine.analyze(processed, scan_index=1, scan_timestamp=1.0)
        assert engine.state.signal_count > 0

        engine.reset()
        assert engine.state.signal_count == 0


class TestCreateFromConfig:
    """Test engine creation from configuration."""

    def test_creates_engine_from_config(self, test_topology):
        """Test creating engine from configuration dict."""
        config = {
            "affected_policy": {
                "use_active_incidents": True,
                "use_quality_class": True,
                "affected_classes": ["POOR", "BAD"],
                "missing_ratio_threshold": 0.3,
            },
            "representative_signals_max": 10,
            "supporting_incidents_max": 20,
            "retention_scans": 1000,
            "scoring": {
                "weights": {
                    "coverage": 0.5,
                    "concentration": 0.2,
                    "coherence": 0.2,
                    "signature": 0.1,
                },
                "coherence_k_scans": 3,
            },
            "confidence": {
                "required_scans": 3,
                "margin_scale": 0.3,
            },
            "node_incidents": {
                "min_confidence_to_start": 0.5,
            },
        }

        engine = create_rca_engine_from_config(test_topology, config)

        assert engine is not None
        assert engine.topology_snapshot == test_topology

    def test_uses_defaults_for_missing_config(self, test_topology):
        """Test that defaults are used for missing config values."""
        config = {}  # Empty config

        engine = create_rca_engine_from_config(test_topology, config)

        assert engine is not None
        # Should use default values
        assert engine._representative_signals_max == 12


class TestReportSerialization:
    """Test report serialization."""

    def test_to_dict_stable_keys(self, test_topology):
        """Test that to_dict produces stable key ordering."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "POOR", "sqi": 20.0}
            for i in range(1, 9)
        }

        report = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)
        data = report.to_dict()

        # Check required keys
        assert "schema_version" in data
        assert "scan_index" in data
        assert "scan_timestamp" in data
        assert "topology_version_hash" in data
        assert "overall_state" in data
        assert "primary" in data
        assert "secondary" in data
        assert "impacted_nodes" in data
        assert "supporting_incidents" in data

    def test_json_serializable(self, test_topology):
        """Test that report can be serialized to JSON."""
        engine = RCAEngine(test_topology)

        processed = {
            f"sig{i}": {"quality_class": "POOR", "sqi": 20.0}
            for i in range(1, 9)
        }

        report = engine.analyze(processed, scan_index=1, scan_timestamp=1.0)

        # Should not raise
        json_str = json.dumps(report.to_dict())
        assert len(json_str) > 0

        # Should be parseable
        parsed = json.loads(json_str)
        assert parsed["schema_version"] == SCHEMA_VERSION
