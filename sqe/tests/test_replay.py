"""Tests for deterministic replay runner."""

from pathlib import Path

from sqe.replay.runner import run_replay


def test_replay_outputs_are_deterministic(tmp_path):
    fixture_dir = Path(__file__).parent / "fixtures" / "replay"
    scans_path = fixture_dir / "scans.jsonl"
    config_path = fixture_dir / "cfg.yaml"
    groups_path = fixture_dir / "groups.yaml"
    expected_incidents = (fixture_dir / "expected_incidents.jsonl").read_text()
    expected_scans = (fixture_dir / "expected_scans.jsonl").read_text()
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
    assert (out_dir / "scans.jsonl").read_text() == expected_scans
    assert (out_dir / "group_incidents.jsonl").read_text() == expected_group_incidents

    out_dir_repeat = tmp_path / "out_repeat"
    run_replay(
        input_jsonl_path=str(scans_path),
        config_path=str(config_path),
        groups_config_path=str(groups_path),
        out_dir=str(out_dir_repeat),
    )
    assert (out_dir_repeat / "incidents.jsonl").read_text() == expected_incidents
    assert (out_dir_repeat / "scans.jsonl").read_text() == expected_scans
    assert (
        out_dir_repeat / "group_incidents.jsonl"
    ).read_text() == expected_group_incidents


def test_replay_metadata_fixture(tmp_path):
    fixture_dir = Path(__file__).parent / "fixtures" / "replay_metadata"
    scans_path = fixture_dir / "scans.jsonl"
    config_path = fixture_dir / "cfg.yaml"
    groups_path = fixture_dir / "groups.yaml"
    expected_incidents = (fixture_dir / "expected_incidents.jsonl").read_text()
    expected_scans = (fixture_dir / "expected_scans.jsonl").read_text()
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
    assert (out_dir / "scans.jsonl").read_text() == expected_scans
    assert (out_dir / "group_incidents.jsonl").read_text() == expected_group_incidents
