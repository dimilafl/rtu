"""Stale detector for flatline values or non-advancing timestamps."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional


@dataclass
class StaleResult:
    """Result from stale detector."""

    is_stale: bool
    reason: Optional[str]
    flatline: bool
    timestamp_stale: bool


class StaleDetector:
    """Detects frozen values or non-advancing timestamps with hysteresis."""

    def __init__(self, window_size: int, recovery_window: int) -> None:
        if window_size <= 1:
            raise ValueError("window_size must be > 1")
        if recovery_window <= 0:
            raise ValueError("recovery_window must be > 0")
        self.window_size = window_size
        self.recovery_window = recovery_window
        self._values: Deque[float] = deque(maxlen=window_size)
        self._last_timestamp: Optional[float] = None
        self._stale_active = False
        self._stale_reason: Optional[str] = None
        self._recovery_count = 0

    def update(self, value: float, timestamp: float) -> StaleResult:
        """Update detector with a new sample."""
        self._values.append(value)

        timestamp_stale = (
            self._last_timestamp is not None and timestamp <= self._last_timestamp
        )
        self._last_timestamp = timestamp

        flatline = (
            len(self._values) == self.window_size
            and len(set(self._values)) == 1
        )

        raw_stale = timestamp_stale or flatline
        if raw_stale:
            self._stale_active = True
            self._recovery_count = 0
            if timestamp_stale:
                self._stale_reason = "timestamp"
            elif flatline:
                self._stale_reason = "flatline"
        elif self._stale_active:
            self._recovery_count += 1
            if self._recovery_count >= self.recovery_window:
                self._stale_active = False
                self._stale_reason = None
                self._recovery_count = 0

        return StaleResult(
            is_stale=self._stale_active or raw_stale,
            reason=self._stale_reason,
            flatline=flatline,
            timestamp_stale=timestamp_stale,
        )

    def reset(self) -> None:
        """Reset detector state."""
        self._values.clear()
        self._last_timestamp = None
        self._stale_active = False
        self._stale_reason = None
        self._recovery_count = 0
