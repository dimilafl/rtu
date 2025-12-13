"""
Digital Signal Processing Filters

Implements low-pass, high-pass, and moving average filters
for real-time signal conditioning in discrete time.
"""

from typing import Optional
import numpy as np
from sqe.core.signal_buffer import SignalBuffer


class EWMAFilter:
    """
    Exponentially Weighted Moving Average (EWMA) Low-Pass Filter.

    Implements: y[n] = α * x[n] + (1 - α) * y[n-1]

    Where:
        - α (alpha) controls smoothing (0 < α ≤ 1)
        - Higher α = less smoothing, faster response
        - Lower α = more smoothing, slower response
    """

    def __init__(self, alpha: float = 0.3):
        """
        Initialize EWMA filter.

        Args:
            alpha: Smoothing factor (0 < α ≤ 1)
        """
        if not 0 < alpha <= 1:
            raise ValueError("Alpha must be in range (0, 1]")

        self.alpha = alpha
        self.last_output: Optional[float] = None

    def update(self, x: float) -> float:
        """
        Process new sample through filter.

        Args:
            x: Raw input sample

        Returns:
            Filtered output y[n]
        """
        if self.last_output is None:
            # Initialize with first sample
            self.last_output = x
            return x

        # y[n] = α * x[n] + (1 - α) * y[n-1]
        y = self.alpha * x + (1 - self.alpha) * self.last_output
        self.last_output = y
        return y

    def reset(self) -> None:
        """Reset filter state."""
        self.last_output = None


class HighPassFilter:
    """
    High-Pass Filter derived from EWMA low-pass.

    Implements: hp[n] = x[n] - lp[n]

    Where lp[n] is the low-pass filtered signal.
    Removes slow trends and DC offset.
    """

    def __init__(self, alpha: float = 0.3):
        """
        Initialize high-pass filter.

        Args:
            alpha: Smoothing factor for underlying low-pass filter
        """
        self.lowpass = EWMAFilter(alpha)

    def update(self, x: float) -> float:
        """
        Process new sample through high-pass filter.

        Args:
            x: Raw input sample

        Returns:
            High-pass filtered output
        """
        lp = self.lowpass.update(x)
        hp = x - lp
        return hp

    def reset(self) -> None:
        """Reset filter state."""
        self.lowpass.reset()


class MovingAverageFilter:
    """
    Simple Moving Average Filter.

    Computes average of last N samples.
    Provides uniform weighting within the window.
    """

    def __init__(self, window_size: int):
        """
        Initialize moving average filter.

        Args:
            window_size: Number of samples to average
        """
        if window_size <= 0:
            raise ValueError("Window size must be positive")

        self.window_size = window_size
        self.buffer = SignalBuffer(window_size)

    def update(self, x: float) -> float:
        """
        Process new sample through moving average.

        Args:
            x: Raw input sample

        Returns:
            Moving average output
        """
        self.buffer.push(x)
        samples = self.buffer.get_samples()

        if len(samples) == 0:
            return x

        return np.mean(samples)

    def reset(self) -> None:
        """Reset filter state."""
        self.buffer.clear()


class FilterBank:
    """
    Collection of filters that can be applied in parallel.

    Allows multiple filter types to process the same signal
    for comparative analysis or feature extraction.
    """

    def __init__(self):
        """Initialize empty filter bank."""
        self.filters = {}

    def add_filter(self, name: str, filter_obj) -> None:
        """
        Add a filter to the bank.

        Args:
            name: Identifier for the filter
            filter_obj: Filter instance (EWMA, HighPass, MovingAverage)
        """
        self.filters[name] = filter_obj

    def update(self, x: float) -> dict:
        """
        Process sample through all filters.

        Args:
            x: Raw input sample

        Returns:
            Dictionary of {filter_name: output_value}
        """
        results = {}
        for name, filt in self.filters.items():
            results[name] = filt.update(x)
        return results

    def reset(self) -> None:
        """Reset all filters."""
        for filt in self.filters.values():
            filt.reset()
