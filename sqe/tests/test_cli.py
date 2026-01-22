"""Tests for CLI helpers."""

import pytest
from types import SimpleNamespace

from sqe.cli.sqe_cli import (
    analyze_command,
    build_scans,
    derive_scan_interval,
    incidents_command,
    load_signal_from_csv,
)


def test_load_signal_from_csv_parses_missing_values(tmp_path):
    """Ensure missing timestamp/value entries are parsed as None."""
    csv_content = "\n".join([
        "timestamp,signal_id,value",
        "0.0,AI_001,42.5",
        ",AI_002,",
        ""
    ])
    csv_path = tmp_path / "signals.csv"
    csv_path.write_text(csv_content)

    rows = load_signal_from_csv(str(csv_path))

    assert rows[0].timestamp == 0.0
    assert rows[0].value == 42.5
    assert rows[1].timestamp is None
    assert rows[1].value is None


def test_load_signal_from_csv_requires_expected_columns(tmp_path):
    """Ensure missing required CSV headers are rejected."""
    csv_content = "\n".join([
        "time,signal_id,value",
        "0.0,AI_001,42.5",
        ""
    ])
    csv_path = tmp_path / "invalid_headers.csv"
    csv_path.write_text(csv_content)

    with pytest.raises(ValueError, match="Missing required CSV columns"):
        load_signal_from_csv(str(csv_path))


def test_load_signal_from_csv_rejects_blank_signal_id(tmp_path):
    """Ensure missing signal identifiers raise a helpful error."""
    csv_content = "\n".join([
        "timestamp,signal_id,value",
        "0.0,,42.5",
        ""
    ])
    csv_path = tmp_path / "missing_signal_id.csv"
    csv_path.write_text(csv_content)

    with pytest.raises(ValueError, match="Missing signal_id value"):
        load_signal_from_csv(str(csv_path))


def test_build_scans_with_staggered_timestamps_and_missing_entries(tmp_path):
    """Ensure scans are grouped by timestamp and missing signals are filled with None."""
    csv_content = "\n".join([
        "timestamp,signal_id,value",
        "0.0,AI_001,10.0",
        "0.0,AI_002,20.0",
        "0.1,AI_001,10.5",
        "0.2,AI_002,",
        "0.3,AI_001,11.0",
        "0.3,AI_002,21.0",
        ""
    ])
    csv_path = tmp_path / "staggered.csv"
    csv_path.write_text(csv_content)

    rows = load_signal_from_csv(str(csv_path))
    signal_ids, scans = build_scans(rows)

    assert signal_ids == ["AI_001", "AI_002"]
    timestamps = [timestamp for timestamp, _ in scans]
    assert timestamps == [0.0, 0.1, 0.2, 0.3]

    _, first_scan = scans[0]
    assert first_scan["AI_001"] == 10.0
    assert first_scan["AI_002"] == 20.0

    _, second_scan = scans[1]
    assert second_scan["AI_001"] == 10.5
    assert second_scan["AI_002"] is None

    _, third_scan = scans[2]
    assert third_scan["AI_001"] is None
    assert third_scan["AI_002"] is None

    scan_interval = derive_scan_interval(timestamps)
    assert scan_interval == pytest.approx(0.1)


def test_analyze_command_accepts_timestamps(tmp_path, capsys):
    """Ensure analyze command handles timestamped CSVs without errors."""
    csv_content = "\n".join([
        "timestamp,signal_id,value",
        "0.0,AI_001,10.0",
        "0.1,AI_001,10.5",
        ""
    ])
    csv_path = tmp_path / "signals.csv"
    csv_path.write_text(csv_content)

    args = SimpleNamespace(
        signal_file=str(csv_path),
        plot=False,
        config=None,
    )

    assert analyze_command(args) == 0
    capsys.readouterr()


def test_incidents_command_writes_output(tmp_path, capsys):
    """Ensure incidents command writes JSONL output."""
    csv_content = "\n".join([
        "timestamp,signal_id,value",
        "0.0,AI_001,",
        "0.1,AI_001,",
        "0.2,AI_001,",
        "0.3,AI_001,",
        "0.4,AI_001,",
        ""
    ])
    csv_path = tmp_path / "signals.csv"
    csv_path.write_text(csv_content)
    out_path = tmp_path / "incidents.jsonl"

    args = SimpleNamespace(
        signal_file=str(csv_path),
        config=None,
        out=str(out_path),
    )

    assert incidents_command(args) == 0
    contents = out_path.read_text().strip()
    assert contents
    capsys.readouterr()
