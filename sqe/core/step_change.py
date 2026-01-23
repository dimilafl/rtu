"""Step-change detector for persistent signal offsets."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import numpy as np


@dataclass
class StepChangeResult:
    """Result from step-change detector."""

    is_step: bool
    baseline: Optional[float]
    step_level: Optional[float]
    offset: Optional[float]


class StepChangeDetector:
    """Detects persistent step changes with confirmation and recovery."""

    def __init__(
        self,
        baseline_window: int,
        step_threshold: float,
        persistence_scans: int,
        recovery_scans: int,
    ) -> None:
        if baseline_window <= 1:
            raise ValueError("baseline_window must be > 1")
        if step_threshold <= 0:
            raise ValueError("step_threshold must be > 0")
        if persistence_scans <= 0:
            raise ValueError("persistence_scans must be > 0")
        if recovery_scans <= 0:
            raise ValueError("recovery_scans must be > 0")
        self.baseline_window = baseline_window
        self.step_threshold = step_threshold
        self.persistence_scans = persistence_scans
        self.recovery_scans = recovery_scans
        self._window: Deque[float] = deque(maxlen=baseline_window)
        self._candidate_level: Optional[float] = None
        self._baseline_snapshot: Optional[float] = None
        self._confirm_count = 0
        self._recovery_count = 0
        self._active = False

    def update(self, value: float) -> StepChangeResult:
        """Update detector with a new sample."""
        self._window.append(value)

        baseline = None
        if len(self._window) == self.baseline_window:
            baseline = float(np.mean(self._window))

        if not self._active and baseline is not None:
            if self._candidate_level is None:
                if abs(value - baseline) >= self.step_threshold:
                    self._candidate_level = value
                    self._baseline_snapshot = baseline
                    self._confirm_count = 1
            else:
                if abs(value - self._candidate_level) <= self.step_threshold:
                    self._confirm_count += 1
                else:
                    self._candidate_level = None
                    self._baseline_snapshot = None
                    self._confirm_count = 0

                if self._confirm_count >= self.persistence_scans:
                    self._active = True
                    self._recovery_count = 0

        if self._active:
            if (
                self._candidate_level is not None
                and abs(value - self._candidate_level) <= self.step_threshold
            ):
                self._recovery_count += 1
            else:
                self._recovery_count = 0

            if self._recovery_count >= self.recovery_scans:
                self._active = False
                self._candidate_level = None
                self._baseline_snapshot = None
                self._confirm_count = 0
                self._recovery_count = 0

        offset = None
        if self._baseline_snapshot is not None and self._candidate_level is not None:
            offset = self._candidate_level - self._baseline_snapshot

        return StepChangeResult(
            is_step=self._active,
            baseline=self._baseline_snapshot,
            step_level=self._candidate_level,
            offset=offset,
        )

    def reset(self) -> None:
        """Reset detector state."""
        self._window.clear()
        self._candidate_level = None
        self._baseline_snapshot = None
        self._confirm_count = 0
        self._recovery_count = 0
        self._active = False
