"""Offline tuning pipeline for incident policy and SQI configuration."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import itertools
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from sqe.config.loader import load_config
from sqe.eval.metrics import (
    compute_metrics,
    count_group_started_events,
    load_predicted_started_events,
)
from sqe.eval.labels import load_labels
from sqe.replay.runner import run_replay


@dataclass(frozen=True)
class GateConfig:
    detection_f1_min: float
    mean_time_to_detect_scans_max: float
    spam_ratio_max: float

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "GateConfig":
        gates = config.get("gates", {})
        return cls(
            detection_f1_min=float(gates.get("detection_f1_min", 0.0)),
            mean_time_to_detect_scans_max=float(
                gates.get("mean_time_to_detect_scans_max", float("inf"))
            ),
            spam_ratio_max=float(gates.get("spam_ratio_max", float("inf"))),
        )


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Sweep config must be a mapping: {path}")
    return data


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _grid(params: Dict[str, List[Any]]) -> Iterable[Dict[str, Any]]:
    if not params:
        return
    keys = list(params.keys())
    values = [params[key] for key in keys]
    for combination in itertools.product(*values):
        yield dict(zip(keys, combination))


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {key: value / total for key, value in weights.items()}


def _write_config(config: Dict[str, Any], path: Path) -> None:
    path.write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")


def _evaluate_replay(
    replay_input: Path,
    labels_path: Path,
    config_path: Path,
    groups_config: Optional[Path],
    out_dir: Path,
) -> Dict[str, Any]:
    run_replay(
        input_jsonl_path=str(replay_input),
        config_path=str(config_path),
        groups_config_path=str(groups_config) if groups_config else None,
        out_dir=str(out_dir),
        write_processed=False,
    )
    incidents_path = out_dir / "incidents.jsonl"
    group_incidents_path = out_dir / "group_incidents.jsonl"
    predicted = load_predicted_started_events(str(incidents_path))
    group_started = count_group_started_events(str(group_incidents_path))
    labels = load_labels(str(labels_path))
    return compute_metrics(predicted, labels, group_started)


def _passes_gates(metrics: Dict[str, Any], gates: GateConfig) -> bool:
    spam_ratio = metrics["spam_metrics"]["starts_ratio"]
    return (
        metrics["detection_f1"] >= gates.detection_f1_min
        and metrics["mean_time_to_detect_scans"]
        <= gates.mean_time_to_detect_scans_max
        and spam_ratio <= gates.spam_ratio_max
    )


def _score(metrics: Dict[str, Any]) -> Tuple[float, float, float]:
    spam_ratio = metrics["spam_metrics"]["starts_ratio"]
    return (
        metrics["detection_f1"],
        -metrics["mean_time_to_detect_scans"],
        -spam_ratio,
    )


def _run_sweep(
    *,
    base_config: Dict[str, Any],
    overrides_iter: Iterable[Tuple[Dict[str, Any], Dict[str, Any]]],
    replay_input: Path,
    labels_path: Path,
    groups_config: Optional[Path],
    out_dir: Path,
    gates: GateConfig,
    run_prefix: str,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None
    for idx, (override, metadata) in enumerate(overrides_iter, start=1):
        run_dir = out_dir / f"{run_prefix}_{idx:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        config = _deep_merge(base_config, override)
        config_path = run_dir / "config.yaml"
        _write_config(config, config_path)
        metrics = _evaluate_replay(
            replay_input,
            labels_path,
            config_path,
            groups_config,
            run_dir,
        )
        passed = _passes_gates(metrics, gates)
        record = {
            "run_id": run_dir.name,
            "override": override,
            "metadata": metadata,
            "metrics": metrics,
            "passes_gates": passed,
        }
        results.append(record)
        if passed:
            if best is None or _score(metrics) > _score(best["metrics"]):
                best = record

    return {
        "results": results,
        "best": best,
    }


def _incident_policy_overrides(
    sweep_config: Dict[str, Any]
) -> Iterable[Tuple[Dict[str, Any], Dict[str, Any]]]:
    params = sweep_config.get("incident_policy_sweep", {})
    grid_params = {key: params.get(key, []) for key in params}
    for combo in _grid(grid_params):
        override = {"incidents": combo}
        yield override, {"policy": combo}


def _sqi_overrides(
    sweep_config: Dict[str, Any]
) -> Iterable[Tuple[Dict[str, Any], Dict[str, Any]]]:
    params = sweep_config.get("sqi_weight_sweep", {})
    weights = params.get("weights", {})
    thresholds = params.get("thresholds", {})
    normalize = bool(params.get("normalize_weights", False))

    weight_grid = list(_grid(weights)) if weights else [{}]
    threshold_grid = list(_grid(thresholds)) if thresholds else [{}]

    for weight_combo in weight_grid:
        if normalize:
            weight_combo = _normalize_weights(
                {key: float(value) for key, value in weight_combo.items()}
            )
        for threshold_combo in threshold_grid:
            override = {
                "sqi": {
                    "weights": weight_combo,
                    "thresholds": threshold_combo,
                }
            }
            metadata = {
                "weights": weight_combo,
                "thresholds": threshold_combo,
                "normalized": normalize,
            }
            yield override, metadata


def _write_summary(out_dir: Path, payload: Dict[str, Any]) -> None:
    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    results_path = out_dir / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as handle:
        for record in payload.get("results", []):
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline tuning pipeline for SQE incidents and SQI."
    )
    parser.add_argument(
        "--replay-input",
        required=True,
        help="Path to replay input JSONL.",
    )
    parser.add_argument(
        "--labels",
        required=True,
        help="Path to incident labels YAML/JSON.",
    )
    parser.add_argument(
        "--sweep-config",
        required=True,
        help="Path to sweep config YAML.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Directory to store sweep outputs.",
    )
    parser.add_argument(
        "--base-config",
        help="Optional base config YAML to override defaults.",
    )
    parser.add_argument(
        "--groups-config",
        help="Optional groups config YAML for group incidents.",
    )
    parser.add_argument(
        "--mode",
        choices=["incident_policy", "sqi", "all"],
        default="all",
        help="Which sweep to run (default: all).",
    )
    return parser.parse_args(argv)


def run_offline_tuning(args: argparse.Namespace) -> int:
    replay_input = Path(args.replay_input)
    labels_path = Path(args.labels)
    sweep_config = _load_yaml(Path(args.sweep_config))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_config(args.base_config)
    gates = GateConfig.from_config(sweep_config)

    summary: Dict[str, Any] = {
        "gates": gates.__dict__,
        "mode": args.mode,
    }

    if args.mode in {"incident_policy", "all"}:
        incident_out = out_dir / "incident_policy"
        incident_out.mkdir(parents=True, exist_ok=True)
        incident_payload = _run_sweep(
            base_config=base_config,
            overrides_iter=_incident_policy_overrides(sweep_config),
            replay_input=replay_input,
            labels_path=labels_path,
            groups_config=Path(args.groups_config)
            if args.groups_config
            else None,
            out_dir=incident_out,
            gates=gates,
            run_prefix="incident",
        )
        _write_summary(incident_out, incident_payload)
        summary["incident_policy"] = {
            "best": incident_payload["best"],
            "runs": len(incident_payload["results"]),
        }

    if args.mode in {"sqi", "all"}:
        sqi_out = out_dir / "sqi_weights"
        sqi_out.mkdir(parents=True, exist_ok=True)
        sqi_payload = _run_sweep(
            base_config=base_config,
            overrides_iter=_sqi_overrides(sweep_config),
            replay_input=replay_input,
            labels_path=labels_path,
            groups_config=Path(args.groups_config)
            if args.groups_config
            else None,
            out_dir=sqi_out,
            gates=gates,
            run_prefix="sqi",
        )
        _write_summary(sqi_out, sqi_payload)
        summary["sqi_weights"] = {
            "best": sqi_payload["best"],
            "runs": len(sqi_payload["results"]),
        }

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    return run_offline_tuning(args)


if __name__ == "__main__":
    raise SystemExit(main())
