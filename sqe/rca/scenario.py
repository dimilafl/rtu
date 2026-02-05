"""Scenario harness for offline RCA testing and validation.

Provides deterministic scenario replay for testing topology-aware RCA
with synthetic signal feeds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from sqe.topology.model import TopologySnapshot
from sqe.topology.loader import load_topology_dict, load_topology_yaml
from sqe.rca.engine import RCAEngine, create_rca_engine_from_config
from sqe.rca.schema import TroubleshootReport, OverallState


@dataclass
class SignalFeedEntry:
    """A single entry in the synthetic signal feed.

    Attributes:
        scan_index: Scan index for this entry
        timestamp: Timestamp for this scan
        signals: Dict of signal_id to signal state
        incidents: Optional list of active incidents
    """

    scan_index: int
    timestamp: float
    signals: Dict[str, Dict[str, Any]]
    incidents: Optional[List[Dict[str, Any]]] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "SignalFeedEntry":
        """Create from dictionary."""
        return SignalFeedEntry(
            scan_index=data["scan_index"],
            timestamp=data["timestamp"],
            signals=data.get("signals", {}),
            incidents=data.get("incidents"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "scan_index": self.scan_index,
            "timestamp": self.timestamp,
            "signals": self.signals,
        }
        if self.incidents:
            result["incidents"] = self.incidents
        return result


@dataclass
class ScenarioExpectation:
    """Expected outcome for a scenario scan.

    Attributes:
        scan_index: Scan to check
        overall_state: Expected overall state
        primary_node_id: Expected primary candidate node ID (optional)
        primary_node_type: Expected primary candidate node type (optional)
        min_confidence: Minimum expected confidence (optional)
        affected_count_min: Minimum number of affected signals (optional)
        impacted_nodes: Expected impacted nodes by type (optional)
    """

    scan_index: int
    overall_state: Optional[str] = None
    primary_node_id: Optional[str] = None
    primary_node_type: Optional[str] = None
    min_confidence: Optional[float] = None
    affected_count_min: Optional[int] = None
    impacted_nodes: Optional[Dict[str, List[str]]] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ScenarioExpectation":
        """Create from dictionary."""
        return ScenarioExpectation(
            scan_index=data["scan_index"],
            overall_state=data.get("overall_state"),
            primary_node_id=data.get("primary_node_id"),
            primary_node_type=data.get("primary_node_type"),
            min_confidence=data.get("min_confidence"),
            affected_count_min=data.get("affected_count_min"),
            impacted_nodes=data.get("impacted_nodes"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {"scan_index": self.scan_index}
        if self.overall_state:
            result["overall_state"] = self.overall_state
        if self.primary_node_id:
            result["primary_node_id"] = self.primary_node_id
        if self.primary_node_type:
            result["primary_node_type"] = self.primary_node_type
        if self.min_confidence is not None:
            result["min_confidence"] = self.min_confidence
        if self.affected_count_min is not None:
            result["affected_count_min"] = self.affected_count_min
        if self.impacted_nodes:
            result["impacted_nodes"] = self.impacted_nodes
        return result


@dataclass
class Scenario:
    """A complete test scenario for RCA validation.

    Attributes:
        name: Scenario name
        description: Scenario description
        topology: Topology data (dict or path to YAML file)
        signal_feed: List of signal feed entries
        expectations: List of expected outcomes
        rca_config: Optional RCA engine configuration
    """

    name: str
    description: str
    topology: Any  # Dict or str (path)
    signal_feed: List[SignalFeedEntry]
    expectations: List[ScenarioExpectation]
    rca_config: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Scenario":
        """Create from dictionary."""
        return Scenario(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            topology=data.get("topology", {}),
            signal_feed=[
                SignalFeedEntry.from_dict(e)
                for e in data.get("signal_feed", [])
            ],
            expectations=[
                ScenarioExpectation.from_dict(e)
                for e in data.get("expectations", [])
            ],
            rca_config=data.get("rca_config", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "topology": self.topology,
            "signal_feed": [e.to_dict() for e in self.signal_feed],
            "expectations": [e.to_dict() for e in self.expectations],
            "rca_config": self.rca_config,
        }


@dataclass
class ValidationResult:
    """Result of validating a scenario expectation.

    Attributes:
        scan_index: Scan index that was validated
        passed: Whether the validation passed
        failures: List of failure messages
        report: The TroubleshootReport that was generated
    """

    scan_index: int
    passed: bool
    failures: List[str]
    report: Optional[TroubleshootReport] = None


class ScenarioRunner:
    """Runs scenarios and validates expectations.

    Provides deterministic replay of scenarios for testing and validation.
    """

    def __init__(
        self,
        scenario: Scenario,
        topology_base_path: Optional[str] = None,
    ) -> None:
        """Initialize scenario runner.

        Args:
            scenario: Scenario to run
            topology_base_path: Base path for resolving topology file paths
        """
        self._scenario = scenario
        self._base_path = Path(topology_base_path) if topology_base_path else Path(".")

        # Load topology
        self._topology = self._load_topology()

        # Create RCA engine
        if scenario.rca_config:
            self._engine = create_rca_engine_from_config(
                self._topology,
                scenario.rca_config,
            )
        else:
            self._engine = RCAEngine(self._topology)

        # Results storage
        self._reports: Dict[int, TroubleshootReport] = {}
        self._results: List[ValidationResult] = []

    def _load_topology(self) -> TopologySnapshot:
        """Load topology from scenario."""
        topology_data = self._scenario.topology

        if isinstance(topology_data, str):
            # Path to YAML file
            path = self._base_path / topology_data
            return load_topology_yaml(str(path))
        elif isinstance(topology_data, dict):
            # Inline topology dict
            return load_topology_dict(topology_data)
        else:
            raise ValueError(
                f"Invalid topology type: {type(topology_data)}; "
                "must be str (path) or dict"
            )

    @property
    def topology(self) -> TopologySnapshot:
        """Get loaded topology."""
        return self._topology

    @property
    def engine(self) -> RCAEngine:
        """Get RCA engine."""
        return self._engine

    def run(self) -> List[TroubleshootReport]:
        """Run the scenario and return reports for each scan.

        Returns:
            List of TroubleshootReport for each scan in the feed
        """
        self._reports.clear()
        reports = []

        for entry in self._scenario.signal_feed:
            report = self._engine.analyze(
                processed_signals=entry.signals,
                scan_index=entry.scan_index,
                scan_timestamp=entry.timestamp,
                incident_events=entry.incidents,
            )
            self._reports[entry.scan_index] = report
            reports.append(report)

        return reports

    def validate(self) -> List[ValidationResult]:
        """Validate scenario expectations.

        Returns:
            List of ValidationResult for each expectation
        """
        # Run scenario if not already run
        if not self._reports:
            self.run()

        self._results.clear()

        for expectation in self._scenario.expectations:
            result = self._validate_expectation(expectation)
            self._results.append(result)

        return self._results

    def _validate_expectation(
        self,
        expectation: ScenarioExpectation,
    ) -> ValidationResult:
        """Validate a single expectation."""
        failures: List[str] = []
        report = self._reports.get(expectation.scan_index)

        if report is None:
            return ValidationResult(
                scan_index=expectation.scan_index,
                passed=False,
                failures=[f"No report for scan {expectation.scan_index}"],
            )

        # Check overall state
        if expectation.overall_state:
            expected_state = OverallState(expectation.overall_state)
            if report.overall_state != expected_state:
                failures.append(
                    f"overall_state: expected {expected_state.value}, "
                    f"got {report.overall_state.value}"
                )

        # Check primary candidate
        if expectation.primary_node_id:
            if report.primary is None:
                failures.append(
                    f"primary_node_id: expected {expectation.primary_node_id}, "
                    "got None (no primary candidate)"
                )
            elif report.primary.node_id != expectation.primary_node_id:
                failures.append(
                    f"primary_node_id: expected {expectation.primary_node_id}, "
                    f"got {report.primary.node_id}"
                )

        if expectation.primary_node_type:
            if report.primary is None:
                failures.append(
                    f"primary_node_type: expected {expectation.primary_node_type}, "
                    "got None (no primary candidate)"
                )
            elif report.primary.node_type != expectation.primary_node_type:
                failures.append(
                    f"primary_node_type: expected {expectation.primary_node_type}, "
                    f"got {report.primary.node_type}"
                )

        # Check minimum confidence
        if expectation.min_confidence is not None:
            if report.primary is None:
                failures.append(
                    f"min_confidence: expected >= {expectation.min_confidence}, "
                    "got None (no primary candidate)"
                )
            elif report.primary.confidence < expectation.min_confidence:
                failures.append(
                    f"min_confidence: expected >= {expectation.min_confidence}, "
                    f"got {report.primary.confidence}"
                )

        # Check impacted nodes
        if expectation.impacted_nodes:
            for node_type, expected_nodes in expectation.impacted_nodes.items():
                actual_nodes = report.impacted_nodes.get(node_type, [])
                missing = set(expected_nodes) - set(actual_nodes)
                if missing:
                    failures.append(
                        f"impacted_nodes[{node_type}]: missing {sorted(missing)}"
                    )

        return ValidationResult(
            scan_index=expectation.scan_index,
            passed=len(failures) == 0,
            failures=failures,
            report=report,
        )

    def get_report(self, scan_index: int) -> Optional[TroubleshootReport]:
        """Get report for a specific scan."""
        return self._reports.get(scan_index)

    def all_passed(self) -> bool:
        """Check if all validations passed."""
        if not self._results:
            self.validate()
        return all(r.passed for r in self._results)

    def get_failures(self) -> List[str]:
        """Get all failure messages."""
        if not self._results:
            self.validate()
        failures = []
        for result in self._results:
            if not result.passed:
                for failure in result.failures:
                    failures.append(f"scan {result.scan_index}: {failure}")
        return failures


def load_scenario_yaml(path: str) -> Scenario:
    """Load scenario from YAML file.

    Args:
        path: Path to scenario YAML file

    Returns:
        Loaded Scenario
    """
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    with open(path_obj, "r") as f:
        data = yaml.safe_load(f)

    return Scenario.from_dict(data)


def save_scenario_yaml(scenario: Scenario, path: str) -> None:
    """Save scenario to YAML file.

    Args:
        scenario: Scenario to save
        path: Path to save to
    """
    with open(path, "w") as f:
        yaml.dump(scenario.to_dict(), f, default_flow_style=False, sort_keys=False)


def make_comms_outage_scenario(
    topology_dict: Dict[str, Any],
    comms_domain_id: str,
    signal_ids: List[str],
    outage_start_scan: int = 5,
    outage_end_scan: int = 15,
    total_scans: int = 20,
) -> Scenario:
    """Create a comms domain outage scenario for testing.

    Args:
        topology_dict: Topology as dictionary
        comms_domain_id: ID of the comms domain that has outage
        signal_ids: List of signal IDs affected by the outage
        outage_start_scan: Scan when outage starts
        outage_end_scan: Scan when outage ends
        total_scans: Total number of scans in scenario

    Returns:
        Scenario configured for comms outage testing
    """
    signal_feed = []

    for scan_idx in range(total_scans):
        timestamp = float(scan_idx * 10)
        signals: Dict[str, Dict[str, Any]] = {}
        incidents: List[Dict[str, Any]] = []

        for sig_id in signal_ids:
            if outage_start_scan <= scan_idx < outage_end_scan:
                # During outage: signals are missing/stale
                signals[sig_id] = {
                    "quality_class": "BAD",
                    "is_missing": True,
                    "is_stale": True,
                }
                incidents.append({
                    "signal_id": sig_id,
                    "incident_type": "MISSING",
                    "sqi": 0.0,
                })
            else:
                # Normal operation
                signals[sig_id] = {
                    "quality_class": "GOOD",
                    "is_missing": False,
                    "is_stale": False,
                }

        signal_feed.append(SignalFeedEntry(
            scan_index=scan_idx,
            timestamp=timestamp,
            signals=signals,
            incidents=incidents if incidents else None,
        ))

    # Set expectations
    expectations = []

    # Before outage: OK state
    expectations.append(ScenarioExpectation(
        scan_index=outage_start_scan - 1,
        overall_state="OK",
    ))

    # During outage: OUTAGE state with comms domain as primary
    mid_outage = (outage_start_scan + outage_end_scan) // 2
    expectations.append(ScenarioExpectation(
        scan_index=mid_outage,
        overall_state="OUTAGE",
        primary_node_type="comms_domain",
    ))

    # After outage: back to OK
    if outage_end_scan < total_scans:
        expectations.append(ScenarioExpectation(
            scan_index=outage_end_scan + 2,
            overall_state="OK",
        ))

    return Scenario(
        name="comms_domain_outage",
        description=f"Simulated comms domain outage for {comms_domain_id}",
        topology=topology_dict,
        signal_feed=signal_feed,
        expectations=expectations,
    )


def make_rtu_failure_scenario(
    topology_dict: Dict[str, Any],
    rtu_id: str,
    signal_ids: List[str],
    failure_start_scan: int = 5,
    total_scans: int = 15,
) -> Scenario:
    """Create an RTU failure scenario for testing.

    Args:
        topology_dict: Topology as dictionary
        rtu_id: ID of the RTU that fails
        signal_ids: List of signal IDs under the failing RTU
        failure_start_scan: Scan when failure starts
        total_scans: Total number of scans in scenario

    Returns:
        Scenario configured for RTU failure testing
    """
    signal_feed = []

    for scan_idx in range(total_scans):
        timestamp = float(scan_idx * 10)
        signals: Dict[str, Dict[str, Any]] = {}
        incidents: List[Dict[str, Any]] = []

        for sig_id in signal_ids:
            if scan_idx >= failure_start_scan:
                # After failure: signals are missing
                signals[sig_id] = {
                    "quality_class": "BAD",
                    "is_missing": True,
                    "is_stale": False,
                }
                incidents.append({
                    "signal_id": sig_id,
                    "incident_type": "MISSING",
                    "sqi": 0.0,
                })
            else:
                # Normal operation
                signals[sig_id] = {
                    "quality_class": "GOOD",
                    "is_missing": False,
                    "is_stale": False,
                }

        signal_feed.append(SignalFeedEntry(
            scan_index=scan_idx,
            timestamp=timestamp,
            signals=signals,
            incidents=incidents if incidents else None,
        ))

    # Set expectations
    expectations = [
        # Before failure: OK
        ScenarioExpectation(
            scan_index=failure_start_scan - 1,
            overall_state="OK",
        ),
        # After failure: DEGRADED with RTU as primary
        ScenarioExpectation(
            scan_index=failure_start_scan + 3,
            overall_state="DEGRADED",
            primary_node_id=rtu_id,
            primary_node_type="rtu",
        ),
    ]

    return Scenario(
        name="rtu_failure",
        description=f"Simulated RTU failure for {rtu_id}",
        topology=topology_dict,
        signal_feed=signal_feed,
        expectations=expectations,
    )
