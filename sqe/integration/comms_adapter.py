"""
SCADA-Comms-Front-End-Processor Adapter

Integrates with SCADA communications front-end.
Ingests transport telemetry (poll success, RTT, jitter, dropout streaks)
and tracks missing samples for signal quality assessment.
"""

from typing import Any, Dict, Optional, List
from dataclasses import dataclass, asdict

from sqe.core.engine import SignalQualityEngine


@dataclass
class CommsArtifact:
    """Deprecated communication artifact configuration."""
    jitter_ms: float = 0.0           # Random timing jitter (milliseconds)
    dropout_probability: float = 0.0  # Probability of sample dropout (0-1)
    late_probability: float = 0.0     # Probability of late arrival (0-1)
    late_delay_ms: float = 0.0        # Delay for late samples (milliseconds)


@dataclass(frozen=True)
class CommsTelemetry:
    """Raw transport telemetry for a single poll."""
    poll_success: bool
    rtt_ms: float
    jitter_ms: float
    dropout_streak: int = 0


@dataclass(frozen=True)
class CommsAdapterSettings:
    """Settings for comms adapter defaults."""
    track_jitter: bool = True
    track_dropouts: bool = True
    track_late_arrivals: bool = True
    quality_monitor_window: int = 100
    max_rtt_ms: float = 500.0
    max_jitter_ms: float = 200.0
    max_dropout_streak: int = 3


@dataclass(frozen=True)
class CommsHealth:
    """Derived communication health state."""
    poll_success: bool
    rtt_ms: float
    jitter_ms: float
    dropout_streak: int
    degraded: bool


@dataclass
class CommsStats:
    """Communication statistics."""
    total_polls: int = 0
    failed_polls: int = 0
    late_samples: int = 0
    jittered_samples: int = 0
    average_jitter_ms: float = 0.0
    average_rtt_ms: float = 0.0
    max_dropout_streak: int = 0
    current_dropout_streak: int = 0


class CommsAdapter:
    """
    Adapter for SCADA communications front-end integration.

    Tracks communication telemetry that affects signal quality.
    """

    def __init__(
        self,
        engine: SignalQualityEngine,
        artifact_config: Optional[CommsArtifact] = None,
        settings: Optional[CommsAdapterSettings] = None,
    ):
        """
        Initialize communications adapter.

        Args:
            engine: SignalQualityEngine instance
            artifact_config: Communication artifact configuration
        """
        self.engine = engine
        self.artifact_config = artifact_config or CommsArtifact()
        self.settings = settings or CommsAdapterSettings()

        # Statistics tracking
        self.stats = CommsStats()
        self.jitter_history: List[float] = []
        self.rtt_history: List[float] = []

    def process_scan(
        self,
        signal_values: Dict[str, Optional[float]],
        telemetry_by_signal: Optional[Dict[str, CommsTelemetry]] = None,
    ) -> Dict[str, Any]:
        """
        Process scan with communication artifacts.

        Args:
            signal_values: Raw signal values
            telemetry_by_signal: Optional transport telemetry keyed by signal_id

        Returns:
            Processed results with comms statistics
        """
        comms_health_by_signal: Dict[str, CommsHealth] = {}
        artifacted_signals = dict(signal_values)
        if telemetry_by_signal:
            for signal_id, telemetry in telemetry_by_signal.items():
                self._update_stats(telemetry)
                health = self._build_health(telemetry)
                comms_health_by_signal[signal_id] = health
                if not telemetry.poll_success:
                    artifacted_signals[signal_id] = None

        # Process through engine
        processed = self.engine.update(artifacted_signals)

        # Build result with comms stats
        return {
            "processed_signals": {
                sig_id: sig.to_dict()
                for sig_id, sig in processed.items()
            },
            "comms_stats": self.get_stats(),
            "comms_health_by_signal": {
                signal_id: asdict(health)
                for signal_id, health in comms_health_by_signal.items()
            },
        }

    def set_artifact_config(self, config: CommsArtifact) -> None:
        """
        Update artifact configuration.

        Args:
            config: New artifact configuration
        """
        self.artifact_config = config

    def set_settings(self, settings: CommsAdapterSettings) -> None:
        """Update comms adapter settings."""
        self.settings = settings

    @classmethod
    def from_config(
        cls,
        engine: SignalQualityEngine,
        config: Dict[str, Any],
        artifact_config: Optional[CommsArtifact] = None,
    ) -> "CommsAdapter":
        """Construct adapter from merged configuration dictionary."""
        integration = config.get("integration", {})
        comms = integration.get("comms", {})
        settings = CommsAdapterSettings(
            track_jitter=bool(comms.get("track_jitter", True)),
            track_dropouts=bool(comms.get("track_dropouts", True)),
            track_late_arrivals=bool(comms.get("track_late_arrivals", True)),
            quality_monitor_window=int(comms.get("quality_monitor_window", 100)),
            max_rtt_ms=float(comms.get("max_rtt_ms", 500.0)),
            max_jitter_ms=float(comms.get("max_jitter_ms", 200.0)),
            max_dropout_streak=int(comms.get("max_dropout_streak", 3)),
        )
        return cls(
            engine=engine,
            artifact_config=artifact_config,
            settings=settings,
        )

    def get_stats(self) -> Dict:
        """
        Get communication statistics.

        Returns:
            Dictionary with comms stats
        """
        total_polls = self.stats.total_polls
        failed_polls = self.stats.failed_polls
        return {
            "total_polls": total_polls,
            "failed_polls": failed_polls,
            "late_samples": self.stats.late_samples,
            "jittered_samples": self.stats.jittered_samples,
            "poll_failure_rate": failed_polls / total_polls if total_polls > 0 else 0,
            "late_rate": self.stats.late_samples / total_polls if total_polls > 0 else 0,
            "average_jitter_ms": self.stats.average_jitter_ms,
            "average_rtt_ms": self.stats.average_rtt_ms,
            "max_dropout_streak": self.stats.max_dropout_streak,
            "current_dropout_streak": self.stats.current_dropout_streak,
        }

    def reset_stats(self) -> None:
        """Reset communication statistics."""
        self.stats = CommsStats()
        self.jitter_history = []
        self.rtt_history = []

    def _update_stats(self, telemetry: CommsTelemetry) -> None:
        self.stats.total_polls += 1
        if not telemetry.poll_success:
            self.stats.failed_polls += 1
        if self.settings.track_jitter:
            self.jitter_history.append(float(telemetry.jitter_ms))
            self.stats.jittered_samples += 1
        self.rtt_history.append(float(telemetry.rtt_ms))
        if self.jitter_history:
            self.stats.average_jitter_ms = sum(self.jitter_history) / len(
                self.jitter_history
            )
        if self.rtt_history:
            self.stats.average_rtt_ms = sum(self.rtt_history) / len(self.rtt_history)
        self.stats.current_dropout_streak = int(telemetry.dropout_streak)
        self.stats.max_dropout_streak = max(
            self.stats.max_dropout_streak, self.stats.current_dropout_streak
        )

    def _build_health(self, telemetry: CommsTelemetry) -> CommsHealth:
        degraded = (
            not telemetry.poll_success
            or telemetry.rtt_ms >= self.settings.max_rtt_ms
            or telemetry.jitter_ms >= self.settings.max_jitter_ms
            or telemetry.dropout_streak >= self.settings.max_dropout_streak
        )
        return CommsHealth(
            poll_success=telemetry.poll_success,
            rtt_ms=float(telemetry.rtt_ms),
            jitter_ms=float(telemetry.jitter_ms),
            dropout_streak=int(telemetry.dropout_streak),
            degraded=degraded,
        )


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

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
    ) -> "CommsQualityMonitor":
        """Construct comms quality monitor from config defaults."""
        integration = config.get("integration", {})
        comms = integration.get("comms", {})
        return cls(window_size=int(comms.get("quality_monitor_window", 100)))

    def update(self, comms_stats: Dict) -> Dict:
        """
        Update monitor with new comms statistics.

        Args:
            comms_stats: Statistics from CommsAdapter

        Returns:
            Quality assessment with trends
        """
        poll_failure_rate = comms_stats.get("poll_failure_rate", 0.0)
        jitter = comms_stats.get("average_jitter_ms", 0.0)
        rtt = comms_stats.get("average_rtt_ms", 0.0)
        dropout_streak = comms_stats.get("max_dropout_streak", 0)

        # Update histories
        self.dropout_history.append(poll_failure_rate)
        self.latency_history.append(rtt)

        # Trim to window size
        if len(self.dropout_history) > self.window_size:
            self.dropout_history = self.dropout_history[-self.window_size:]
        if len(self.latency_history) > self.window_size:
            self.latency_history = self.latency_history[-self.window_size:]

        # Calculate trends
        dropout_trend = self._calculate_trend(self.dropout_history)
        latency_trend = self._calculate_trend(self.latency_history)

        # Assess quality
        quality_score = self._assess_quality(
            poll_failure_rate, rtt, jitter, dropout_streak
        )

        return {
            "current_poll_failure_rate": poll_failure_rate,
            "current_jitter_ms": jitter,
            "current_rtt_ms": rtt,
            "max_dropout_streak": dropout_streak,
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

    def _assess_quality(
        self,
        poll_failure_rate: float,
        rtt: float,
        jitter: float,
        dropout_streak: int,
    ) -> float:
        """Assess communication quality (0-100)."""
        # Poll success component (0-40 points)
        poll_score = max(0, 40 * (1 - poll_failure_rate / 0.1))

        # RTT component (0-30 points)
        rtt_score = max(0, 30 * (1 - rtt / 500))

        # Jitter component (0-20 points)
        jitter_score = max(0, 20 * (1 - jitter / 200))

        # Dropout streak penalty (0-10 points)
        streak_penalty = min(10, dropout_streak * 2)

        return poll_score + rtt_score + jitter_score + (10 - streak_penalty)

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
