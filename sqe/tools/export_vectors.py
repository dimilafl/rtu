"""Export deterministic replay vectors."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from sqe.replay.runner import run_replay


def export_vectors(out_dir: Path) -> None:
    fixture_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "replay"
    scans_path = fixture_dir / "scans.jsonl"
    config_path = fixture_dir / "cfg.yaml"
    groups_path = fixture_dir / "groups.yaml"

    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        run_replay(
            input_jsonl_path=str(scans_path),
            config_path=str(config_path),
            groups_config_path=str(groups_path),
            out_dir=tmp_dir,
        )
        shutil.copyfile(scans_path, out_dir / "scans.jsonl")
        shutil.copyfile(config_path, out_dir / "cfg.yaml")
        shutil.copyfile(groups_path, out_dir / "groups.yaml")
        shutil.copyfile(Path(tmp_dir) / "incidents.jsonl", out_dir / "expected_incidents.jsonl")
        shutil.copyfile(
            Path(tmp_dir) / "group_incidents.jsonl",
            out_dir / "expected_group_incidents.jsonl",
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export replay vectors to a deterministic bundle."
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parents[1] / "vectors"),
        help="Output directory for vectors",
    )
    args = parser.parse_args()
    export_vectors(Path(args.out_dir))


if __name__ == "__main__":
    main()
