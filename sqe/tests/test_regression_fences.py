"""Regression fences for SQE golden vectors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from sqe.replay.runner import run_replay
from sqe.schema import (
    GROUP_INCIDENT_EVENT_SCHEMA,
    INCIDENT_EVENT_SCHEMA,
    PROCESSED_SCAN_SCHEMA,
    SCHEMA_VERSION,
)
from sqe.tools.offline_tuning import _estimate_memory_bytes, _estimate_scan_p95
from sqe.tools.offline_tuning import _load_replay_stats


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _schema_hash() -> str:
    payload = {
        "processed_scan": PROCESSED_SCAN_SCHEMA,
        "incident_event": INCIDENT_EVENT_SCHEMA,
        "group_incident_event": GROUP_INCIDENT_EVENT_SCHEMA,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _sqi_stats(scans_path: Path) -> dict:
    values = []
    with scans_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            values.append(float(record["sqi"]))
    if not values:
        return {"mean": 0.0, "min": 0.0, "max": 0.0}
    total = sum(values)
    return {
        "mean": total / len(values),
        "min": min(values),
        "max": max(values),
    }


def test_replay_vectors_regression_fences(tmp_path: Path) -> None:
    vectors_dir = Path(__file__).resolve().parents[1] / "vectors"
    scans_path = vectors_dir / "scans.jsonl"
    config_path = vectors_dir / "cfg.yaml"
    groups_path = vectors_dir / "groups.yaml"
    expected_incidents = (vectors_dir / "expected_incidents.jsonl").read_text()
    expected_group_incidents = (
        vectors_dir / "expected_group_incidents.jsonl"
    ).read_text()

    out_dir = tmp_path / "out"
    run_replay(
        input_jsonl_path=str(scans_path),
        config_path=str(config_path),
        groups_config_path=str(groups_path),
        out_dir=str(out_dir),
        run_id="test-run",
    )

    assert (out_dir / "incidents.jsonl").read_text() == expected_incidents
    assert (out_dir / "group_incidents.jsonl").read_text() == expected_group_incidents

    golden = _load_json(vectors_dir / "golden_metrics.json")
    stats = _sqi_stats(out_dir / "scans.jsonl")
    tolerance = float(golden["sqi"]["tolerance"])
    assert abs(stats["mean"] - golden["sqi"]["mean"]) <= tolerance

    replay_stats = _load_replay_stats(scans_path)
    config = yaml.safe_load((vectors_dir / "cfg.yaml").read_text())
    scan_p95 = _estimate_scan_p95(replay_stats, config)
    memory_bytes = _estimate_memory_bytes(replay_stats, config)
    assert scan_p95 <= golden["scan_p95_estimate_max"]
    assert memory_bytes <= golden["memory_estimate_bytes_max"]

    schema_snapshot = _load_json(vectors_dir / "schema_snapshot.json")
    current_hash = _schema_hash()
    if current_hash != schema_snapshot["hash"]:
        assert SCHEMA_VERSION != schema_snapshot["schema_version"]
