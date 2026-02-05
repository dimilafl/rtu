"""Tests for comms budget JSONL determinism."""

from pathlib import Path

from sqe.comms.budget import BudgetConfig, BudgetThresholds
from sqe.comms.schema import CommsMetrics
from sqe.core.engine import SignalQualityEngine
from sqe.core.incidents import IncidentCause, IncidentEngine, IncidentPolicy
from sqe.integration.publisher import JsonLinesPublisher
from sqe.ops.service import RealtimeQualityService
from sqe.topology.loader import load_topology_dict


def _build_policy() -> IncidentPolicy:
    return IncidentPolicy(
        start_sqi_threshold=50,
        end_sqi_threshold=60,
        start_persistence_scans=1,
        end_persistence_scans=1,
        critical_sqi_threshold=25,
        component_score_floor=70,
        cause_priority=[
            IncidentCause.MISSING,
            IncidentCause.STALE,
            IncidentCause.STEP,
            IncidentCause.PLAUSIBILITY,
            IncidentCause.DRIFT,
            IncidentCause.SPIKES,
            IncidentCause.NOISE,
            IncidentCause.OSCILLATION,
            IncidentCause.UNKNOWN,
        ],
    )


def _build_budget_config(enabled: bool) -> BudgetConfig:
    return BudgetConfig(
        enabled=enabled,
        scan_interval_ms=1000,
        bytes_per_signal_estimate=18,
        protocol_overhead_bytes=200,
        default_capacity_bps_by_type={
            "comms_domain": 9600,
            "poll_group": 9600,
            "rtu": 9600,
        },
        per_node_capacity_bps={},
        thresholds=BudgetThresholds(
            utilization_degraded=0.7,
            utilization_critical=0.9,
            low_headroom=0.1,
        ),
    )


def _build_snapshot():
    return load_topology_dict(
        {
            "nodes": [
                {"id": "cd1", "type": "comms_domain"},
                {"id": "pg1", "type": "poll_group"},
                {"id": "rtu1", "type": "rtu"},
                {"id": "sig1", "type": "signal"},
            ],
            "edges": [
                {"parent": "cd1", "child": "pg1"},
                {"parent": "pg1", "child": "rtu1"},
                {"parent": "rtu1", "child": "sig1"},
            ],
        }
    )


def _build_comms_metrics() -> list[CommsMetrics]:
    return [
        CommsMetrics(
            scan_index=1,
            scan_timestamp=123.0,
            signal_id="sig1",
            rtu_id="rtu1",
            poll_group_id="pg1",
            comms_domain_id="cd1",
            poll_cycle_ms=1000.0,
            poll_jitter_ms=10.0,
            timeout_count=0,
            retry_count=0,
            crc_error_count=0,
            bytes_tx=1200,
            bytes_rx=0,
        )
    ]


def _write_comms_budget(output_dir: Path) -> str:
    engine = SignalQualityEngine(scan_interval=1.0)
    snapshot = _build_snapshot()
    service = RealtimeQualityService(
        engine,
        IncidentEngine(_build_policy()),
        comms_budget_config=_build_budget_config(enabled=True),
        topology_snapshot=snapshot,
    )
    processed_scan, _, _ = service.process_scan(
        {"sig1": 1.0},
        timestamp=123.0,
        comms_metrics=_build_comms_metrics(),
    )
    publisher = JsonLinesPublisher(output_dir)
    publisher.publish_comms_budget(
        processed_scan.comms_utilization_statuses or []
    )
    return publisher.comms_budget_path.read_text(encoding="utf-8")


def test_comms_budget_disabled_writes_nothing(tmp_path: Path) -> None:
    output_dir = tmp_path / "disabled"
    output_dir.mkdir()
    engine = SignalQualityEngine(scan_interval=1.0)
    snapshot = _build_snapshot()
    service = RealtimeQualityService(
        engine,
        IncidentEngine(_build_policy()),
        comms_budget_config=_build_budget_config(enabled=False),
        topology_snapshot=snapshot,
    )
    processed_scan, _, _ = service.process_scan(
        {"sig1": 1.0},
        timestamp=123.0,
        comms_metrics=_build_comms_metrics(),
    )
    assert processed_scan.comms_utilization_statuses is None

    publisher = JsonLinesPublisher(output_dir)
    if processed_scan.comms_utilization_statuses:
        publisher.publish_comms_budget(processed_scan.comms_utilization_statuses)
    assert not publisher.comms_budget_path.exists()


def test_comms_budget_jsonl_determinism(tmp_path: Path) -> None:
    out_dir_one = tmp_path / "run_one"
    out_dir_two = tmp_path / "run_two"
    out_dir_one.mkdir()
    out_dir_two.mkdir()

    first = _write_comms_budget(out_dir_one)
    second = _write_comms_budget(out_dir_two)

    assert first == second
