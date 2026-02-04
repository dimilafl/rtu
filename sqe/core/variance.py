"""
Sliding-Window Variance Calculator

Implements numerically stable incremental variance calculation
for real-time signal quality assessment using O(1) rolling sums.
"""

from collections import deque
from math import sqrt
from typing import Deque, Optional


class VarianceCalculator:
    """
    Calculates sliding-window variance using O(1) rolling sums.

    Uses incremental sum and sum-of-squares for constant-time updates:
        mean = sum / n
        variance = (sumsq - sum²/n) / (n-1)  [sample variance]
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
        self._window: Deque[float] = deque(maxlen=window_size)
        self._sum: float = 0.0
        self._sumsq: float = 0.0
        # Cache the last computed stats for get_stats()
        self._cached_stats: Optional[dict] = None

    def update(self, x: float) -> dict:
        """
        Process new sample and calculate variance.

        Args:
            x: New signal sample

        Returns:
            Dictionary with mean, variance, std_dev, and noise_level
        """
        # Evict oldest value if window is full
        if len(self._window) == self.window_size:
            y = self._window[0]  # Will be evicted by append
            self._sum -= y
            self._sumsq -= y * y

        # Add new value
        self._window.append(x)
        self._sum += x
        self._sumsq += x * x

        n = len(self._window)

        if n < 2:
            stats = {
                "mean": x,
                "variance": 0.0,
                "std_dev": 0.0,
                "noise_level": 0.0,
                "sample_count": n
            }
            self._cached_stats = stats
            return stats

        # Compute mean
        mean = self._sum / n

        # Compute sample variance (ddof=1)
        # ss = sumsq - sum²/n
        ss = self._sumsq - (self._sum * self._sum) / n
        # Clamp to avoid negative due to floating point errors
        if ss < 0.0:
            ss = 0.0
        variance = ss / (n - 1)
        if variance < 0.0:
            variance = 0.0

        std_dev = sqrt(variance)

        # Noise level as coefficient of variation
        if abs(mean) > 1e-9:
            noise_level = std_dev / abs(mean)
        else:
            noise_level = std_dev

        stats = {
            "mean": mean,
            "variance": variance,
            "std_dev": std_dev,
            "noise_level": noise_level,
            "sample_count": n
        }
        self._cached_stats = stats
        return stats

    def get_stats(self) -> dict:
        """
        Calculate statistics without updating the buffer.

        Returns:
            Dictionary with mean, variance, std_dev, and noise_level
        """
        # If we have cached stats, return them
        if self._cached_stats is not None:
            return self._cached_stats

        n = len(self._window)

        if n == 0:
            return {
                "mean": 0.0,
                "variance": 0.0,
                "std_dev": 0.0,
                "noise_level": 0.0,
                "sample_count": 0
            }

        if n < 2:
            mean = self._sum / n if n > 0 else 0.0
            return {
                "mean": mean,
                "variance": 0.0,
                "std_dev": 0.0,
                "noise_level": 0.0,
                "sample_count": n
            }

        mean = self._sum / n
        ss = self._sumsq - (self._sum * self._sum) / n
        if ss < 0.0:
            ss = 0.0
        variance = ss / (n - 1)
        if variance < 0.0:
            variance = 0.0
        std_dev = sqrt(variance)

        if abs(mean) > 1e-9:
            noise_level = std_dev / abs(mean)
        else:
            noise_level = std_dev

        return {
            "mean": mean,
            "variance": variance,
            "std_dev": std_dev,
            "noise_level": noise_level,
            "sample_count": n
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
        self._window.clear()
        self._sum = 0.0
        self._sumsq = 0.0
        self._cached_stats = None


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
        std_dev = sqrt(variance)

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
    Can use an external VarianceCalculator for shared stats.
    """

    def __init__(
        self,
        window_size: int = 20,
        k_sigma: float = 3.0,
        debounce_samples: int = 1,
        variance_calc: Optional[VarianceCalculator] = None,
    ):
        """
        Initialize spike detector.

        Args:
            window_size: Window for baseline statistics
            k_sigma: Number of standard deviations for threshold
            debounce_samples: Consecutive samples to confirm spike
            variance_calc: Optional external variance calculator to share
        """
        if variance_calc is not None:
            self.variance_calc = variance_calc
            self._external_variance = True
        else:
            self.variance_calc = VarianceCalculator(window_size)
            self._external_variance = False

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
            signal_id: Optional signal identifier for caching
            baseline_stats_cache: Optional cache for baseline stats

        Returns:
            Dictionary with spike detection results
        """
        self.total_samples += 1

        # Get baseline statistics BEFORE updating with current sample
        baseline_stats = None
        if baseline_stats_cache is not None and signal_id is not None:
            baseline_stats = baseline_stats_cache.get(signal_id)

        if baseline_stats is None:
            baseline_stats = self.variance_calc.get_stats()
            if baseline_stats_cache is not None and signal_id is not None:
                baseline_stats_cache[signal_id] = baseline_stats

        # Get threshold from baseline stats
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

        # Only update variance if we own the calculator (not external)
        if not self._external_variance:
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
