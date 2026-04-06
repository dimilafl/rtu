#!/usr/bin/env python3
"""
SQE Command-Line Interface

Usage:
    sqe analyze --signal-file data.csv [--plot]
    sqe simulate --duration 100 --noise 1.0 [--plot]
    sqe incidents --signal-file data.csv [--out incidents.jsonl]
    sqe replay --in scans.jsonl --config cfg.yaml --out out_dir
    sqe eval --replay-out out_dir --labels labels.yaml
    sqe version
"""

import argparse
import sys
import csv
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Dict, Iterable, List, Optional, Tuple
from collections import Counter

from sqe.core.engine import SignalQualityEngine
from sqe.core.event_filter import EventFilter
from sqe.core.incidents import (
    IncidentEngine,
    IncidentEventType,
    required_causes_from_policy,
)
from sqe.core.group_incidents import GroupIncidentEngine
from sqe.core.grouping import GroupResolver
from sqe.config.loader import (
    ConfigError,
    build_signal_config,
    configure_logging,
    get_engine_auto_register,
    get_engine_max_signals_policy,
    get_engine_max_signals,
    get_engine_scan_interval,
    get_engine_treat_missing_signals_as_none,
    get_engine_unknown_signal_policy,
    get_logging_settings,
    get_performance_settings,
    get_event_filter_policy,
    get_incident_policy,
    get_group_incident_policy,
    get_grouping_config,
    load_config,
    load_groups_config,
)
from sqe.eval.labels import load_labels
from sqe.eval.metrics import (
    compute_metrics,
    count_group_started_events,
    load_predicted_started_events,
)
from sqe.ops.service import RealtimeQualityService
from sqe.replay.runner import run_replay
from sqe import __version__


@dataclass(frozen=True)
class SignalRow:
    timestamp: Optional[float]
    signal_id: str
    value: Optional[float]


def _parse_optional_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped)


def load_signal_from_csv(filepath: str) -> List[SignalRow]:
    """
    Load signal data from CSV file.

    Expected format:
        timestamp,signal_id,value
        0.0,AI_001,42.5
        0.1,AI_001,43.2
        ...

    Args:
        filepath: Path to CSV file

    Returns:
        List of SignalRow entries. Empty timestamp/value entries are returned as None.
    """
    rows: List[SignalRow] = []

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        required_fields = {"timestamp", "signal_id", "value"}
        fieldnames = set(reader.fieldnames or [])
        missing_fields = required_fields - fieldnames
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"Missing required CSV columns: {missing}")
        for row in reader:
            if not any(
                value and value.strip() for value in row.values() if value is not None
            ):
                continue
            signal_id = (row.get("signal_id") or "").strip()
            if not signal_id:
                raise ValueError(f"Missing signal_id value on line {reader.line_num}")
            rows.append(
                SignalRow(
                    timestamp=_parse_optional_float(row.get("timestamp")),
                    signal_id=signal_id,
                    value=_parse_optional_float(row.get("value")),
                )
            )

    return rows


def build_scans(
    rows: Iterable[SignalRow],
) -> Tuple[List[str], List[Tuple[Optional[float], Dict[str, Optional[float]]]]]:
    signal_ids: List[str] = []
    seen_signals = set()
    grouped: Dict[float, Dict[str, Optional[float]]] = {}
    missing_timestamp_rows: List[Dict[str, Optional[float]]] = []

    for row in rows:
        if row.signal_id not in seen_signals:
            seen_signals.add(row.signal_id)
            signal_ids.append(row.signal_id)
        if row.timestamp is None:
            missing_timestamp_rows.append({row.signal_id: row.value})
        else:
            grouped.setdefault(row.timestamp, {})[row.signal_id] = row.value

    scans = [
        (
            timestamp,
            {signal_id: grouped[timestamp].get(signal_id) for signal_id in signal_ids},
        )
        for timestamp in sorted(grouped)
    ]
    scans.extend(
        (None, {signal_id: scan.get(signal_id) for signal_id in signal_ids})
        for scan in missing_timestamp_rows
    )
    return signal_ids, scans


def derive_scan_interval(
    timestamps: Iterable[Optional[float]], default_interval: float = 0.1
) -> float:
    deltas = []
    last_timestamp: Optional[float] = None

    for timestamp in timestamps:
        if timestamp is None:
            continue
        if last_timestamp is not None:
            delta = timestamp - last_timestamp
            if delta > 0:
                deltas.append(delta)
        last_timestamp = timestamp

    return median(deltas) if deltas else default_interval


def analyze_command(args):
    """Execute analyze command."""
    print(f"Analyzing signal file: {args.signal_file}")
    print()

    if not Path(args.signal_file).exists():
        print(f"Error: File '{args.signal_file}' not found")
        return 1

    # Load signal data
    try:
        rows = load_signal_from_csv(args.signal_file)
    except Exception as e:
        print(f"Error loading file: {e}")
        return 1

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Error loading config: {exc}")
        return 1
    configure_logging(config)
    signal_ids, scans = build_scans(rows)
    scan_interval = derive_scan_interval(
        (timestamp for timestamp, _ in scans),
        default_interval=get_engine_scan_interval(config),
    )
    auto_register = get_engine_auto_register(config)
    max_signals = get_engine_max_signals(config)
    missing_policy = get_engine_treat_missing_signals_as_none(config)
    unknown_signal_policy = get_engine_unknown_signal_policy(config)
    max_signals_policy = get_engine_max_signals_policy(config)
    logging_settings = get_logging_settings(config)
    performance_settings = get_performance_settings(config)

    print(f"Loaded {len(rows)} samples")
    unique_signals = set(signal_ids)
    print(f"Signals: {', '.join(unique_signals)}")
    print()

    # Initialize engine
    incident_policy = get_incident_policy(config)
    required_causes = required_causes_from_policy(incident_policy)
    engine = SignalQualityEngine(
        scan_interval=scan_interval,
        auto_register=auto_register,
        max_signals=max_signals,
        treat_missing_signals_as_none=missing_policy,
        unknown_signal_policy=unknown_signal_policy,
        max_signals_policy=max_signals_policy,
        log_scan_timing=logging_settings["log_scan_timing"],
        log_quality_changes=logging_settings["log_quality_changes"],
        log_anomalies=logging_settings["log_anomalies"],
        compute_budget_ms=performance_settings["compute_budget_ms"],
        load_shed_p95_window=performance_settings["load_shed_p95_window"],
        load_shed_oscillation_cadence=performance_settings[
            "load_shed_oscillation_cadence"
        ],
        load_shed_skip_fft=performance_settings["load_shed_skip_fft"],
        required_incident_causes=required_causes,
    )
    for signal_id in signal_ids:
        engine.register_signal(
            signal_id, build_signal_config(config, signal_id, scan_interval)
        )

    # Process signals
    print("Processing signals...")
    for timestamp, scan_values in scans:
        engine.update(scan_values, timestamp=timestamp)

    # Print statistics
    print()
    print("=" * 70)
    print("Analysis Results")
    print("=" * 70)
    print()

    all_stats = engine.get_all_stats()

    for sig_id, stats in all_stats.items():
        print(f"{sig_id}:")
        print(f"  Samples Processed: {stats['sample_count']}")
        print(
            f"  Missing Samples: {stats['missing_count']} ({stats['missing_ratio']:.1%})"
        )

        sqi_stats = stats["sqi_stats"]
        print("  Signal Quality:")
        print(f"    Mean SQI: {sqi_stats['mean_sqi']:.1f}")
        print(f"    Min SQI:  {sqi_stats['min_sqi']:.1f}")
        print(f"    Max SQI:  {sqi_stats['max_sqi']:.1f}")
        print()

    # Plot if requested
    if args.plot:
        try:
            print("Generating plots...")
            plot_results(engine, signal_ids, rows)
            print("Plot displayed.")
        except ImportError:
            print(
                "Warning: matplotlib not available. Install with: pip install matplotlib"
            )

    return 0


def simulate_command(args):
    """Execute simulate command."""
    import numpy as np

    print(f"Simulating signal for {args.duration} samples")
    print(f"Noise level: {args.noise}")
    print()

    # Initialize engine
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Error loading config: {exc}")
        return 1
    configure_logging(config)
    scan_interval = get_engine_scan_interval(config)
    logging_settings = get_logging_settings(config)
    performance_settings = get_performance_settings(config)
    engine = SignalQualityEngine(
        scan_interval=scan_interval,
        auto_register=get_engine_auto_register(config),
        max_signals=get_engine_max_signals(config),
        treat_missing_signals_as_none=get_engine_treat_missing_signals_as_none(config),
        unknown_signal_policy=get_engine_unknown_signal_policy(config),
        max_signals_policy=get_engine_max_signals_policy(config),
        log_scan_timing=logging_settings["log_scan_timing"],
        log_quality_changes=logging_settings["log_quality_changes"],
        log_anomalies=logging_settings["log_anomalies"],
        compute_budget_ms=performance_settings["compute_budget_ms"],
        load_shed_p95_window=performance_settings["load_shed_p95_window"],
        load_shed_oscillation_cadence=performance_settings[
            "load_shed_oscillation_cadence"
        ],
        load_shed_skip_fft=performance_settings["load_shed_skip_fft"],
    )
    engine.register_signal(
        "SIM_SIGNAL", build_signal_config(config, "SIM_SIGNAL", scan_interval)
    )

    # Generate signal
    print("Generating signal...")
    t = np.linspace(0, args.duration * scan_interval, args.duration)
    clean_signal = 10.0 * np.sin(2 * np.pi * 0.5 * t)
    noise = np.random.normal(0, args.noise, args.duration)
    signal = clean_signal + noise

    # Process signal
    print("Processing...")
    results = []
    for index, value in enumerate(signal):
        timestamp = index * scan_interval
        result = engine.update_single("SIM_SIGNAL", value, timestamp=timestamp)
        if result:
            results.append(result)

    # Print statistics
    print()
    print("=" * 70)
    print("Simulation Results")
    print("=" * 70)
    print()

    stats = engine.get_signal_stats("SIM_SIGNAL")
    sqi_stats = stats["sqi_stats"]

    print(f"Samples Processed: {stats['sample_count']}")
    print("Signal Quality:")
    print(f"  Mean SQI: {sqi_stats['mean_sqi']:.1f}")
    print(f"  Min SQI:  {sqi_stats['min_sqi']:.1f}")
    print(f"  Max SQI:  {sqi_stats['max_sqi']:.1f}")
    print()

    if results:
        final = results[-1]
        print("Final State:")
        print(f"  Raw Value: {final.raw:.2f}")
        print(f"  Filtered (EWMA): {final.filtered_ewma:.2f}")
        print(f"  Noise Level: {final.noise_level:.3f}")
        print(f"  SQI: {final.sqi:.1f} ({final.quality_class})")
        print()

    # Plot if requested
    if args.plot:
        try:
            print("Generating plots...")
            plot_simulation(signal, results)
            print("Plot displayed.")
        except ImportError:
            print(
                "Warning: matplotlib not available. Install with: pip install matplotlib"
            )

    return 0


def version_command(args):
    """Execute version command."""
    print(f"Signal Quality Engine (SQE) version {__version__}")
    return 0


def incidents_command(args):
    """Execute incidents command."""
    print(f"Generating incidents from signal file: {args.signal_file}")
    print()

    if not Path(args.signal_file).exists():
        print(f"Error: File '{args.signal_file}' not found")
        return 1

    try:
        rows = load_signal_from_csv(args.signal_file)
    except Exception as exc:
        print(f"Error loading file: {exc}")
        return 1

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Error loading config: {exc}")
        return 1

    configure_logging(config)
    signal_ids, scans = build_scans(rows)
    scan_interval = derive_scan_interval(
        (timestamp for timestamp, _ in scans),
        default_interval=get_engine_scan_interval(config),
    )
    auto_register = get_engine_auto_register(config)
    max_signals = get_engine_max_signals(config)
    missing_policy = get_engine_treat_missing_signals_as_none(config)
    unknown_signal_policy = get_engine_unknown_signal_policy(config)
    max_signals_policy = get_engine_max_signals_policy(config)
    logging_settings = get_logging_settings(config)
    performance_settings = get_performance_settings(config)

    incident_policy = get_incident_policy(config)
    required_causes = required_causes_from_policy(incident_policy)
    run_id = uuid.uuid4().hex
    engine = SignalQualityEngine(
        scan_interval=scan_interval,
        auto_register=auto_register,
        max_signals=max_signals,
        treat_missing_signals_as_none=missing_policy,
        unknown_signal_policy=unknown_signal_policy,
        max_signals_policy=max_signals_policy,
        log_scan_timing=logging_settings["log_scan_timing"],
        log_quality_changes=logging_settings["log_quality_changes"],
        log_anomalies=logging_settings["log_anomalies"],
        compute_budget_ms=performance_settings["compute_budget_ms"],
        load_shed_p95_window=performance_settings["load_shed_p95_window"],
        load_shed_oscillation_cadence=performance_settings[
            "load_shed_oscillation_cadence"
        ],
        load_shed_skip_fft=performance_settings["load_shed_skip_fft"],
        required_incident_causes=required_causes,
    )
    for signal_id in signal_ids:
        engine.register_signal(
            signal_id, build_signal_config(config, signal_id, scan_interval)
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    incident_engine = IncidentEngine(incident_policy, run_id=run_id)
    event_filter_policy = get_event_filter_policy(config)
    event_filter = EventFilter(event_filter_policy)
    group_events_path: Optional[Path] = None
    group_resolver = None
    group_incident_engine = None
    groups_config_path = getattr(args, "groups_config", None)
    if groups_config_path:
        try:
            group_config = load_groups_config(groups_config_path)
            grouping_config = get_grouping_config(group_config)
            group_policy = get_group_incident_policy(group_config, grouping_config)
        except (ValueError, ConfigError) as exc:
            print(f"Error loading groups config: {exc}")
            return 1
        group_resolver = GroupResolver(grouping_config)
        group_incident_engine = GroupIncidentEngine(group_policy, run_id=run_id)
        group_events_path = out_path.parent / "group_incidents.jsonl"
        group_events_path.write_text("", encoding="utf-8")

    service = RealtimeQualityService(
        engine,
        incident_engine,
        group_resolver=group_resolver,
        group_incident_engine=group_incident_engine,
        event_filter=event_filter,
        event_filter_policy=event_filter_policy,
    )

    event_counts = Counter()
    cause_counts = Counter()
    group_event_counts = Counter()

    group_handle = (
        group_events_path.open("a", encoding="utf-8") if group_events_path else None
    )
    with out_path.open("w", encoding="utf-8") as handle:
        for timestamp, scan_values in scans:
            _, events, group_events = service.process_scan(
                scan_values, timestamp=timestamp
            )
            for event in events:
                event_counts[event.event_type] += 1
                if event.event_type == IncidentEventType.STARTED:
                    cause_counts[event.incident.cause] += 1
                payload = {
                    "event_type": event.event_type.value,
                    "message": event.message,
                    "recommended_action": event.recommended_action,
                    "incident": {
                        "incident_id": event.incident.incident_id,
                        "signal_id": event.incident.signal_id,
                        "cause": event.incident.cause.value,
                        "severity": event.incident.severity.value,
                        "start_timestamp": event.incident.start_timestamp,
                        "last_timestamp": event.incident.last_timestamp,
                        "end_timestamp": event.incident.end_timestamp,
                        "min_sqi": event.incident.min_sqi,
                        "last_sqi": event.incident.last_sqi,
                        "start_scan_index": event.incident.start_scan_index,
                        "last_scan_index": event.incident.last_scan_index,
                        "details": event.incident.details,
                    },
                }
                handle.write(json.dumps(payload, sort_keys=True))
                handle.write("\n")
            if group_handle:
                for event in group_events:
                    group_event_counts[event.event_type] += 1
                    incident = event.incident
                    details = incident.details or {}
                    payload = {
                        "group_id": incident.group_id,
                        "group_incident_id": incident.group_incident_id,
                        "timestamp": incident.last_timestamp,
                        "event_type": event.event_type.value,
                        "severity": incident.severity.value,
                        "cause": incident.cause.value,
                        "degraded_fraction": details.get("degraded_fraction", 0.0),
                        "degraded_members": list(incident.degraded_members),
                        "counts": {
                            "members_total": details.get("members_total", 0),
                            "members_degraded": details.get("members_degraded", 0),
                        },
                    }
                    group_handle.write(json.dumps(payload, sort_keys=True))
                    group_handle.write("\n")
        handle.flush()
    if group_handle:
        group_handle.flush()
        group_handle.close()

    started = event_counts[IncidentEventType.STARTED]
    resolved = event_counts[IncidentEventType.RESOLVED]
    updated = event_counts[IncidentEventType.UPDATED]

    print("Incident summary")
    print(f"  Started: {started}")
    print(f"  Updated: {updated}")
    print(f"  Resolved: {resolved}")
    if cause_counts:
        top_causes = ", ".join(
            f"{cause.value} ({count})" for cause, count in cause_counts.most_common(3)
        )
        print(f"  Top causes: {top_causes}")
    else:
        print("  Top causes: none")

    if group_events_path:
        group_started = group_event_counts[IncidentEventType.STARTED]
        group_updated = group_event_counts[IncidentEventType.UPDATED]
        group_resolved = group_event_counts[IncidentEventType.RESOLVED]
        print("Group incident summary")
        print(f"  Started: {group_started}")
        print(f"  Updated: {group_updated}")
        print(f"  Resolved: {group_resolved}")

    return 0


def replay_command(args):
    """Execute replay command."""
    try:
        run_replay(
            input_jsonl_path=args.input_jsonl,
            config_path=args.config,
            groups_config_path=args.groups_config,
            out_dir=args.out,
        )
    except (ValueError, ConfigError, OSError) as exc:
        print(f"Error running replay: {exc}")
        return 1
    print(f"Replay output written to {args.out}")
    return 0


def eval_command(args):
    """Execute eval command."""
    try:
        labels = load_labels(args.labels)
        replay_dir = Path(args.replay_out)
        incidents_path = replay_dir / "incidents.jsonl"
        group_incidents_path = replay_dir / "group_incidents.jsonl"
        predicted = load_predicted_started_events(str(incidents_path))
        group_started = count_group_started_events(str(group_incidents_path))
        metrics = compute_metrics(predicted, labels, group_started)
    except (OSError, ValueError) as exc:
        print(f"Error running eval: {exc}")
        return 1

    ordered_keys = [
        "detection_precision",
        "detection_recall",
        "detection_f1",
        "mean_time_to_detect_scans",
        "cause_accuracy",
        "severity_accuracy",
    ]
    for key in ordered_keys:
        print(f"{key}: {metrics[key]}")

    spam_metrics = metrics["spam_metrics"]
    print(f"spam_metrics.total_signal_started: {spam_metrics['total_signal_started']}")
    print(f"spam_metrics.total_group_started: {spam_metrics['total_group_started']}")
    print(f"spam_metrics.starts_ratio: {spam_metrics['starts_ratio']}")

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return 0


def plot_results(engine, signal_ids, rows):
    """Plot analysis results."""
    import matplotlib.pyplot as plt

    # Group values by signal
    signals_data = {}
    for row in rows:
        if row.signal_id not in signals_data:
            signals_data[row.signal_id] = []
        if row.value is not None:
            signals_data[row.signal_id].append(row.value)

    # Create plots
    fig, axes = plt.subplots(len(signals_data), 1, figsize=(12, 4 * len(signals_data)))

    if len(signals_data) == 1:
        axes = [axes]

    for ax, (sig_id, values) in zip(axes, signals_data.items()):
        ax.plot(values, label="Raw Signal", alpha=0.7)
        ax.set_title(f"{sig_id}")
        ax.set_xlabel("Sample")
        ax.set_ylabel("Value")
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def plot_simulation(signal, results):
    """Plot simulation results."""
    import matplotlib.pyplot as plt

    # Extract data
    raw = [r.raw for r in results]
    filtered = [r.filtered_ewma for r in results]
    sqi = [r.sqi for r in results]

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

    # Signal plot
    ax1.plot(raw, label="Raw Signal", alpha=0.5)
    ax1.plot(filtered, label="Filtered Signal", linewidth=2)
    ax1.set_title("Signal Processing")
    ax1.set_xlabel("Sample")
    ax1.set_ylabel("Value")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # SQI plot
    ax2.plot(sqi, color="green", linewidth=2)
    ax2.axhline(y=75, color="yellow", linestyle="--", alpha=0.5, label="Good Threshold")
    ax2.axhline(y=50, color="orange", linestyle="--", alpha=0.5, label="Fair Threshold")
    ax2.axhline(y=25, color="red", linestyle="--", alpha=0.5, label="Poor Threshold")
    ax2.set_title("Signal Quality Index (SQI)")
    ax2.set_xlabel("Sample")
    ax2.set_ylabel("SQI")
    ax2.set_ylim(0, 100)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Signal Quality Engine (SQE) - DSP analysis for SCADA signals"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze signal from file")
    analyze_parser.add_argument(
        "--signal-file",
        required=True,
        help=(
            "Path to CSV file containing signal data. "
            "Required columns: timestamp, signal_id, value. "
            "Empty timestamp/value entries are treated as missing (None)."
        ),
    )
    analyze_parser.add_argument(
        "--plot", action="store_true", help="Generate plots (requires matplotlib)"
    )
    analyze_parser.add_argument(
        "--config", help="Optional path to YAML config to override defaults"
    )

    # Simulate command
    simulate_parser = subparsers.add_parser(
        "simulate", help="Simulate signal processing"
    )
    simulate_parser.add_argument(
        "--duration",
        type=int,
        default=100,
        help="Number of samples to simulate (default: 100)",
    )
    simulate_parser.add_argument(
        "--noise", type=float, default=1.0, help="Noise level (std dev) (default: 1.0)"
    )
    simulate_parser.add_argument(
        "--plot", action="store_true", help="Generate plots (requires matplotlib)"
    )
    simulate_parser.add_argument(
        "--config", help="Optional path to YAML config to override defaults"
    )

    # Version command
    subparsers.add_parser("version", help="Show version")

    # Incidents command
    incidents_parser = subparsers.add_parser(
        "incidents", help="Generate incident events from signal file"
    )
    incidents_parser.add_argument(
        "--signal-file",
        required=True,
        help=(
            "Path to CSV file containing signal data. "
            "Required columns: timestamp, signal_id, value."
        ),
    )
    incidents_parser.add_argument(
        "--config", help="Optional path to YAML config to override defaults"
    )
    incidents_parser.add_argument(
        "--out", default="incidents.jsonl", help="Output JSONL file for incident events"
    )
    incidents_parser.add_argument(
        "--groups-config", help="Optional path to group incident config YAML"
    )

    # Replay command
    replay_parser = subparsers.add_parser(
        "replay", help="Replay scan inputs into deterministic outputs"
    )
    replay_parser.add_argument(
        "--in",
        dest="input_jsonl",
        required=True,
        help="Input JSONL file of scan records",
    )
    replay_parser.add_argument(
        "--config", required=True, help="Path to SQE config YAML"
    )
    replay_parser.add_argument(
        "--out", required=True, help="Output directory for replay artifacts"
    )
    replay_parser.add_argument(
        "--groups-config", help="Optional path to group incident config YAML"
    )

    # Eval command
    eval_parser = subparsers.add_parser(
        "eval", help="Evaluate replay outputs against incident labels"
    )
    eval_parser.add_argument(
        "--replay-out",
        required=True,
        help="Replay output directory containing incidents.jsonl",
    )
    eval_parser.add_argument(
        "--labels", required=True, help="Path to YAML/JSON label file"
    )
    eval_parser.add_argument(
        "--out-json", help="Optional path to write metrics JSON output"
    )

    # Offline tuning command
    tuning_parser = subparsers.add_parser(
        "offline-tuning", help="Run offline tuning sweeps for incident policy and SQI"
    )
    tuning_parser.add_argument(
        "--replay-input", required=True, help="Path to replay input JSONL"
    )
    tuning_parser.add_argument(
        "--labels", required=True, help="Path to incident labels YAML/JSON"
    )
    tuning_parser.add_argument(
        "--sweep-config", required=True, help="Path to sweep config YAML"
    )
    tuning_parser.add_argument(
        "--out-dir", required=True, help="Directory to store sweep outputs"
    )
    tuning_parser.add_argument(
        "--base-config", help="Optional base config YAML to override defaults"
    )
    tuning_parser.add_argument(
        "--groups-config", help="Optional groups config YAML for group incidents"
    )
    tuning_parser.add_argument(
        "--mode",
        choices=["incident_policy", "sqi", "all"],
        default="all",
        help="Which sweep to run (default: all)",
    )

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute command
    if args.command == "analyze":
        return analyze_command(args)
    elif args.command == "simulate":
        return simulate_command(args)
    elif args.command == "version":
        return version_command(args)
    elif args.command == "incidents":
        return incidents_command(args)
    elif args.command == "replay":
        return replay_command(args)
    elif args.command == "eval":
        return eval_command(args)
    elif args.command == "offline-tuning":
        from sqe.tools.offline_tuning import run_offline_tuning

        return run_offline_tuning(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
