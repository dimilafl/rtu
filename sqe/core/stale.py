"""Stale detector for flatline values or non-advancing timestamps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class StaleResult:
    """Result from stale detector."""

    is_stale: bool
    reason: Optional[str]
    flatline: bool
    timestamp_stale: bool


class StaleDetector:
    """Detects frozen values or non-advancing timestamps with hysteresis.

    Uses O(1) run-length tracking for flatline detection instead of O(n) set().
    """

    def __init__(self, window_size: int, recovery_window: int) -> None:
        if window_size <= 1:
            raise ValueError("window_size must be > 1")
        if recovery_window <= 0:
            raise ValueError("recovery_window must be > 0")
        self.window_size = window_size
        self.recovery_window = recovery_window
        # Run-length tracking for O(1) flatline detection
        self._last_value: Optional[float] = None
        self._flatline_run: int = 0
        self._last_timestamp: Optional[float] = None
        self._stale_active = False
        self._stale_reason: Optional[str] = None
        self._recovery_count = 0

    def update(self, value: float, timestamp: float) -> StaleResult:
        """Update detector with a new sample."""
        # Update run-length for flatline detection
        if self._last_value is None:
            self._last_value = value
            self._flatline_run = 1
        elif value == self._last_value:
            self._flatline_run += 1
        else:
            self._last_value = value
            self._flatline_run = 1

        timestamp_stale = (
            self._last_timestamp is not None and timestamp <= self._last_timestamp
        )
        self._last_timestamp = timestamp

        # Flatline detected when run length reaches window_size
        flatline = self._flatline_run >= self.window_size

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
        self._last_value = None
        self._flatline_run = 0
        self._last_timestamp = None
        self._stale_active = False
        self._stale_reason = None
        self._recovery_count = 0
