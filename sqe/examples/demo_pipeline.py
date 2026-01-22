"""
Demo: Complete SQE Pipeline

Demonstrates the full Signal Quality Engine pipeline
with simulated RTU signals.
"""

import numpy as np
import time
from sqe.core.engine import SignalQualityEngine, SignalConfig


def generate_clean_signal(t: float, freq: float = 0.5, amplitude: float = 10.0) -> float:
    """Generate clean sinusoidal signal."""
    return amplitude * np.sin(2 * np.pi * freq * t)


def generate_noisy_signal(t: float, noise_level: float = 0.5) -> float:
    """Generate signal with additive noise."""
    clean = generate_clean_signal(t)
    noise = np.random.normal(0, noise_level)
    return clean + noise


def generate_drifting_signal(t: float, drift_rate: float = 0.1) -> float:
    """Generate signal with linear drift."""
    clean = generate_clean_signal(t)
    drift = drift_rate * t
    return clean + drift


def main():
    """Run complete pipeline demonstration."""
    print("=" * 60)
    print("Signal Quality Engine - Complete Pipeline Demo")
    print("=" * 60)
    print()

    # Initialize engine
    print("Initializing Signal Quality Engine...")
    engine = SignalQualityEngine(scan_interval=0.1)

    # Register signals with custom configurations
    print("Registering signals...")

    # Clean signal
    engine.register_signal(
        "CLEAN_SIGNAL",
        SignalConfig(
            signal_id="CLEAN_SIGNAL",
            ewma_alpha=0.3,
            reference_frequencies=[0.5, 1.0]
        )
    )

    # Noisy signal
    engine.register_signal(
        "NOISY_SIGNAL",
        SignalConfig(
            signal_id="NOISY_SIGNAL",
            ewma_alpha=0.2,  # More smoothing for noisy signal
            variance_window=30
        )
    )

    # Drifting signal
    engine.register_signal(
        "DRIFT_SIGNAL",
        SignalConfig(
            signal_id="DRIFT_SIGNAL",
            small_drift_threshold=0.2,
            large_drift_threshold=2.0
        )
    )

    print(f"Registered {len(engine.get_registered_signals())} signals")
    print()

    # Simulate scan cycles
    print("Running simulation...")
    print("-" * 60)

    scan_count = 100
    dt = 0.1  # 100ms scan interval

    for scan in range(scan_count):
        t = scan * dt

        # Generate signal values
        signals = {
            "CLEAN_SIGNAL": generate_clean_signal(t),
            "NOISY_SIGNAL": generate_noisy_signal(t, noise_level=2.0),
            "DRIFT_SIGNAL": generate_drifting_signal(t, drift_rate=0.3)
        }

        # Process through engine
        results = engine.update(signals)

        # Print periodic updates
        if scan % 20 == 0:
            print(f"\nScan {scan}:")
            for sig_id, result in results.items():
                print(f"  {sig_id}:")
                print(f"    Raw: {result.raw:.2f}")
                print(f"    Filtered: {result.filtered_ewma:.2f}")
                print(f"    SQI: {result.sqi:.1f} ({result.quality_class})")
                if result.sqi_components:
                    components = ", ".join(
                        f"{name}={score:.1f}"
                        for name, score in result.sqi_components.items()
                    )
                    print(f"    SQI Components: {components}")
                print(f"    Drift: {result.drift:.3f} ({result.drift_type})")
                print(f"    Noise: {result.noise_level:.3f}")

        # Simulate scan timing
        time.sleep(0.01)  # Reduced sleep for demo

    print()
    print("-" * 60)
    print("Simulation complete!")
    print()

    # Print final statistics
    print("=" * 60)
    print("Final Statistics")
    print("=" * 60)
    print()

    all_stats = engine.get_all_stats()

    for sig_id, stats in all_stats.items():
        print(f"{sig_id}:")
        print(f"  Total Samples: {stats['sample_count']}")
        print(f"  Missing Samples: {stats['missing_count']}")
        print(f"  Missing Ratio: {stats['missing_ratio']:.2%}")

        sqi_stats = stats['sqi_stats']
        print(f"  SQI Statistics:")
        print(f"    Mean: {sqi_stats['mean_sqi']:.1f}")
        print(f"    Min: {sqi_stats['min_sqi']:.1f}")
        print(f"    Max: {sqi_stats['max_sqi']:.1f}")
        print(f"    Current: {sqi_stats['current_sqi']:.1f}")
        print()

    # Get final processed signals
    final_results = engine.update(signals)

    print("=" * 60)
    print("Signal Quality Comparison")
    print("=" * 60)
    print()

    for sig_id in ["CLEAN_SIGNAL", "NOISY_SIGNAL", "DRIFT_SIGNAL"]:
        if sig_id in final_results:
            result = final_results[sig_id]
            print(f"{sig_id}: SQI = {result.sqi:.1f} ({result.quality_class})")
            if result.sqi_components:
                components = ", ".join(
                    f"{name}={score:.1f}"
                    for name, score in result.sqi_components.items()
                )
                print(f"  Components: {components}")

    print()
    print("Demo complete!")


if __name__ == "__main__":
    main()
