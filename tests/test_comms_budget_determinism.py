"""Tests for deterministic budget output."""

import json
from dataclasses import asdict

from sqe.comms.api import build_utilization_statuses
from sqe.comms.budget import BudgetConfig, BudgetThresholds
from sqe.comms.schema import CommsAggregate
from sqe.topology.loader import load_topology_dict


def _make_snapshot():
    return load_topology_dict(
        {
            "nodes": [
                {"id": "D", "type": "comms_domain"},
                {"id": "P", "type": "poll_group"},
                {"id": "R1", "type": "rtu"},
                {"id": "s1", "type": "signal"},
            ],
            "edges": [
                {"parent": "D", "child": "P"},
                {"parent": "P", "child": "R1"},
                {"parent": "R1", "child": "s1"},
            ],
        }
    )


def _make_config():
    return BudgetConfig(
        enabled=True,
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


def _make_aggregate(node_id: str, node_type: str) -> CommsAggregate:
    return CommsAggregate(
        node_id=node_id,
        node_type=node_type,
        scan_index=2,
        scan_timestamp=123.4,
        sample_count=1,
        timeout_rate=0.0,
        retry_rate=0.0,
        crc_error_rate=0.0,
        avg_poll_cycle_ms=None,
        avg_jitter_ms=None,
        bytes_tx_total=10,
        bytes_rx_total=20,
    )


def test_budget_output_is_deterministic():
    snapshot = _make_snapshot()
    cfg = _make_config()
    aggregates = {
        ("COMMS_DOMAIN", "D"): _make_aggregate("D", "COMMS_DOMAIN"),
        ("POLL_GROUP", "P"): _make_aggregate("P", "POLL_GROUP"),
        ("RTU", "R1"): _make_aggregate("R1", "RTU"),
    }

    first = build_utilization_statuses(snapshot, aggregates, cfg)
    second = build_utilization_statuses(snapshot, aggregates, cfg)

    first_json = json.dumps(
        [asdict(item) for item in first],
        sort_keys=True,
        separators=(",", ":"),
    )
    second_json = json.dumps(
        [asdict(item) for item in second],
        sort_keys=True,
        separators=(",", ":"),
    )

    assert first_json == second_json
