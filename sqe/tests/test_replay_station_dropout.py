"""Tests for station dropout replay fixture."""

from pathlib import Path

from sqe.replay.runner import run_replay


def test_replay_station_dropout_suppresses_member_events(tmp_path):
    fixture_dir = Path(__file__).parent / "fixtures" / "replay_station_dropout"
    scans_path = fixture_dir / "scans.jsonl"
    config_path = fixture_dir / "cfg.yaml"
    groups_path = fixture_dir / "groups.yaml"
    expected_incidents = (fixture_dir / "expected_incidents.jsonl").read_text()
    expected_group_incidents = (
        fixture_dir / "expected_group_incidents.jsonl"
    ).read_text()

    out_dir = tmp_path / "out"
    run_replay(
        input_jsonl_path=str(scans_path),
        config_path=str(config_path),
        groups_config_path=str(groups_path),
        out_dir=str(out_dir),
    )

    assert (out_dir / "incidents.jsonl").read_text() == expected_incidents
    assert (out_dir / "group_incidents.jsonl").read_text() == expected_group_incidents
