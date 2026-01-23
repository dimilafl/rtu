"""Tests for impact report tool."""

import subprocess
import sys
from pathlib import Path

from sqe.replay.runner import run_replay


def _extract_count(report: str, section: str, label: str) -> int:
    in_section = False
    for line in report.splitlines():
        if line.strip() == section:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.strip().startswith(f"- {label}:"):
            return int(line.split(":", 1)[1].strip())
    raise AssertionError(f"Missing {label} in {section}")


def _extract_ratio(report: str) -> str:
    for line in report.splitlines():
        if line.strip().startswith("- ratio:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("Missing ratio line")


def test_impact_report_counts(tmp_path):
    fixture_dir = Path(__file__).parent / "fixtures" / "replay"
    scans_path = fixture_dir / "scans.jsonl"
    config_path = fixture_dir / "cfg.yaml"
    groups_path = fixture_dir / "groups.yaml"

    out_dir = tmp_path / "out"
    run_replay(
        input_jsonl_path=str(scans_path),
        config_path=str(config_path),
        groups_config_path=str(groups_path),
        out_dir=str(out_dir),
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sqe.tools.impact_report",
            "--replay-dir",
            str(out_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report = result.stdout
    assert _extract_count(report, "## Signal incidents", "started") == 2
    assert _extract_count(report, "## Signal incidents", "resolved") == 0
    assert _extract_count(report, "## Group incidents", "started") == 1
    assert _extract_count(report, "## Group incidents", "resolved") == 0
    assert _extract_ratio(report) == "2.000"
