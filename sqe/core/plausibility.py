"""Plausibility checker for range and rate-of-change limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PlausibilityResult:
    """Result from plausibility checker."""

    is_violation: bool
    reasons: List[str]
    rate_of_change: Optional[float]


class PlausibilityChecker:
    """Checks values against configured plausibility constraints."""

    def __init__(
        self,
        min_value: Optional[float],
        max_value: Optional[float],
        max_rate: Optional[float],
        persistence_scans: int,
        recovery_scans: int,
    ) -> None:
        if persistence_scans <= 0:
            raise ValueError("persistence_scans must be > 0")
        if recovery_scans <= 0:
            raise ValueError("recovery_scans must be > 0")
        self.min_value = min_value
        self.max_value = max_value
        self.max_rate = max_rate
        self.persistence_scans = persistence_scans
        self.recovery_scans = recovery_scans
        self._last_value: Optional[float] = None
        self._last_timestamp: Optional[float] = None
        self._active = False
        self._violation_count = 0
        self._recovery_count = 0

    def update(self, value: float, timestamp: float) -> PlausibilityResult:
        """Update checker with a new sample."""
        reasons: List[str] = []
        rate_of_change: Optional[float] = None

        if self.min_value is not None and value < self.min_value:
            reasons.append("below_min")
        if self.max_value is not None and value > self.max_value:
            reasons.append("above_max")

        if self.max_rate is not None and self._last_value is not None:
            dt = timestamp - (self._last_timestamp or timestamp)
            if dt <= 0:
                dt = 1.0
            rate_of_change = abs(value - self._last_value) / dt
            if rate_of_change > self.max_rate:
                reasons.append("rate_exceeded")

        self._last_value = value
        self._last_timestamp = timestamp

        if reasons:
            self._violation_count += 1
            self._recovery_count = 0
            if self._violation_count >= self.persistence_scans:
                self._active = True
        else:
            self._violation_count = 0
            if self._active:
                self._recovery_count += 1
                if self._recovery_count >= self.recovery_scans:
                    self._active = False
                    self._recovery_count = 0

        is_violation = self._active
        return PlausibilityResult(
            is_violation=is_violation,
            reasons=reasons,
            rate_of_change=rate_of_change,
        )

    def reset(self) -> None:
        """Reset checker state."""
        self._last_value = None
        self._last_timestamp = None
        self._active = False
        self._violation_count = 0
        self._recovery_count = 0
