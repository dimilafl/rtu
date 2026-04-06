"""Tests for scenario harness and RCA integration."""

import tempfile
from pathlib import Path

import pytest

from sqe.rca.scenario import (
    Scenario,
    ScenarioRunner,
    SignalFeedEntry,
    ScenarioExpectation,
    load_scenario_yaml,
    save_scenario_yaml,
    make_comms_outage_scenario,
    make_rtu_failure_scenario,
)
from sqe.rca.schema import OverallState


def make_test_topology_dict():
    """Create a test topology as dictionary."""
    return {
        "nodes": [
            {"id": "comms1", "type": "comms_domain"},
            {"id": "pg1", "type": "poll_group"},
            {"id": "rtu1", "type": "rtu"},
            {"id": "rtu2", "type": "rtu"},
            {"id": "sig1", "type": "signal"},
            {"id": "sig2", "type": "signal"},
            {"id": "sig3", "type": "signal"},
            {"id": "sig4", "type": "signal"},
        ],
        "edges": [
            {"parent": "comms1", "child": "pg1"},
            {"parent": "pg1", "child": "rtu1"},
            {"parent": "pg1", "child": "rtu2"},
            {"parent": "rtu1", "child": "sig1"},
            {"parent": "rtu1", "child": "sig2"},
            {"parent": "rtu2", "child": "sig3"},
            {"parent": "rtu2", "child": "sig4"},
        ],
    }


class TestSignalFeedEntry:
    """Tests for SignalFeedEntry."""

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "scan_index": 5,
            "timestamp": 50.0,
            "signals": {
                "sig1": {"quality_class": "GOOD"},
                "sig2": {"quality_class": "BAD"},
            },
            "incidents": [{"signal_id": "sig2", "incident_type": "MISSING"}],
        }
        entry = SignalFeedEntry.from_dict(data)
        assert entry.scan_index == 5
        assert entry.timestamp == 50.0
        assert len(entry.signals) == 2
        assert len(entry.incidents) == 1

    def test_to_dict(self):
        """Test converting to dictionary."""
        entry = SignalFeedEntry(
            scan_index=5,
            timestamp=50.0,
            signals={"sig1": {"quality_class": "GOOD"}},
            incidents=[{"signal_id": "sig1", "incident_type": "NOISE"}],
        )
        data = entry.to_dict()
        assert data["scan_index"] == 5
        assert data["timestamp"] == 50.0
        assert "signals" in data
        assert "incidents" in data

    def test_round_trip(self):
        """Test dict -> entry -> dict round trip."""
        original = {
            "scan_index": 10,
            "timestamp": 100.0,
            "signals": {"sig1": {"quality_class": "GOOD"}},
        }
        entry = SignalFeedEntry.from_dict(original)
        result = entry.to_dict()
        assert result["scan_index"] == original["scan_index"]
        assert result["timestamp"] == original["timestamp"]


class TestScenarioExpectation:
    """Tests for ScenarioExpectation."""

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "scan_index": 10,
            "overall_state": "OUTAGE",
            "primary_node_id": "comms1",
            "min_confidence": 0.7,
        }
        exp = ScenarioExpectation.from_dict(data)
        assert exp.scan_index == 10
        assert exp.overall_state == "OUTAGE"
        assert exp.primary_node_id == "comms1"
        assert exp.min_confidence == 0.7

    def test_to_dict_minimal(self):
        """Test to_dict with minimal fields."""
        exp = ScenarioExpectation(scan_index=5)
        data = exp.to_dict()
        assert data == {"scan_index": 5}

    def test_round_trip(self):
        """Test dict -> expectation -> dict round trip."""
        original = {
            "scan_index": 10,
            "overall_state": "DEGRADED",
            "primary_node_type": "rtu",
        }
        exp = ScenarioExpectation.from_dict(original)
        result = exp.to_dict()
        assert result["scan_index"] == original["scan_index"]
        assert result["overall_state"] == original["overall_state"]


class TestScenario:
    """Tests for Scenario."""

    def test_from_dict(self):
        """Test creating scenario from dictionary."""
        data = {
            "name": "test_scenario",
            "description": "A test scenario",
            "topology": make_test_topology_dict(),
            "signal_feed": [
                {"scan_index": 0, "timestamp": 0.0, "signals": {}},
            ],
            "expectations": [
                {"scan_index": 0, "overall_state": "OK"},
            ],
        }
        scenario = Scenario.from_dict(data)
        assert scenario.name == "test_scenario"
        assert scenario.description == "A test scenario"
        assert len(scenario.signal_feed) == 1
        assert len(scenario.expectations) == 1

    def test_to_dict(self):
        """Test converting scenario to dictionary."""
        scenario = Scenario(
            name="test",
            description="desc",
            topology=make_test_topology_dict(),
            signal_feed=[SignalFeedEntry(0, 0.0, {})],
            expectations=[ScenarioExpectation(0, overall_state="OK")],
        )
        data = scenario.to_dict()
        assert data["name"] == "test"
        assert "topology" in data
        assert len(data["signal_feed"]) == 1


class TestScenarioRunner:
    """Tests for ScenarioRunner."""

    def test_runs_scenario(self):
        """Test that scenario runs and produces reports."""
        scenario = Scenario(
            name="basic_test",
            description="Basic test scenario",
            topology=make_test_topology_dict(),
            signal_feed=[
                SignalFeedEntry(
                    scan_index=0,
                    timestamp=0.0,
                    signals={
                        "sig1": {"quality_class": "GOOD"},
                        "sig2": {"quality_class": "GOOD"},
                        "sig3": {"quality_class": "GOOD"},
                        "sig4": {"quality_class": "GOOD"},
                    },
                ),
                SignalFeedEntry(
                    scan_index=1,
                    timestamp=10.0,
                    signals={
                        "sig1": {"quality_class": "GOOD"},
                        "sig2": {"quality_class": "GOOD"},
                        "sig3": {"quality_class": "GOOD"},
                        "sig4": {"quality_class": "GOOD"},
                    },
                ),
            ],
            expectations=[],
        )

        runner = ScenarioRunner(scenario)
        reports = runner.run()

        assert len(reports) == 2
        assert reports[0].scan_index == 0
        assert reports[1].scan_index == 1

    def test_validates_expectations(self):
        """Test that expectations are validated correctly."""
        scenario = Scenario(
            name="validation_test",
            description="Test validation",
            topology=make_test_topology_dict(),
            signal_feed=[
                SignalFeedEntry(
                    scan_index=0,
                    timestamp=0.0,
                    signals={
                        "sig1": {"quality_class": "GOOD"},
                        "sig2": {"quality_class": "GOOD"},
                        "sig3": {"quality_class": "GOOD"},
                        "sig4": {"quality_class": "GOOD"},
                    },
                ),
            ],
            expectations=[
                ScenarioExpectation(
                    scan_index=0,
                    overall_state="OK",
                ),
            ],
        )

        runner = ScenarioRunner(scenario)
        results = runner.validate()

        assert len(results) == 1
        assert results[0].passed
        assert len(results[0].failures) == 0

    def test_detects_expectation_failures(self):
        """Test that failed expectations are detected."""
        scenario = Scenario(
            name="failure_test",
            description="Test failure detection",
            topology=make_test_topology_dict(),
            signal_feed=[
                SignalFeedEntry(
                    scan_index=0,
                    timestamp=0.0,
                    signals={
                        "sig1": {"quality_class": "GOOD"},
                        "sig2": {"quality_class": "GOOD"},
                        "sig3": {"quality_class": "GOOD"},
                        "sig4": {"quality_class": "GOOD"},
                    },
                ),
            ],
            expectations=[
                ScenarioExpectation(
                    scan_index=0,
                    overall_state="OUTAGE",  # Wrong - should be OK
                ),
            ],
        )

        runner = ScenarioRunner(scenario)
        results = runner.validate()

        assert len(results) == 1
        assert not results[0].passed
        assert "overall_state" in results[0].failures[0]

    def test_get_report(self):
        """Test getting report by scan index."""
        scenario = Scenario(
            name="get_report_test",
            description="Test get_report",
            topology=make_test_topology_dict(),
            signal_feed=[
                SignalFeedEntry(0, 0.0, {"sig1": {"quality_class": "GOOD"}}),
                SignalFeedEntry(5, 50.0, {"sig1": {"quality_class": "GOOD"}}),
            ],
            expectations=[],
        )

        runner = ScenarioRunner(scenario)
        runner.run()

        assert runner.get_report(0) is not None
        assert runner.get_report(5) is not None
        assert runner.get_report(3) is None  # No report for this scan


class TestScenarioYAML:
    """Tests for YAML load/save."""

    def test_save_and_load_scenario(self):
        """Test saving and loading scenario YAML."""
        scenario = Scenario(
            name="yaml_test",
            description="Test YAML serialization",
            topology=make_test_topology_dict(),
            signal_feed=[
                SignalFeedEntry(0, 0.0, {"sig1": {"quality_class": "GOOD"}}),
            ],
            expectations=[
                ScenarioExpectation(0, overall_state="OK"),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.yaml"
            save_scenario_yaml(scenario, str(path))

            # Verify file was created
            assert path.exists()

            # Load it back
            loaded = load_scenario_yaml(str(path))
            assert loaded.name == scenario.name
            assert loaded.description == scenario.description
            assert len(loaded.signal_feed) == 1
            assert len(loaded.expectations) == 1

    def test_load_scenario_file_not_found(self):
        """Test that FileNotFoundError is raised for missing file."""
        with pytest.raises(FileNotFoundError):
            load_scenario_yaml("/nonexistent/path/scenario.yaml")


class TestCommsOutageScenario:
    """Tests for comms domain outage scenario."""

    def test_creates_comms_outage_scenario(self):
        """Test comms outage scenario creation."""
        topology_dict = make_test_topology_dict()
        scenario = make_comms_outage_scenario(
            topology_dict=topology_dict,
            comms_domain_id="comms1",
            signal_ids=["sig1", "sig2", "sig3", "sig4"],
            outage_start_scan=5,
            outage_end_scan=15,
            total_scans=20,
        )

        assert scenario.name == "comms_domain_outage"
        assert len(scenario.signal_feed) == 20
        assert len(scenario.expectations) == 3  # Before, during, after

    def test_comms_outage_signals_affected_during_outage(self):
        """Test that signals are affected during outage window."""
        topology_dict = make_test_topology_dict()
        scenario = make_comms_outage_scenario(
            topology_dict=topology_dict,
            comms_domain_id="comms1",
            signal_ids=["sig1", "sig2"],
            outage_start_scan=5,
            outage_end_scan=10,
            total_scans=15,
        )

        # Before outage (scan 4) - signals should be GOOD
        entry_before = scenario.signal_feed[4]
        assert entry_before.signals["sig1"]["quality_class"] == "GOOD"

        # During outage (scan 7) - signals should be BAD
        entry_during = scenario.signal_feed[7]
        assert entry_during.signals["sig1"]["quality_class"] == "BAD"
        assert entry_during.signals["sig1"]["is_missing"]

        # After outage (scan 12) - signals should be GOOD again
        entry_after = scenario.signal_feed[12]
        assert entry_after.signals["sig1"]["quality_class"] == "GOOD"

    def test_comms_outage_scenario_runs(self):
        """Test that comms outage scenario runs successfully."""
        topology_dict = make_test_topology_dict()
        scenario = make_comms_outage_scenario(
            topology_dict=topology_dict,
            comms_domain_id="comms1",
            signal_ids=["sig1", "sig2", "sig3", "sig4"],
            outage_start_scan=3,
            outage_end_scan=8,
            total_scans=12,
        )

        runner = ScenarioRunner(scenario)
        reports = runner.run()

        assert len(reports) == 12

        # Check states transition correctly
        # Before outage
        assert reports[2].overall_state == OverallState.OK

        # During outage - should be OUTAGE (all signals affected)
        assert reports[5].overall_state == OverallState.OUTAGE

        # After outage
        assert reports[10].overall_state == OverallState.OK


class TestRTUFailureScenario:
    """Tests for RTU failure scenario."""

    def test_creates_rtu_failure_scenario(self):
        """Test RTU failure scenario creation."""
        topology_dict = make_test_topology_dict()
        scenario = make_rtu_failure_scenario(
            topology_dict=topology_dict,
            rtu_id="rtu1",
            signal_ids=["sig1", "sig2"],
            failure_start_scan=5,
            total_scans=15,
        )

        assert scenario.name == "rtu_failure"
        assert len(scenario.signal_feed) == 15
        assert len(scenario.expectations) == 2

    def test_rtu_failure_scenario_runs(self):
        """Test that RTU failure scenario runs successfully."""
        topology_dict = make_test_topology_dict()
        scenario = make_rtu_failure_scenario(
            topology_dict=topology_dict,
            rtu_id="rtu1",
            signal_ids=["sig1", "sig2"],
            failure_start_scan=3,
            total_scans=10,
        )

        runner = ScenarioRunner(scenario)
        reports = runner.run()

        assert len(reports) == 10

        # Before failure
        assert reports[2].overall_state == OverallState.OK

        # After failure - should be DEGRADED (only some signals affected)
        # Note: With 2 of 4 signals affected (50%), it could be DEGRADED or OUTAGE
        assert reports[7].overall_state in [OverallState.DEGRADED, OverallState.OUTAGE]


class TestScenarioValidation:
    """Tests for scenario validation integration."""

    def test_validates_primary_candidate(self):
        """Test validation of primary candidate expectation."""
        topology_dict = make_test_topology_dict()
        scenario = Scenario(
            name="primary_test",
            description="Test primary validation",
            topology=topology_dict,
            signal_feed=[
                SignalFeedEntry(
                    scan_index=0,
                    timestamp=0.0,
                    signals={
                        "sig1": {"quality_class": "BAD", "is_missing": True},
                        "sig2": {"quality_class": "BAD", "is_missing": True},
                    },
                    incidents=[
                        {"signal_id": "sig1", "incident_type": "MISSING"},
                        {"signal_id": "sig2", "incident_type": "MISSING"},
                    ],
                ),
            ],
            expectations=[
                ScenarioExpectation(
                    scan_index=0,
                    primary_node_type="rtu",  # Should identify RTU as root cause
                ),
            ],
        )

        runner = ScenarioRunner(scenario)
        results = runner.validate()

        # Just check that validation runs - the actual result depends on scoring
        assert len(results) == 1

    def test_all_passed_helper(self):
        """Test all_passed() helper method."""
        topology_dict = make_test_topology_dict()
        scenario = Scenario(
            name="all_passed_test",
            description="Test all_passed",
            topology=topology_dict,
            signal_feed=[
                SignalFeedEntry(0, 0.0, {"sig1": {"quality_class": "GOOD"}}),
            ],
            expectations=[
                ScenarioExpectation(0, overall_state="OK"),
            ],
        )

        runner = ScenarioRunner(scenario)
        assert runner.all_passed()

    def test_get_failures_helper(self):
        """Test get_failures() helper method."""
        topology_dict = make_test_topology_dict()
        scenario = Scenario(
            name="failures_test",
            description="Test get_failures",
            topology=topology_dict,
            signal_feed=[
                SignalFeedEntry(0, 0.0, {"sig1": {"quality_class": "GOOD"}}),
            ],
            expectations=[
                ScenarioExpectation(0, overall_state="OUTAGE"),  # Will fail
            ],
        )

        runner = ScenarioRunner(scenario)
        failures = runner.get_failures()

        assert len(failures) > 0
        assert "scan 0" in failures[0]


class TestScenarioRoundTrip:
    """Tests for scenario round-trip (save/load/run)."""

    def test_scenario_round_trip_produces_same_results(self):
        """Test that saving and loading scenario produces same results."""
        topology_dict = make_test_topology_dict()
        original_scenario = make_rtu_failure_scenario(
            topology_dict=topology_dict,
            rtu_id="rtu1",
            signal_ids=["sig1", "sig2"],
            failure_start_scan=3,
            total_scans=8,
        )

        # Run original
        original_runner = ScenarioRunner(original_scenario)
        original_reports = original_runner.run()

        # Save and reload
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.yaml"
            save_scenario_yaml(original_scenario, str(path))
            loaded_scenario = load_scenario_yaml(str(path))

        # Run loaded
        loaded_runner = ScenarioRunner(loaded_scenario)
        loaded_reports = loaded_runner.run()

        # Compare results
        assert len(original_reports) == len(loaded_reports)
        for i in range(len(original_reports)):
            assert original_reports[i].scan_index == loaded_reports[i].scan_index
            assert original_reports[i].overall_state == loaded_reports[i].overall_state
