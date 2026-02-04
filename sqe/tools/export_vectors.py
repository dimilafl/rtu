"""Export deterministic replay vectors."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
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
        shutil.copyfile(
            Path(tmp_dir) / "incidents.jsonl",
            out_dir / "expected_incidents.jsonl",
        )
        shutil.copyfile(
            Path(tmp_dir) / "group_incidents.jsonl",
            out_dir / "expected_group_incidents.jsonl",
        )

        config = yaml.safe_load(config_path.read_text())
        replay_stats = _load_replay_stats(scans_path)
        scan_p95 = _estimate_scan_p95(replay_stats, config)
        memory_bytes = _estimate_memory_bytes(replay_stats, config)
        sqi_values = []
        with (Path(tmp_dir) / "scans.jsonl").open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                sqi_values.append(float(record["sqi"]))
        mean_sqi = sum(sqi_values) / len(sqi_values) if sqi_values else 0.0
        golden_payload = {
            "sqi": {"mean": mean_sqi, "tolerance": 0.01},
            "scan_p95_estimate_max": scan_p95 * 1.05,
            "memory_estimate_bytes_max": memory_bytes * 1.05,
        }
        (out_dir / "golden_metrics.json").write_text(
            json.dumps(golden_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        schema_payload = {
            "processed_scan": PROCESSED_SCAN_SCHEMA,
            "incident_event": INCIDENT_EVENT_SCHEMA,
            "group_incident_event": GROUP_INCIDENT_EVENT_SCHEMA,
        }
        schema_blob = json.dumps(schema_payload, sort_keys=True).encode("utf-8")
        schema_snapshot = {
            "schema_version": SCHEMA_VERSION,
            "hash": hashlib.sha256(schema_blob).hexdigest(),
        }
        (out_dir / "schema_snapshot.json").write_text(
            json.dumps(schema_snapshot, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
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
