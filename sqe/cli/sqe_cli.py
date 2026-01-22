#!/usr/bin/env python3
"""
SQE Command-Line Interface

Usage:
    sqe analyze --signal-file data.csv [--plot]
    sqe simulate --duration 100 --noise 1.0 [--plot]
    sqe version
"""

import argparse
import sys
import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Dict, Iterable, List, Optional, Tuple

from sqe.core.engine import SignalQualityEngine
from sqe.config.loader import (
    ConfigError,
    build_signal_config,
    get_engine_scan_interval,
    load_config,
)
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

    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                SignalRow(
                    timestamp=_parse_optional_float(row.get('timestamp')),
                    signal_id=row['signal_id'],
                    value=_parse_optional_float(row.get('value'))
                )
            )

    return rows


def build_scans(rows: Iterable[SignalRow]) -> Tuple[List[str], List[Tuple[Optional[float], Dict[str, Optional[float]]]]]:
    signal_ids: List[str] = []
    seen_signals = set()
    grouped: Dict[Optional[float], Dict[str, Optional[float]]] = {}

    for row in rows:
        if row.signal_id not in seen_signals:
            seen_signals.add(row.signal_id)
            signal_ids.append(row.signal_id)
        grouped.setdefault(row.timestamp, {})[row.signal_id] = row.value

    scans = [
        (timestamp, {signal_id: grouped[timestamp].get(signal_id) for signal_id in signal_ids})
        for timestamp in grouped
    ]
    return signal_ids, scans


def derive_scan_interval(timestamps: Iterable[Optional[float]], default_interval: float = 0.1) -> float:
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
    signal_ids, scans = build_scans(rows)
    scan_interval = derive_scan_interval(
        (timestamp for timestamp, _ in scans),
        default_interval=get_engine_scan_interval(config)
    )

    print(f"Loaded {len(rows)} samples")
    unique_signals = set(signal_ids)
    print(f"Signals: {', '.join(unique_signals)}")
    print()

    # Initialize engine
    engine = SignalQualityEngine(scan_interval=scan_interval)
    for signal_id in signal_ids:
        engine.register_signal(
            signal_id,
            build_signal_config(config, signal_id, scan_interval)
        )

    # Process signals
    print("Processing signals...")
    for _, scan_values in scans:
        engine.update(scan_values)

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
        print(f"  Missing Samples: {stats['missing_count']} ({stats['missing_ratio']:.1%})")

        sqi_stats = stats['sqi_stats']
        print(f"  Signal Quality:")
        print(f"    Mean SQI: {sqi_stats['mean_sqi']:.1f}")
        print(f"    Min SQI:  {sqi_stats['min_sqi']:.1f}")
        print(f"    Max SQI:  {sqi_stats['max_sqi']:.1f}")
        print()

    # Plot if requested
    if args.plot:
        try:
            import matplotlib.pyplot as plt
            print("Generating plots...")
            plot_results(engine, signal_ids, rows)
            print("Plot displayed.")
        except ImportError:
            print("Warning: matplotlib not available. Install with: pip install matplotlib")

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
    scan_interval = get_engine_scan_interval(config)
    engine = SignalQualityEngine(scan_interval=scan_interval)
    engine.register_signal(
        "SIM_SIGNAL",
        build_signal_config(config, "SIM_SIGNAL", scan_interval)
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
    for value in signal:
        result = engine.update_single("SIM_SIGNAL", value)
        if result:
            results.append(result)

    # Print statistics
    print()
    print("=" * 70)
    print("Simulation Results")
    print("=" * 70)
    print()

    stats = engine.get_signal_stats("SIM_SIGNAL")
    sqi_stats = stats['sqi_stats']

    print(f"Samples Processed: {stats['sample_count']}")
    print(f"Signal Quality:")
    print(f"  Mean SQI: {sqi_stats['mean_sqi']:.1f}")
    print(f"  Min SQI:  {sqi_stats['min_sqi']:.1f}")
    print(f"  Max SQI:  {sqi_stats['max_sqi']:.1f}")
    print()

    if results:
        final = results[-1]
        print(f"Final State:")
        print(f"  Raw Value: {final.raw:.2f}")
        print(f"  Filtered (EWMA): {final.filtered_ewma:.2f}")
        print(f"  Noise Level: {final.noise_level:.3f}")
        print(f"  SQI: {final.sqi:.1f} ({final.quality_class})")
        print()

    # Plot if requested
    if args.plot:
        try:
            import matplotlib.pyplot as plt
            print("Generating plots...")
            plot_simulation(signal, results)
            print("Plot displayed.")
        except ImportError:
            print("Warning: matplotlib not available. Install with: pip install matplotlib")

    return 0


def version_command(args):
    """Execute version command."""
    print(f"Signal Quality Engine (SQE) version {__version__}")
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
    fig, axes = plt.subplots(len(signals_data), 1, figsize=(12, 4*len(signals_data)))

    if len(signals_data) == 1:
        axes = [axes]

    for ax, (sig_id, values) in zip(axes, signals_data.items()):
        ax.plot(values, label='Raw Signal', alpha=0.7)
        ax.set_title(f'{sig_id}')
        ax.set_xlabel('Sample')
        ax.set_ylabel('Value')
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
    ax1.plot(raw, label='Raw Signal', alpha=0.5)
    ax1.plot(filtered, label='Filtered Signal', linewidth=2)
    ax1.set_title('Signal Processing')
    ax1.set_xlabel('Sample')
    ax1.set_ylabel('Value')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # SQI plot
    ax2.plot(sqi, color='green', linewidth=2)
    ax2.axhline(y=75, color='yellow', linestyle='--', alpha=0.5, label='Good Threshold')
    ax2.axhline(y=50, color='orange', linestyle='--', alpha=0.5, label='Fair Threshold')
    ax2.axhline(y=25, color='red', linestyle='--', alpha=0.5, label='Poor Threshold')
    ax2.set_title('Signal Quality Index (SQI)')
    ax2.set_xlabel('Sample')
    ax2.set_ylabel('SQI')
    ax2.set_ylim(0, 100)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Signal Quality Engine (SQE) - DSP analysis for SCADA signals'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze signal from file')
    analyze_parser.add_argument(
        '--signal-file',
        required=True,
        help=(
            'Path to CSV file containing signal data. '
            'Required columns: timestamp, signal_id, value. '
            'Empty timestamp/value entries are treated as missing (None).'
        )
    )
    analyze_parser.add_argument(
        '--plot',
        action='store_true',
        help='Generate plots (requires matplotlib)'
    )
    analyze_parser.add_argument(
        '--config',
        help='Optional path to YAML config to override defaults'
    )

    # Simulate command
    simulate_parser = subparsers.add_parser('simulate', help='Simulate signal processing')
    simulate_parser.add_argument(
        '--duration',
        type=int,
        default=100,
        help='Number of samples to simulate (default: 100)'
    )
    simulate_parser.add_argument(
        '--noise',
        type=float,
        default=1.0,
        help='Noise level (std dev) (default: 1.0)'
    )
    simulate_parser.add_argument(
        '--plot',
        action='store_true',
        help='Generate plots (requires matplotlib)'
    )
    simulate_parser.add_argument(
        '--config',
        help='Optional path to YAML config to override defaults'
    )

    # Version command
    version_parser = subparsers.add_parser('version', help='Show version')

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute command
    if args.command == 'analyze':
        return analyze_command(args)
    elif args.command == 'simulate':
        return simulate_command(args)
    elif args.command == 'version':
        return version_command(args)
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
