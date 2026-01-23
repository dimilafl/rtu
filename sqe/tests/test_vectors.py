"""Tests for portability vectors."""

from pathlib import Path

from sqe.tools.export_vectors import export_vectors


def test_vectors_are_stable(tmp_path):
    out_dir = tmp_path / "vectors"
    export_vectors(out_dir)

    repo_vectors = Path(__file__).resolve().parents[1] / "vectors"
    for name in (
        "scans.jsonl",
        "cfg.yaml",
        "groups.yaml",
        "expected_incidents.jsonl",
        "expected_group_incidents.jsonl",
    ):
        generated = (out_dir / name).read_bytes()
        expected = (repo_vectors / name).read_bytes()
        assert generated == expected
