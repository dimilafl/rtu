"""
Sliding-Window Variance Calculator

Implements numerically stable incremental variance calculation
for real-time signal quality assessment.
"""

from typing import Optional
import numpy as np
from sqe.core.signal_buffer import SignalBuffer


class VarianceCalculator:
    """
    Calculates sliding-window variance using Welford's online algorithm.

    Numerically stable incremental calculation:
        mean = Σ x / N
        variance = Σ (x - mean)² / N

    Uses Welford's method to avoid catastrophic cancellation.
    """

    def __init__(self, window_size: int):
        """
        Initialize variance calculator.

        Args:
            window_size: Number of samples for sliding window
        """
        if window_size <= 1:
            raise ValueError("Window size must be > 1 for variance")

        self.window_size = window_size
        self.buffer = SignalBuffer(window_size)

    def update(self, x: float) -> dict:
        """
        Process new sample and calculate variance.

        Args:
            x: New signal sample

        Returns:
            Dictionary with mean, variance, std_dev, and noise_level
        """
        self.buffer.push(x)
        samples = self.buffer.get_samples()

        if len(samples) < 2:
            # Need at least 2 samples for variance
            return {
                "mean": x,
                "variance": 0.0,
                "std_dev": 0.0,
                "noise_level": 0.0,
                "sample_count": len(samples)
            }

        # Calculate statistics using numpy
        mean = np.mean(samples)
        variance = np.var(samples, ddof=1)  # Sample variance
        std_dev = np.sqrt(variance)

        # Noise level as coefficient of variation
        cv = std_dev / abs(mean) if abs(mean) > 1e-9 else std_dev

        return {
            "mean": float(mean),
            "variance": float(variance),
            "std_dev": float(std_dev),
            "noise_level": float(cv),
            "sample_count": len(samples)
        }

    def get_stats(self) -> dict:
        """
        Calculate statistics without updating the buffer.

        Returns:
            Dictionary with mean, variance, std_dev, and noise_level
        """
        samples = self.buffer.get_samples()

        if len(samples) < 2:
            mean = float(np.mean(samples)) if len(samples) > 0 else 0.0
            return {
                "mean": mean,
                "variance": 0.0,
                "std_dev": 0.0,
                "noise_level": 0.0,
                "sample_count": len(samples)
            }

        mean = np.mean(samples)
        variance = np.var(samples, ddof=1)  # Sample variance
        std_dev = np.sqrt(variance)
        cv = std_dev / abs(mean) if abs(mean) > 1e-9 else std_dev

        return {
            "mean": float(mean),
            "variance": float(variance),
            "std_dev": float(std_dev),
            "noise_level": float(cv),
            "sample_count": len(samples)
        }

    def get_spike_threshold(
        self,
        k: float = 3.0,
        stats: Optional[dict] = None,
    ) -> Optional[float]:
        """
        Calculate spike detection threshold.

        Threshold = mean + k * σ

        Args:
            k: Number of standard deviations for threshold

        Returns:
            Threshold value or None if insufficient data
        """
        if stats is None:
            stats = self.get_stats()

        if stats["sample_count"] < 2:
            return None

        return stats["mean"] + k * stats["std_dev"]

    def is_spike(
        self,
        x: float,
        k: float = 3.0,
        stats: Optional[dict] = None,
    ) -> bool:
        """
        Check if value is a spike.

        Args:
            x: Value to check
            k: Number of standard deviations for threshold

        Returns:
            True if value exceeds threshold
        """
        if stats is None:
            stats = self.get_stats()

        if stats["sample_count"] < 2:
            return False

        if stats["std_dev"] <= 0:
            return abs(x - stats["mean"]) > 0

        return abs(x - stats["mean"]) > k * stats["std_dev"]

    def reset(self) -> None:
        """Reset calculator state."""
        self.buffer.clear()


class WelfordVariance:
    """
    Welford's online variance algorithm for streaming data.

    More memory-efficient than buffer-based approach,
    but calculates cumulative rather than sliding window.
    """

    def __init__(self):
        """Initialize Welford variance calculator."""
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0  # Sum of squared differences from mean

    def update(self, x: float) -> dict:
        """
        Process new sample using Welford's algorithm.

        Args:
            x: New sample value

        Returns:
            Dictionary with mean and variance
        """
        self.count += 1
        delta = x - self.mean
        self.mean += delta / self.count
        delta2 = x - self.mean
        self.m2 += delta * delta2

        if self.count < 2:
            return {
                "mean": self.mean,
                "variance": 0.0,
                "std_dev": 0.0,
                "count": self.count
            }

        variance = self.m2 / (self.count - 1)
        std_dev = np.sqrt(variance)

        return {
            "mean": self.mean,
            "variance": variance,
            "std_dev": std_dev,
            "count": self.count
        }

    def reset(self) -> None:
        """Reset calculator state."""
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0


class SpikeDetector:
    """
    Dedicated spike detection using statistical thresholds.

    Combines variance analysis with adaptive thresholding.
    """

    def __init__(
        self,
        window_size: int = 20,
        k_sigma: float = 3.0,
        debounce_samples: int = 1
    ):
        """
        Initialize spike detector.

        Args:
            window_size: Window for baseline statistics
            k_sigma: Number of standard deviations for threshold
            debounce_samples: Consecutive samples to confirm spike
        """
        self.variance_calc = VarianceCalculator(window_size)
        self.k_sigma = k_sigma
        self.debounce_samples = debounce_samples
        self._consecutive_spikes = 0
        self._was_spike = False
        self.spike_count = 0
        self.total_samples = 0

    def update(
        self,
        x: float,
        *,
        signal_id: Optional[str] = None,
        baseline_stats_cache: Optional[dict] = None,
    ) -> dict:
        """
        Check for spike in new sample.

        Args:
            x: New signal value

        Returns:
            Dictionary with spike detection results
        """
        self.total_samples += 1

        # Baseline statistics before updating with current sample
        baseline_stats = None
        if baseline_stats_cache is not None and signal_id is not None:
            baseline_stats = baseline_stats_cache.get(signal_id)

        if baseline_stats is None:
            baseline_stats = self.variance_calc.get_stats()
            if baseline_stats_cache is not None and signal_id is not None:
                baseline_stats_cache[signal_id] = baseline_stats

        # Cache invalidation assumption: the cached baseline stats are only valid
        # until variance_calc.update is called for this signal (i.e., within one scan).
        baseline_threshold = self.variance_calc.get_spike_threshold(
            self.k_sigma,
            stats=baseline_stats,
        )

        # Check for spike
        is_spike_candidate = self.variance_calc.is_spike(
            x,
            self.k_sigma,
            stats=baseline_stats,
        )
        if is_spike_candidate:
            self._consecutive_spikes += 1
        else:
            self._consecutive_spikes = 0

        is_spike = self._consecutive_spikes >= self.debounce_samples

        if is_spike and not self._was_spike:
            self.spike_count += 1

        # Update variance statistics after spike evaluation
        self.variance_calc.update(x)
        self._was_spike = is_spike

        # Calculate spike frequency
        spike_frequency = self.spike_count / self.total_samples if self.total_samples > 0 else 0

        return {
            "is_spike": is_spike,
            "spike_count": self.spike_count,
            "spike_frequency": spike_frequency,
            "threshold": baseline_threshold,
            "deviation_from_mean": (
                abs(x - baseline_stats["mean"]) / baseline_stats["std_dev"]
                if baseline_stats["std_dev"] > 0
                else 0
            )
        }

    def reset(self) -> None:
        """Reset detector state."""
        self.variance_calc.reset()
        self._consecutive_spikes = 0
        self._was_spike = False
        self.spike_count = 0
        self.total_samples = 0
