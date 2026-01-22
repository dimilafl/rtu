"""
Signal Buffer - Circular buffer for maintaining signal history.

Provides efficient storage and retrieval of signal samples
for sliding-window operations.
"""

from collections import deque
from typing import Optional
import numpy as np


class SignalBuffer:
    """
    Circular buffer for storing signal history.

    Used for sliding-window operations like moving average,
    variance calculation, and frequency detection.
    """

    def __init__(self, capacity: int):
        """
        Initialize signal buffer.

        Args:
            capacity: Maximum number of samples to store
        """
        if capacity <= 0:
            raise ValueError("Buffer capacity must be positive")

        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)
        self.missing_flags = deque(maxlen=capacity)
        self.missing_count = 0  # Track missing samples for SQI

    def push(self, value: Optional[float]) -> None:
        """
        Add a new sample to the buffer.

        Args:
            value: Sample value, or None if missing
        """
        if len(self.buffer) == self.capacity:
            evicted_missing = self.missing_flags.popleft()
            self.buffer.popleft()
            if evicted_missing:
                self.missing_count -= 1

        if value is None:
            self.buffer.append(None)
            self.missing_flags.append(True)
            self.missing_count += 1
            return

        self.buffer.append(value)
        self.missing_flags.append(False)

    def get_samples(self, n: Optional[int] = None) -> np.ndarray:
        """
        Get last n samples as numpy array.

        Args:
            n: Number of samples to retrieve (None = all)

        Returns:
            Numpy array of samples
        """
        if n is None:
            return np.array([sample for sample in self.buffer if sample is not None])

        if n <= 0:
            return np.array([])

        # Get last n samples
        samples = list(self.buffer)[-n:]
        return np.array([sample for sample in samples if sample is not None])

    def get_latest(self) -> Optional[float]:
        """
        Get the most recent sample.

        Returns:
            Latest sample value or None if buffer is empty
        """
        if len(self.buffer) == 0:
            return None
        return self.buffer[-1]

    def get_previous(self) -> Optional[float]:
        """
        Get the second most recent sample.

        Returns:
            Previous sample value or None if insufficient data
        """
        if len(self.buffer) < 2:
            return None
        return self.buffer[-2]

    def is_full(self) -> bool:
        """Check if buffer is at capacity."""
        return len(self.buffer) == self.capacity

    def size(self) -> int:
        """Get current number of samples in buffer."""
        return len(self.buffer)

    def clear(self) -> None:
        """Clear all samples from buffer."""
        self.buffer.clear()
        self.missing_flags.clear()
        self.missing_count = 0

    def get_missing_ratio(self) -> float:
        """
        Calculate ratio of missing samples.

        Returns:
            Ratio between 0 and 1
        """
        total = len(self.buffer)
        if total == 0:
            return 0.0
        return self.missing_count / total

    def reset_missing_count(self) -> None:
        """Recalculate the missing sample counter for the current window."""
        self.missing_count = sum(self.missing_flags)
