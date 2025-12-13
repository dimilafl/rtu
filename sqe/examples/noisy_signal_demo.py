"""
Demo: Noisy Signal Analysis

Demonstrates filter effectiveness and signal quality degradation
with increasing noise levels.
"""

import numpy as np
from sqe.core.filters import EWMAFilter, MovingAverageFilter
from sqe.core.variance import VarianceCalculator, SpikeDetector
from sqe.core.sqi import SignalQualityIndex


def generate_signal_with_noise(samples: int, noise_std: float) -> np.ndarray:
    """
    Generate sinusoidal signal with additive Gaussian noise.

    Args:
        samples: Number of samples
        noise_std: Standard deviation of noise

    Returns:
        Noisy signal array
    """
    t = np.linspace(0, 10, samples)
    clean = 10.0 * np.sin(2 * np.pi * 0.5 * t)
    noise = np.random.normal(0, noise_std, samples)
    return clean + noise


def demo_filter_comparison():
    """Compare filter performance on noisy signal."""
    print("=" * 60)
    print("Filter Performance Comparison")
    print("=" * 60)
    print()

    # Generate noisy signal
    np.random.seed(42)
    samples = 100
    noise_std = 2.0
    signal = generate_signal_with_noise(samples, noise_std)

    # Initialize filters
    ewma_slow = EWMAFilter(alpha=0.1)  # Aggressive smoothing
    ewma_fast = EWMAFilter(alpha=0.5)  # Light smoothing
    ma_filter = MovingAverageFilter(window_size=10)

    # Process signal
    ewma_slow_out = []
    ewma_fast_out = []
    ma_out = []

    for s in signal:
        ewma_slow_out.append(ewma_slow.update(s))
        ewma_fast_out.append(ewma_fast.update(s))
        ma_out.append(ma_filter.update(s))

    # Calculate output variance (measure of smoothing)
    raw_var = np.var(signal[50:])  # Skip initial transient
    ewma_slow_var = np.var(ewma_slow_out[50:])
    ewma_fast_var = np.var(ewma_fast_out[50:])
    ma_var = np.var(ma_out[50:])

    print(f"Input Signal Variance: {raw_var:.2f}")
    print()
    print("Filter Output Variance:")
    print(f"  EWMA (α=0.1): {ewma_slow_var:.2f} ({100*ewma_slow_var/raw_var:.1f}% of input)")
    print(f"  EWMA (α=0.5): {ewma_fast_var:.2f} ({100*ewma_fast_var/raw_var:.1f}% of input)")
    print(f"  MA (N=10):    {ma_var:.2f} ({100*ma_var/raw_var:.1f}% of input)")
    print()


def demo_spike_detection():
    """Demonstrate spike detection on signal with outliers."""
    print("=" * 60)
    print("Spike Detection Demo")
    print("=" * 60)
    print()

    # Generate signal with spikes
    np.random.seed(42)
    samples = 100
    signal = 10.0 * np.sin(np.linspace(0, 10, samples))

    # Add random spikes
    spike_indices = [20, 45, 73, 91]
    for idx in spike_indices:
        signal[idx] += np.random.choice([-1, 1]) * 15.0  # Large deviation

    # Initialize spike detector
    detector = SpikeDetector(window_size=20, k_sigma=3.0)

    # Process signal
    detected_spikes = []
    for i, s in enumerate(signal):
        result = detector.update(s)
        if result["is_spike"]:
            detected_spikes.append(i)

    print(f"Injected Spikes at indices: {spike_indices}")
    print(f"Detected Spikes at indices: {detected_spikes}")
    print(f"Total Spikes Detected: {len(detected_spikes)}")
    print(f"Spike Frequency: {detector.spike_count / detector.total_samples:.2%}")
    print()


def demo_noise_impact_on_sqi():
    """Demonstrate SQI degradation with increasing noise."""
    print("=" * 60)
    print("Noise Impact on Signal Quality Index")
    print("=" * 60)
    print()

    # Test multiple noise levels
    noise_levels = [0.1, 0.5, 1.0, 2.0, 5.0]

    print(f"{'Noise Level':<15} {'SQI Score':<12} {'Quality Class':<15}")
    print("-" * 42)

    for noise_std in noise_levels:
        # Generate signal
        np.random.seed(42)
        signal = generate_signal_with_noise(100, noise_std)

        # Calculate variance
        var_calc = VarianceCalculator(window_size=50)
        for s in signal[:50]:
            var_calc.update(s)

        stats = var_calc.update(signal[50])

        # Calculate SQI
        sqi_calc = SignalQualityIndex()
        result = sqi_calc.calculate(
            noise_level=stats["noise_level"],
            drift_rate=0.0,
            spike_frequency=0.0,
            oscillation_energy=0.0,
            missing_ratio=0.0
        )

        print(f"{noise_std:<15.1f} {result['sqi']:<12.1f} {result['quality_class']:<15}")

    print()


def demo_variance_calculation():
    """Demonstrate sliding-window variance calculation."""
    print("=" * 60)
    print("Sliding-Window Variance Calculation")
    print("=" * 60)
    print()

    # Generate signal with changing noise characteristics
    np.random.seed(42)

    # Part 1: Low noise
    low_noise = 10.0 + np.random.normal(0, 0.5, 50)

    # Part 2: High noise
    high_noise = 10.0 + np.random.normal(0, 2.0, 50)

    signal = np.concatenate([low_noise, high_noise])

    # Calculate variance
    var_calc = VarianceCalculator(window_size=20)

    variances = []
    for s in signal:
        result = var_calc.update(s)
        variances.append(result["variance"])

    # Print variance at key points
    print("Variance at different signal segments:")
    print(f"  Sample 30 (low noise): {variances[29]:.3f}")
    print(f"  Sample 60 (transition): {variances[59]:.3f}")
    print(f"  Sample 90 (high noise): {variances[89]:.3f}")
    print()

    variance_increase = variances[89] / variances[29]
    print(f"Variance increased by {variance_increase:.1f}x")
    print()


def main():
    """Run all noisy signal demonstrations."""
    print()
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  Noisy Signal Analysis - SQE Demonstration".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    demo_filter_comparison()
    print()

    demo_spike_detection()
    print()

    demo_noise_impact_on_sqi()
    print()

    demo_variance_calculation()
    print()

    print("=" * 60)
    print("All demonstrations complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
