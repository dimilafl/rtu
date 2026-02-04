"""
Signal Buffer - Circular buffer for maintaining signal history.

Provides efficient storage and retrieval of signal samples
for sliding-window operations. Uses fixed-size numpy arrays
to avoid per-sample allocations in the hot path.
"""

from typing import Optional
import numpy as np


class SignalBuffer:
    """
    Circular buffer for storing signal history.

    Uses fixed-size numpy arrays with ring buffer semantics
    for O(1) push and allocation-free get_samples.
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
        # Preallocate fixed-size arrays
        self._values: np.ndarray = np.zeros(capacity, dtype=np.float64)
        self._missing: np.ndarray = np.zeros(capacity, dtype=np.bool_)
        self._scratch: np.ndarray = np.zeros(capacity, dtype=np.float64)
        # Ring buffer state
        self._head: int = 0  # Next write index
        self._count: int = 0  # Number of valid entries (0..capacity)
        self.missing_count: int = 0

    def push(self, value: Optional[float]) -> None:
        """
        Add a new sample to the buffer.

        Args:
            value: Sample value, or None if missing
        """
        # If overwriting, decrement missing_count if outgoing slot was missing
        if self._count == self.capacity:
            if self._missing[self._head]:
                self.missing_count -= 1

        # Write new value
        is_missing = value is None
        if is_missing:
            self._values[self._head] = np.nan
            self._missing[self._head] = True
            self.missing_count += 1
        else:
            self._values[self._head] = value
            self._missing[self._head] = False

        # Advance head
        self._head = (self._head + 1) % self.capacity
        if self._count < self.capacity:
            self._count += 1

    def get_samples(self, n: Optional[int] = None) -> np.ndarray:
        """
        Get last n samples as numpy array.

        Returns samples in chronological order (oldest -> newest).
        Missing (None) values are excluded from the returned array.
        Returns views or scratch buffer to avoid allocations.

        Args:
            n: Number of samples to retrieve (None = all)

        Returns:
            Numpy array of samples (view or scratch, not new allocation)
        """
        if n is not None and n <= 0:
            return self._scratch[:0]

        if self._count == 0:
            return self._scratch[:0]

        # Determine how many samples to consider
        count = self._count
        if n is not None and n < count:
            count = n

        # Calculate start index (oldest sample in the requested range)
        # _head points to next write position
        # For full buffer: oldest is at _head, newest is at _head-1
        # For partial buffer: oldest is at 0, newest is at _head-1
        if self._count == self.capacity:
            # Full buffer: data wraps around
            oldest_idx = self._head
        else:
            # Partial buffer: data starts at 0
            oldest_idx = 0

        # If we only want last n samples, adjust start
        if n is not None and n < self._count:
            # Skip (self._count - n) oldest samples
            skip = self._count - n
            oldest_idx = (oldest_idx + skip) % self.capacity

        # Check if the range is contiguous (no wrap-around)
        end_idx = (oldest_idx + count - 1) % self.capacity
        is_contiguous = oldest_idx <= end_idx or count == 0

        # Check if there are any missing values in the range
        has_missing = False
        if is_contiguous:
            # Contiguous range: check _missing[oldest_idx:oldest_idx+count]
            if np.any(self._missing[oldest_idx:oldest_idx + count]):
                has_missing = True
        else:
            # Wrapped range: check both segments
            if np.any(self._missing[oldest_idx:]) or np.any(self._missing[:end_idx + 1]):
                has_missing = True

        # Fast path: contiguous with no missing values - return view
        if is_contiguous and not has_missing:
            return self._values[oldest_idx:oldest_idx + count]

        # Slow path: copy non-missing values into scratch buffer
        k = 0
        for i in range(count):
            idx = (oldest_idx + i) % self.capacity
            if not self._missing[idx]:
                self._scratch[k] = self._values[idx]
                k += 1

        return self._scratch[:k]

    def get_latest(self) -> Optional[float]:
        """
        Get the most recent sample.

        Returns:
            Latest sample value or None if buffer is empty or latest is missing
        """
        if self._count == 0:
            return None
        # Latest is at _head - 1
        idx = (self._head - 1) % self.capacity
        if self._missing[idx]:
            return None
        return float(self._values[idx])

    def get_previous(self) -> Optional[float]:
        """
        Get the second most recent sample.

        Returns:
            Previous sample value or None if insufficient data or missing
        """
        if self._count < 2:
            return None
        idx = (self._head - 2) % self.capacity
        if self._missing[idx]:
            return None
        return float(self._values[idx])

    def is_full(self) -> bool:
        """Check if buffer is at capacity."""
        return self._count == self.capacity

    def size(self) -> int:
        """Get current number of samples in buffer."""
        return self._count

    def clear(self) -> None:
        """Clear all samples from buffer."""
        self._head = 0
        self._count = 0
        self.missing_count = 0
        # Reset arrays to clean state
        self._values.fill(0.0)
        self._missing.fill(False)

    def get_missing_ratio(self) -> float:
        """
        Calculate ratio of missing samples.

        Returns:
            Ratio between 0 and 1
        """
        if self._count == 0:
            return 0.0
        return self.missing_count / self._count

    def reset_missing_count(self) -> None:
        """Recalculate the missing sample counter for the current window."""
        if self._count == 0:
            self.missing_count = 0
            return

        # Count missing values in the active window
        if self._count == self.capacity:
            # Full buffer: all entries are valid
            self.missing_count = int(np.sum(self._missing))
        else:
            # Partial buffer: only count from 0 to _count
            # Note: in partial buffer, data is always at indices 0.._head-1
            # which equals 0.._count-1
            self.missing_count = int(np.sum(self._missing[:self._count]))
