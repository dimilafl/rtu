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
from pathlib import Path
from typing import List, Tuple

from sqe.core.engine import SignalQualityEngine, SignalConfig
from sqe import __version__


def load_signal_from_csv(filepath: str) -> Tuple[List[str], List[float]]:
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
        Tuple of (signal_ids, values)
    """
    signal_ids = []
    values = []

    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            signal_ids.append(row['signal_id'])
            values.append(float(row['value']))

    return signal_ids, values


def analyze_command(args):
    """Execute analyze command."""
    print(f"Analyzing signal file: {args.signal_file}")
    print()

    if not Path(args.signal_file).exists():
        print(f"Error: File '{args.signal_file}' not found")
        return 1

    # Load signal data
    try:
        signal_ids, values = load_signal_from_csv(args.signal_file)
    except Exception as e:
        print(f"Error loading file: {e}")
        return 1

    print(f"Loaded {len(values)} samples")
    unique_signals = set(signal_ids)
    print(f"Signals: {', '.join(unique_signals)}")
    print()

    # Initialize engine
    engine = SignalQualityEngine()

    # Process signals
    print("Processing signals...")
    for sig_id, value in zip(signal_ids, values):
        engine.update_single(sig_id, value)

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
            plot_results(engine, signal_ids, values)
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
    engine = SignalQualityEngine(scan_interval=0.1)
    engine.register_signal("SIM_SIGNAL")

    # Generate signal
    print("Generating signal...")
    t = np.linspace(0, args.duration * 0.1, args.duration)
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


def plot_results(engine, signal_ids, values):
    """Plot analysis results."""
    import matplotlib.pyplot as plt

    # Group values by signal
    signals_data = {}
    for sig_id, value in zip(signal_ids, values):
        if sig_id not in signals_data:
            signals_data[sig_id] = []
        signals_data[sig_id].append(value)

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
        help='Path to CSV file containing signal data'
    )
    analyze_parser.add_argument(
        '--plot',
        action='store_true',
        help='Generate plots (requires matplotlib)'
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
