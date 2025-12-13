"""
SCADA-Comms-Front-End-Processor Adapter

Integrates with SCADA communications front-end.
Injects communication artifacts (jitter, dropouts, delays)
and tracks missing samples for signal quality assessment.
"""

from typing import Dict, Optional, List
from dataclasses import dataclass
import random
import time

from sqe.core.engine import SignalQualityEngine


@dataclass
class CommsArtifact:
    """Communication artifact configuration."""
    jitter_ms: float = 0.0           # Random timing jitter (milliseconds)
    dropout_probability: float = 0.0  # Probability of sample dropout (0-1)
    late_probability: float = 0.0     # Probability of late arrival (0-1)
    late_delay_ms: float = 0.0        # Delay for late samples (milliseconds)


@dataclass
class CommsStats:
    """Communication statistics."""
    total_samples: int = 0
    dropped_samples: int = 0
    late_samples: int = 0
    jittered_samples: int = 0
    average_jitter_ms: float = 0.0


class CommsAdapter:
    """
    Adapter for SCADA communications front-end integration.

    Simulates and tracks communication artifacts that affect
    signal quality.
    """

    def __init__(
        self,
        engine: SignalQualityEngine,
        artifact_config: Optional[CommsArtifact] = None
    ):
        """
        Initialize communications adapter.

        Args:
            engine: SignalQualityEngine instance
            artifact_config: Communication artifact configuration
        """
        self.engine = engine
        self.artifact_config = artifact_config or CommsArtifact()

        # Statistics tracking
        self.stats = CommsStats()
        self.jitter_history: List[float] = []

    def inject_artifacts(
        self,
        signal_values: Dict[str, Optional[float]]
    ) -> Dict[str, Optional[float]]:
        """
        Inject communication artifacts into signal data.

        Args:
            signal_values: Clean signal values

        Returns:
            Signal values with artifacts applied
        """
        artifacted = {}

        for signal_id, value in signal_values.items():
            self.stats.total_samples += 1

            # Apply dropout
            if random.random() < self.artifact_config.dropout_probability:
                artifacted[signal_id] = None
                self.stats.dropped_samples += 1
                continue

            # Apply jitter (affects timing, tracked but not modified here)
            if self.artifact_config.jitter_ms > 0:
                jitter = random.gauss(0, self.artifact_config.jitter_ms)
                self.jitter_history.append(abs(jitter))
                self.stats.jittered_samples += 1

            # Apply late arrival (for now, just track statistics)
            if random.random() < self.artifact_config.late_probability:
                self.stats.late_samples += 1
                # In real implementation, would delay sample delivery

            artifacted[signal_id] = value

        # Update average jitter
        if self.jitter_history:
            self.stats.average_jitter_ms = sum(self.jitter_history) / len(self.jitter_history)

        return artifacted

    def process_scan(
        self,
        signal_values: Dict[str, Optional[float]]
    ) -> Dict[str, Any]:
        """
        Process scan with communication artifacts.

        Args:
            signal_values: Raw signal values

        Returns:
            Processed results with comms statistics
        """
        # Inject artifacts
        artifacted_signals = self.inject_artifacts(signal_values)

        # Process through engine
        processed = self.engine.update(artifacted_signals)

        # Build result with comms stats
        return {
            "processed_signals": {
                sig_id: sig.to_dict()
                for sig_id, sig in processed.items()
            },
            "comms_stats": {
                "total_samples": self.stats.total_samples,
                "dropped_samples": self.stats.dropped_samples,
                "late_samples": self.stats.late_samples,
                "dropout_rate": self.stats.dropped_samples / self.stats.total_samples
                if self.stats.total_samples > 0 else 0,
                "late_rate": self.stats.late_samples / self.stats.total_samples
                if self.stats.total_samples > 0 else 0,
                "average_jitter_ms": self.stats.average_jitter_ms
            }
        }

    def set_artifact_config(self, config: CommsArtifact) -> None:
        """
        Update artifact configuration.

        Args:
            config: New artifact configuration
        """
        self.artifact_config = config

    def get_stats(self) -> Dict:
        """
        Get communication statistics.

        Returns:
            Dictionary with comms stats
        """
        return {
            "total_samples": self.stats.total_samples,
            "dropped_samples": self.stats.dropped_samples,
            "late_samples": self.stats.late_samples,
            "jittered_samples": self.stats.jittered_samples,
            "dropout_rate": self.stats.dropped_samples / self.stats.total_samples
            if self.stats.total_samples > 0 else 0,
            "late_rate": self.stats.late_samples / self.stats.total_samples
            if self.stats.total_samples > 0 else 0,
            "average_jitter_ms": self.stats.average_jitter_ms
        }

    def reset_stats(self) -> None:
        """Reset communication statistics."""
        self.stats = CommsStats()
        self.jitter_history = []


class CommsQualityMonitor:
    """
    Monitor communication quality metrics.

    Tracks long-term trends in communication performance.
    """

    def __init__(self, window_size: int = 100):
        """
        Initialize comms quality monitor.

        Args:
            window_size: History window size for trend analysis
        """
        self.window_size = window_size
        self.dropout_history: List[float] = []
        self.latency_history: List[float] = []

    def update(self, comms_stats: Dict) -> Dict:
        """
        Update monitor with new comms statistics.

        Args:
            comms_stats: Statistics from CommsAdapter

        Returns:
            Quality assessment with trends
        """
        dropout_rate = comms_stats.get("dropout_rate", 0.0)
        jitter = comms_stats.get("average_jitter_ms", 0.0)

        # Update histories
        self.dropout_history.append(dropout_rate)
        self.latency_history.append(jitter)

        # Trim to window size
        if len(self.dropout_history) > self.window_size:
            self.dropout_history = self.dropout_history[-self.window_size:]
        if len(self.latency_history) > self.window_size:
            self.latency_history = self.latency_history[-self.window_size:]

        # Calculate trends
        dropout_trend = self._calculate_trend(self.dropout_history)
        latency_trend = self._calculate_trend(self.latency_history)

        # Assess quality
        quality_score = self._assess_quality(dropout_rate, jitter)

        return {
            "current_dropout_rate": dropout_rate,
            "current_jitter_ms": jitter,
            "dropout_trend": dropout_trend,
            "latency_trend": latency_trend,
            "quality_score": quality_score,
            "quality_class": self._classify_quality(quality_score)
        }

    def _calculate_trend(self, history: List[float]) -> str:
        """Calculate trend direction."""
        if len(history) < 10:
            return "stable"

        recent = history[-10:]
        first_half = sum(recent[:5]) / 5
        second_half = sum(recent[5:]) / 5

        diff = second_half - first_half

        if diff > 0.05:
            return "degrading"
        elif diff < -0.05:
            return "improving"
        else:
            return "stable"

    def _assess_quality(self, dropout_rate: float, jitter: float) -> float:
        """Assess communication quality (0-100)."""
        # Dropout component (0-50 points)
        dropout_score = max(0, 50 * (1 - dropout_rate / 0.1))

        # Jitter component (0-50 points)
        jitter_score = max(0, 50 * (1 - jitter / 100))

        return dropout_score + jitter_score

    def _classify_quality(self, score: float) -> str:
        """Classify quality level."""
        if score >= 90:
            return "excellent"
        elif score >= 75:
            return "good"
        elif score >= 50:
            return "fair"
        elif score >= 25:
            return "poor"
        else:
            return "critical"
