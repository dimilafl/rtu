"""Tests for evaluation harness metrics."""

from pathlib import Path

from sqe.eval.labels import load_labels
from sqe.eval.metrics import (
    compute_metrics,
    count_group_started_events,
    load_predicted_started_events,
)
from sqe.replay.runner import run_replay


def test_eval_metrics_against_labels(tmp_path):
    fixture_dir = Path(__file__).parent / "fixtures" / "replay"
    scans_path = fixture_dir / "scans.jsonl"
    config_path = fixture_dir / "cfg.yaml"
    labels_path = Path(__file__).parent / "fixtures" / "eval" / "labels.yaml"

    out_dir = tmp_path / "out"
    run_replay(
        input_jsonl_path=str(scans_path),
        config_path=str(config_path),
        groups_config_path=None,
        out_dir=str(out_dir),
        run_id="test-run",
    )

    labels = load_labels(str(labels_path))
    predicted = load_predicted_started_events(str(out_dir / "incidents.jsonl"))
    group_started = count_group_started_events(
        str(out_dir / "group_incidents.jsonl")
    )
    metrics = compute_metrics(predicted, labels, group_started)

    assert metrics["detection_precision"] == 1.0
    assert metrics["detection_recall"] == 1.0
    assert metrics["detection_f1"] == 1.0
    assert metrics["mean_time_to_detect_scans"] == 0.0
    assert metrics["cause_accuracy"] == 1.0
    assert metrics["severity_accuracy"] == 1.0
    assert metrics["spam_metrics"]["total_signal_started"] == 2
    assert metrics["spam_metrics"]["total_group_started"] == 0
    assert metrics["spam_metrics"]["starts_ratio"] == 2.0
