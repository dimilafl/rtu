"""Tests for comms health JSONL determinism."""

from pathlib import Path

from sqe.comms.health import CommsHealthThresholds
from sqe.comms.schema import CommsMetrics
from sqe.core.incidents import IncidentCause, IncidentEngine, IncidentPolicy
from sqe.core.engine import SignalQualityEngine
from sqe.integration.publisher import JsonLinesPublisher
from sqe.ops.service import RealtimeQualityService


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


def _write_comms_health(output_dir: Path) -> str:
    engine = SignalQualityEngine(scan_interval=0.1)
    service = RealtimeQualityService(
        engine,
        IncidentEngine(_build_policy()),
        comms_enabled=True,
        comms_thresholds=CommsHealthThresholds.from_config({}),
    )
    comms_metrics = [
        CommsMetrics(
            scan_index=1,
            scan_timestamp=123.0,
            signal_id="sig1",
            rtu_id="rtu1",
            poll_group_id="pg1",
            comms_domain_id="cd1",
            poll_cycle_ms=6000.0,
            poll_jitter_ms=800.0,
            timeout_count=1,
            retry_count=0,
            crc_error_count=0,
            bytes_tx=10,
            bytes_rx=20,
        )
    ]
    processed_scan, _, _ = service.process_scan(
        {"sig1": 1.0},
        timestamp=123.0,
        comms_metrics=comms_metrics,
    )
    publisher = JsonLinesPublisher(output_dir)
    publisher.comms_health_path.write_text("", encoding="utf-8")
    publisher.publish_comms_health(processed_scan.comms_health or [])
    return publisher.comms_health_path.read_text(encoding="utf-8")


def test_comms_jsonl_determinism(tmp_path: Path) -> None:
    out_dir_one = tmp_path / "run_one"
    out_dir_two = tmp_path / "run_two"
    out_dir_one.mkdir()
    out_dir_two.mkdir()

    first = _write_comms_health(out_dir_one)
    second = _write_comms_health(out_dir_two)

    assert first == second
