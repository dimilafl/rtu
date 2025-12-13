"""
Drift Detection - Discrete derivative analysis for sensor degradation.

Detects:
- Sustained small drift (sensor degradation)
- Large transient drift (anomalies)
- Monotonic drift (slow leak precursors)
"""

from typing import Optional, Dict, List
from enum import Enum
from dataclasses import dataclass
import numpy as np
from sqe.core.signal_buffer import SignalBuffer


class DriftType(Enum):
    """Types of drift patterns."""
    NONE = "none"
    SUSTAINED_SMALL = "sustained_small"  # Possible sensor degradation
    TRANSIENT_LARGE = "transient_large"  # Anomaly/spike
    MONOTONIC = "monotonic"              # Slow leak precursor


@dataclass
class DriftEvent:
    """Structured drift detection result."""
    drift_rate: float           # Current dX = x[n] - x[n-1]
    drift_type: DriftType       # Classification of drift
    severity: float             # 0-1 severity score
    monotonic_samples: int      # Consecutive samples with same drift direction
    sustained: bool             # Is drift sustained over threshold period


class DriftDetector:
    """
    Detects and classifies signal drift using discrete derivatives.

    Implements:
        dX = x[n] - x[n-1]

    With configurable thresholds for different drift types.
    """

    def __init__(
        self,
        small_drift_threshold: float = 0.5,
        large_drift_threshold: float = 5.0,
        sustained_window: int = 10,
        monotonic_window: int = 5
    ):
        """
        Initialize drift detector.

        Args:
            small_drift_threshold: Threshold for sustained small drift
            large_drift_threshold: Threshold for transient large drift
            sustained_window: Samples to consider drift "sustained"
            monotonic_window: Samples to detect monotonic behavior
        """
        self.small_threshold = small_drift_threshold
        self.large_threshold = large_drift_threshold
        self.sustained_window = sustained_window
        self.monotonic_window = monotonic_window

        self.last_value: Optional[float] = None
        self.drift_history = SignalBuffer(sustained_window)
        self.monotonic_count = 0
        self.last_drift_sign = 0

    def update(self, x: float) -> DriftEvent:
        """
        Process new sample and detect drift.

        Args:
            x: Current signal value

        Returns:
            DriftEvent with classification and metrics
        """
        if self.last_value is None:
            # First sample - no drift
            self.last_value = x
            return DriftEvent(
                drift_rate=0.0,
                drift_type=DriftType.NONE,
                severity=0.0,
                monotonic_samples=0,
                sustained=False
            )

        # Calculate discrete derivative
        dx = x - self.last_value
        self.last_value = x

        # Store drift history
        self.drift_history.push(abs(dx))

        # Update monotonic tracking
        if dx != 0:
            current_sign = 1 if dx > 0 else -1
            if current_sign == self.last_drift_sign:
                self.monotonic_count += 1
            else:
                self.monotonic_count = 1
                self.last_drift_sign = current_sign
        else:
            self.monotonic_count = 0

        # Classify drift type
        drift_type = self._classify_drift(dx)

        # Calculate severity
        severity = self._calculate_severity(dx)

        # Check if sustained
        sustained = self._is_sustained()

        return DriftEvent(
            drift_rate=dx,
            drift_type=drift_type,
            severity=severity,
            monotonic_samples=self.monotonic_count,
            sustained=sustained
        )

    def _classify_drift(self, dx: float) -> DriftType:
        """
        Classify drift pattern.

        Args:
            dx: Current drift rate

        Returns:
            DriftType classification
        """
        abs_dx = abs(dx)

        # Check for monotonic drift first
        if self.monotonic_count >= self.monotonic_window:
            return DriftType.MONOTONIC

        # Large transient drift
        if abs_dx > self.large_threshold:
            return DriftType.TRANSIENT_LARGE

        # Small sustained drift
        if abs_dx > self.small_threshold and self._is_sustained():
            return DriftType.SUSTAINED_SMALL

        return DriftType.NONE

    def _calculate_severity(self, dx: float) -> float:
        """
        Calculate drift severity score (0-1).

        Args:
            dx: Current drift rate

        Returns:
            Severity between 0 and 1
        """
        abs_dx = abs(dx)

        # Normalize against large threshold
        severity = min(abs_dx / self.large_threshold, 1.0)

        # Increase severity if monotonic
        if self.monotonic_count >= self.monotonic_window:
            severity = min(severity * 1.5, 1.0)

        return severity

    def _is_sustained(self) -> bool:
        """
        Check if drift is sustained over window.

        Returns:
            True if sustained drift detected
        """
        samples = self.drift_history.get_samples()

        if len(samples) < self.sustained_window:
            return False

        # Check if most recent samples exceed small threshold
        sustained_count = np.sum(samples > self.small_threshold)
        ratio = sustained_count / len(samples)

        return ratio >= 0.7  # 70% of window must show drift

    def reset(self) -> None:
        """Reset detector state."""
        self.last_value = None
        self.drift_history.clear()
        self.monotonic_count = 0
        self.last_drift_sign = 0


class DriftAnalyzer:
    """
    Advanced drift analysis with statistics.

    Provides aggregate metrics over drift history.
    """

    def __init__(self, window_size: int = 50):
        """
        Initialize drift analyzer.

        Args:
            window_size: Window for statistical analysis
        """
        self.drift_buffer = SignalBuffer(window_size)
        self.event_history: List[DriftEvent] = []

    def add_event(self, event: DriftEvent) -> None:
        """
        Add drift event to history.

        Args:
            event: DriftEvent to record
        """
        self.drift_buffer.push(abs(event.drift_rate))
        self.event_history.append(event)

        # Keep only recent events
        if len(self.event_history) > 100:
            self.event_history = self.event_history[-100:]

    def get_statistics(self) -> Dict:
        """
        Get drift statistics.

        Returns:
            Dictionary of drift metrics
        """
        samples = self.drift_buffer.get_samples()

        if len(samples) == 0:
            return {
                "mean_drift": 0.0,
                "max_drift": 0.0,
                "drift_variance": 0.0,
                "drift_rate_stability": 1.0
            }

        mean_drift = np.mean(samples)
        max_drift = np.max(samples)
        variance = np.var(samples)

        # Stability: inverse of coefficient of variation
        cv = np.std(samples) / mean_drift if mean_drift > 0 else 0
        stability = 1.0 / (1.0 + cv)

        return {
            "mean_drift": float(mean_drift),
            "max_drift": float(max_drift),
            "drift_variance": float(variance),
            "drift_rate_stability": float(stability)
        }
