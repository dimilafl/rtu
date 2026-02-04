"""Offline tuning pipeline for incident policy and SQI configuration."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import itertools
import json
from pathlib import Path
import random
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from sqe.config.loader import load_config
from sqe.config.loader import (
    build_signal_config,
    get_engine_scan_interval,
)
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
    incident_f1_min: float
    false_alarm_rate_max: float
    mean_time_to_detect_scans_max: float
    spam_ratio_max: float
    scan_p95_max: float
    memory_max_bytes: float

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "GateConfig":
        gates = config.get("gates", {})
        return cls(
            detection_f1_min=float(gates.get("detection_f1_min", 0.0)),
            incident_f1_min=float(gates.get("incident_f1_min", 0.0)),
            false_alarm_rate_max=float(gates.get("false_alarm_rate_max", float("inf"))),
            mean_time_to_detect_scans_max=float(
                gates.get("mean_time_to_detect_scans_max", float("inf"))
            ),
            spam_ratio_max=float(gates.get("spam_ratio_max", float("inf"))),
            scan_p95_max=float(gates.get("scan_p95_max", float("inf"))),
            memory_max_bytes=float(gates.get("memory_max_bytes", float("inf"))),
        )


@dataclass(frozen=True)
class ScoreConfig:
    detection_f1: float
    incident_f1: float
    false_alarm_rate: float
    mean_time_to_detect_scans: float
    scan_p95: float
    memory_bytes: float

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "ScoreConfig":
        weights = config.get("score_weights", {})
        return cls(
            detection_f1=float(weights.get("detection_f1", 1.0)),
            incident_f1=float(weights.get("incident_f1", 1.0)),
            false_alarm_rate=float(weights.get("false_alarm_rate", -1.0)),
            mean_time_to_detect_scans=float(
                weights.get("mean_time_to_detect_scans", -0.5)
            ),
            scan_p95=float(weights.get("scan_p95", -0.5)),
            memory_bytes=float(weights.get("memory_bytes", -0.5)),
        )


@dataclass(frozen=True)
class SearchConfig:
    strategy: str
    seed: int
    retain_fraction: float
    scan_fractions: Tuple[float, ...]

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "SearchConfig":
        search = config.get("search", {})
        fractions = search.get("scan_fractions", [1.0])
        if not fractions:
            fractions = [1.0]
        return cls(
            strategy=str(search.get("strategy", "grid")),
            seed=int(search.get("seed", 13)),
            retain_fraction=float(search.get("retain_fraction", 0.5)),
            scan_fractions=tuple(float(value) for value in fractions),
        )


@dataclass(frozen=True)
class ReplayStats:
    scan_indices: Tuple[int, ...]
    scan_signal_counts: Tuple[int, ...]
    signal_ids: Tuple[str, ...]

    @property
    def scan_count(self) -> int:
        return len(self.scan_indices)


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
    *,
    max_scans: Optional[int] = None,
    replay_stats: Optional[ReplayStats] = None,
) -> Dict[str, Any]:
    run_replay(
        input_jsonl_path=str(replay_input),
        config_path=str(config_path),
        groups_config_path=str(groups_config) if groups_config else None,
        out_dir=str(out_dir),
        write_processed=False,
        max_scans=max_scans,
    )
    incidents_path = out_dir / "incidents.jsonl"
    group_incidents_path = out_dir / "group_incidents.jsonl"
    predicted = load_predicted_started_events(str(incidents_path))
    group_started = count_group_started_events(str(group_incidents_path))
    labels = load_labels(str(labels_path))
    if max_scans is not None and replay_stats:
        if max_scans <= 0:
            labels = []
        else:
            last_scan_index = replay_stats.scan_indices[
                min(max_scans, replay_stats.scan_count) - 1
            ]
            labels = [
                label
                for label in labels
                if label.start_scan_index <= last_scan_index
            ]
    return compute_metrics(predicted, labels, group_started)


def _passes_gates(metrics: Dict[str, Any], gates: GateConfig) -> bool:
    spam_ratio = metrics["spam_metrics"]["starts_ratio"]
    false_alarm_rate = metrics["false_alarm_rate"]
    return (
        metrics["detection_f1"] >= gates.detection_f1_min
        and metrics["incident_f1"] >= gates.incident_f1_min
        and false_alarm_rate <= gates.false_alarm_rate_max
        and metrics["mean_time_to_detect_scans"]
        <= gates.mean_time_to_detect_scans_max
        and spam_ratio <= gates.spam_ratio_max
        and metrics["scan_p95_estimate"] <= gates.scan_p95_max
        and metrics["memory_estimate_bytes"] <= gates.memory_max_bytes
    )


def _composite_score(metrics: Dict[str, Any], weights: ScoreConfig) -> float:
    weighted = (
        weights.detection_f1 * metrics["detection_f1"]
        + weights.incident_f1 * metrics["incident_f1"]
        + weights.false_alarm_rate * metrics["false_alarm_rate"]
        + weights.mean_time_to_detect_scans
        * metrics["mean_time_to_detect_scans"]
        + weights.scan_p95 * metrics["scan_p95_estimate"]
        + weights.memory_bytes * metrics["memory_estimate_bytes"]
    )
    return weighted


def _perf_gate_failures(
    metrics: Dict[str, Any], gates: GateConfig
) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if metrics["scan_p95_estimate"] > gates.scan_p95_max:
        failures.append(
            {
                "gate": "scan_p95_max",
                "value": metrics["scan_p95_estimate"],
                "threshold": gates.scan_p95_max,
            }
        )
    if metrics["memory_estimate_bytes"] > gates.memory_max_bytes:
        failures.append(
            {
                "gate": "memory_max_bytes",
                "value": metrics["memory_estimate_bytes"],
                "threshold": gates.memory_max_bytes,
            }
        )
    return failures


def _gate_failures(
    metrics: Dict[str, Any], gates: GateConfig
) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if metrics["detection_f1"] < gates.detection_f1_min:
        failures.append(
            {
                "gate": "detection_f1_min",
                "value": metrics["detection_f1"],
                "threshold": gates.detection_f1_min,
            }
        )
    if metrics["incident_f1"] < gates.incident_f1_min:
        failures.append(
            {
                "gate": "incident_f1_min",
                "value": metrics["incident_f1"],
                "threshold": gates.incident_f1_min,
            }
        )
    if metrics["false_alarm_rate"] > gates.false_alarm_rate_max:
        failures.append(
            {
                "gate": "false_alarm_rate_max",
                "value": metrics["false_alarm_rate"],
                "threshold": gates.false_alarm_rate_max,
            }
        )
    if (
        metrics["mean_time_to_detect_scans"]
        > gates.mean_time_to_detect_scans_max
    ):
        failures.append(
            {
                "gate": "mean_time_to_detect_scans_max",
                "value": metrics["mean_time_to_detect_scans"],
                "threshold": gates.mean_time_to_detect_scans_max,
            }
        )
    if metrics["spam_metrics"]["starts_ratio"] > gates.spam_ratio_max:
        failures.append(
            {
                "gate": "spam_ratio_max",
                "value": metrics["spam_metrics"]["starts_ratio"],
                "threshold": gates.spam_ratio_max,
            }
        )
    if metrics["scan_p95_estimate"] > gates.scan_p95_max:
        failures.append(
            {
                "gate": "scan_p95_max",
                "value": metrics["scan_p95_estimate"],
                "threshold": gates.scan_p95_max,
            }
        )
    if metrics["memory_estimate_bytes"] > gates.memory_max_bytes:
        failures.append(
            {
                "gate": "memory_max_bytes",
                "value": metrics["memory_estimate_bytes"],
                "threshold": gates.memory_max_bytes,
            }
        )
    return failures


def _load_replay_stats(replay_input: Path) -> ReplayStats:
    scan_indices: List[int] = []
    scan_signal_counts: List[int] = []
    signal_ids: List[str] = []
    signal_set = set()
    with replay_input.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            scan_indices.append(int(record["scan_index"]))
            signals = record.get("signals", {})
            if not isinstance(signals, dict):
                raise ValueError("Replay scan signals must be a mapping")
            scan_signal_counts.append(len(signals))
            for signal_id in signals.keys():
                if signal_id not in signal_set:
                    signal_set.add(signal_id)
                    signal_ids.append(signal_id)
    return ReplayStats(
        scan_indices=tuple(scan_indices),
        scan_signal_counts=tuple(scan_signal_counts),
        signal_ids=tuple(signal_ids),
    )


def _estimate_scan_p95(
    replay_stats: ReplayStats, base_config: Dict[str, Any]
) -> float:
    if not replay_stats.scan_signal_counts:
        return 0.0
    scan_interval = get_engine_scan_interval(base_config)
    sample_signal_id = (
        replay_stats.signal_ids[0]
        if replay_stats.signal_ids
        else "SAMPLE"
    )
    signal_config = build_signal_config(
        base_config, sample_signal_id, scan_interval
    )
    base_cost = 1.0
    cost_per_signal = base_cost + (
        0.02 * max(1, signal_config.ma_window)
        + 0.03 * max(1, signal_config.variance_window)
        + 0.04 * max(1, signal_config.freq_window)
        + 0.01 * max(1, signal_config.missing_window)
        + 0.02 * max(1, signal_config.stale_window)
        + 0.02 * max(1, signal_config.step_baseline_window)
    ) / 100.0
    if signal_config.enable_fft:
        cost_per_signal *= 1.15
    estimated = sorted(
        count * cost_per_signal
        for count in replay_stats.scan_signal_counts
    )
    p95_index = int(0.95 * (len(estimated) - 1))
    return estimated[p95_index]


def _estimate_memory_bytes(
    replay_stats: ReplayStats, base_config: Dict[str, Any]
) -> float:
    if not replay_stats.signal_ids:
        return 0.0
    scan_interval = get_engine_scan_interval(base_config)
    sample_signal_id = replay_stats.signal_ids[0]
    signal_config = build_signal_config(
        base_config, sample_signal_id, scan_interval
    )
    buffers = (
        signal_config.ma_window
        + signal_config.variance_window
        + signal_config.freq_window
        + signal_config.missing_window
        + signal_config.stale_window
        + signal_config.stale_recovery_window
        + signal_config.step_baseline_window
        + signal_config.step_persistence_scans
        + signal_config.step_recovery_scans
    )
    fft_overhead = signal_config.freq_window if signal_config.enable_fft else 0
    per_signal_bytes = (buffers + fft_overhead) * 8 + 256
    return float(per_signal_bytes * len(replay_stats.signal_ids))


def _augment_metrics(
    metrics: Dict[str, Any],
    replay_stats: ReplayStats,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    precision = float(metrics.get("detection_precision", 0.0))
    metrics["incident_f1"] = float(metrics.get("detection_f1", 0.0))
    metrics["false_alarm_rate"] = max(0.0, 1.0 - precision)
    metrics["scan_p95_estimate"] = _estimate_scan_p95(replay_stats, config)
    metrics["memory_estimate_bytes"] = _estimate_memory_bytes(
        replay_stats, config
    )
    return metrics


def _candidate_order(
    candidates: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    seed: int,
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    ordered = list(candidates)
    rng = random.Random(seed)
    rng.shuffle(ordered)
    return ordered


def _scan_budgets(
    replay_stats: ReplayStats, fractions: Sequence[float]
) -> List[int]:
    if replay_stats.scan_count == 0:
        return [0]
    budgets = []
    for fraction in fractions:
        safe_fraction = max(0.0, min(1.0, fraction))
        budget = int(max(1, round(replay_stats.scan_count * safe_fraction)))
        budgets.append(min(replay_stats.scan_count, budget))
    if budgets[-1] != replay_stats.scan_count:
        budgets.append(replay_stats.scan_count)
    return budgets


def _flatten_config(
    config: Dict[str, Any], prefix: str = ""
) -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key, value in config.items():
        path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        if isinstance(value, dict):
            flat.update(_flatten_config(value, path))
        else:
            flat[path] = value
    return flat


def _config_delta(base: Dict[str, Any], updated: Dict[str, Any]) -> str:
    base_flat = _flatten_config(base)
    updated_flat = _flatten_config(updated)
    lines = ["# Config delta", ""]
    for key in sorted(updated_flat.keys() | base_flat.keys()):
        base_value = base_flat.get(key, "<unset>")
        updated_value = updated_flat.get(key, "<unset>")
        if base_value != updated_value:
            lines.append(f"- `{key}`: `{base_value}` -> `{updated_value}`")
    if len(lines) == 2:
        lines.append("- No changes from base config.")
    lines.append("")
    return "\n".join(lines)


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
    score_config: ScoreConfig,
    search_config: SearchConfig,
    replay_stats: ReplayStats,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None
    candidates = _candidate_order(list(overrides_iter), search_config.seed)
    budgets = [replay_stats.scan_count]
    if search_config.strategy == "successive_halving":
        budgets = _scan_budgets(replay_stats, search_config.scan_fractions)

    remaining = list(enumerate(candidates, start=1))
    records_by_id: Dict[str, Dict[str, Any]] = {}

    for round_index, max_scans in enumerate(budgets, start=1):
        round_results: List[Dict[str, Any]] = []
        for idx, (override, metadata) in remaining:
            run_dir = out_dir / f"{run_prefix}_{idx:03d}"
            run_dir.mkdir(parents=True, exist_ok=True)
            config = _deep_merge(base_config, override)
            config_path = run_dir / "config.yaml"
            if not config_path.exists():
                _write_config(config, config_path)
            metrics = {
                "detection_precision": 0.0,
                "detection_recall": 0.0,
                "detection_f1": 0.0,
                "mean_time_to_detect_scans": 0.0,
                "cause_accuracy": 0.0,
                "severity_accuracy": 0.0,
                "spam_metrics": {
                    "total_signal_started": 0,
                    "total_group_started": 0,
                    "starts_ratio": 0.0,
                },
            }
            metrics = _augment_metrics(metrics, replay_stats, config)
            perf_failures = _perf_gate_failures(metrics, gates)
            if perf_failures and any(
                failure["gate"]
                in {"scan_p95_max", "memory_max_bytes"}
                for failure in perf_failures
            ):
                record = {
                    "run_id": run_dir.name,
                    "override": override,
                    "metadata": metadata,
                    "metrics": metrics,
                    "passes_gates": False,
                    "gate_failures": perf_failures,
                    "round": round_index,
                    "max_scans": max_scans,
                    "eliminated": True,
                }
                records_by_id[record["run_id"]] = record
                round_results.append(record)
                continue

            round_dir = run_dir / f"round_{round_index:02d}"
            round_dir.mkdir(parents=True, exist_ok=True)
            replay_metrics = _evaluate_replay(
                replay_input,
                labels_path,
                config_path,
                groups_config,
                round_dir,
                max_scans=max_scans,
                replay_stats=replay_stats,
            )
            replay_metrics = _augment_metrics(
                replay_metrics, replay_stats, config
            )
            replay_metrics["max_scans"] = max_scans
            failures = _gate_failures(replay_metrics, gates)
            passed = _passes_gates(replay_metrics, gates)
            record = {
                "run_id": run_dir.name,
                "override": override,
                "metadata": metadata,
                "metrics": replay_metrics,
                "passes_gates": passed,
                "gate_failures": failures,
                "round": round_index,
                "max_scans": max_scans,
            }
            records_by_id[record["run_id"]] = record
            round_results.append(record)

        if round_index == len(budgets):
            break

        if not round_results:
            remaining = []
            continue

        scored = sorted(
            round_results,
            key=lambda item: _composite_score(
                item["metrics"], score_config
            ),
            reverse=True,
        )
        retain = max(1, int(len(scored) * search_config.retain_fraction))
        retained = {item["run_id"] for item in scored[:retain]}
        eliminated = {item["run_id"] for item in scored[retain:]}
        for run_id in eliminated:
            record = records_by_id.get(run_id)
            if record:
                record["eliminated"] = True
                record["eliminated_round"] = round_index
        remaining = [
            (idx, candidate)
            for idx, candidate in remaining
            if f"{run_prefix}_{idx:03d}" in retained
        ]

    results = [
        records_by_id[run_id]
        for run_id in sorted(records_by_id.keys())
    ]

    for record in results:
        if record["passes_gates"]:
            if best is None or _composite_score(
                record["metrics"], score_config
            ) > _composite_score(best["metrics"], score_config):
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
    failures_path = out_dir / "gate_failures.jsonl"
    with failures_path.open("w", encoding="utf-8") as handle:
        for record in payload.get("results", []):
            if not record.get("passes_gates"):
                payload = {
                    "run_id": record["run_id"],
                    "gate_failures": record.get("gate_failures", []),
                }
                handle.write(json.dumps(payload, sort_keys=True))
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
    score_config = ScoreConfig.from_config(sweep_config)
    search_config = SearchConfig.from_config(sweep_config)
    replay_stats = _load_replay_stats(replay_input)

    summary: Dict[str, Any] = {
        "gates": gates.__dict__,
        "score_weights": score_config.__dict__,
        "search": search_config.__dict__,
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
            score_config=score_config,
            search_config=search_config,
            replay_stats=replay_stats,
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
            score_config=score_config,
            search_config=search_config,
            replay_stats=replay_stats,
        )
        _write_summary(sqi_out, sqi_payload)
        summary["sqi_weights"] = {
            "best": sqi_payload["best"],
            "runs": len(sqi_payload["results"]),
        }

    best_config = dict(base_config)
    best_overrides: Dict[str, Any] = {}
    if args.mode in {"incident_policy", "all"}:
        incident_best = summary.get("incident_policy", {}).get("best")
        if incident_best:
            best_overrides = _deep_merge(
                best_overrides, incident_best.get("override", {})
            )
    if args.mode in {"sqi", "all"}:
        sqi_best = summary.get("sqi_weights", {}).get("best")
        if sqi_best:
            best_overrides = _deep_merge(
                best_overrides, sqi_best.get("override", {})
            )
    if best_overrides:
        best_config = _deep_merge(best_config, best_overrides)
        best_config_path = out_dir / "best_config.yaml"
        _write_config(best_config, best_config_path)
        delta_path = out_dir / "best_config_delta.md"
        delta_path.write_text(
            _config_delta(base_config, best_config), encoding="utf-8"
        )
        summary["best_config"] = str(best_config_path)

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
