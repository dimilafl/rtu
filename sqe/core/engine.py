"""
Signal Quality Engine - Main processing engine.

Integrates all DSP components into a unified signal processing pipeline.
Designed for deterministic, real-time operation within PLC scan cycles.
"""

from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from collections import deque
import logging
import time

from sqe.core.sample import Sample, SampleQuality
from sqe.core.filters import EWMAFilter, HighPassFilter, MovingAverageFilter
from sqe.core.drift import DriftDetector, DriftEvent
from sqe.core.variance import VarianceCalculator, SpikeDetector
from sqe.core.freq_detect import OscillationDetector
from sqe.core.sqi import SignalQualityIndex, SQIWeights
from sqe.core.stale import StaleDetector
from sqe.core.step_change import StepChangeDetector
from sqe.core.plausibility import PlausibilityChecker
from sqe.core.signal_buffer import SignalBuffer


@dataclass
class SignalConfig:
    """Configuration for a signal processing pipeline."""
    signal_id: str

    # Filter parameters
    ewma_alpha: float = 0.3
    ma_window: int = 10

    # Drift parameters
    small_drift_threshold: float = 0.5
    large_drift_threshold: float = 5.0

    # Variance parameters
    variance_window: int = 20
    spike_k_sigma: float = 3.0

    # Frequency parameters
    reference_frequencies: List[float] = None
    sample_interval: float = 0.1
    freq_window: int = 50

    # Missing sample tracking
    missing_window: int = 100

    # Stale detection
    stale_window: int = 5
    stale_recovery_window: int = 3

    # Step-change detection
    step_baseline_window: int = 10
    step_threshold: float = 5.0
    step_persistence_scans: int = 3
    step_recovery_scans: int = 5

    # Plausibility constraints
    plausibility_min: Optional[float] = None
    plausibility_max: Optional[float] = None
    plausibility_max_rate: Optional[float] = None
    plausibility_persistence_scans: int = 1
    plausibility_recovery_scans: int = 1

    # SQI parameters
    sqi_weights: Optional[Dict[str, float]] = None
    sqi_noise_threshold: float = 0.1
    sqi_drift_threshold: float = 1.0
    sqi_spike_threshold: float = 0.05
    sqi_oscillation_threshold: float = 0.3

    # Alert thresholds
    sqi_critical_threshold: float = 25.0
    sqi_warning_threshold: float = 50.0
    drift_alert_threshold: float = 5.0
    spike_alert_threshold: float = 0.1

    def __post_init__(self):
        """Set default reference frequencies if not provided."""
        positive_int_params = {
            "ma_window": self.ma_window,
            "variance_window": self.variance_window,
            "freq_window": self.freq_window,
            "missing_window": self.missing_window,
            "stale_window": self.stale_window,
            "stale_recovery_window": self.stale_recovery_window,
            "step_baseline_window": self.step_baseline_window,
            "step_persistence_scans": self.step_persistence_scans,
            "step_recovery_scans": self.step_recovery_scans,
            "plausibility_persistence_scans": self.plausibility_persistence_scans,
            "plausibility_recovery_scans": self.plausibility_recovery_scans,
        }
        for name, value in positive_int_params.items():
            if value <= 0:
                raise ValueError(f"{name} must be > 0 (got {value}).")

        if self.stale_window <= 1:
            raise ValueError(
                f"stale_window must be > 1 (got {self.stale_window})."
            )

        if self.step_baseline_window <= 1:
            raise ValueError(
                "step_baseline_window must be > 1 "
                f"(got {self.step_baseline_window})."
            )

        if self.sample_interval <= 0:
            raise ValueError(
                f"sample_interval must be > 0 (got {self.sample_interval})."
            )

        non_negative_params = {
            "small_drift_threshold": self.small_drift_threshold,
            "large_drift_threshold": self.large_drift_threshold,
            "sqi_noise_threshold": self.sqi_noise_threshold,
            "sqi_drift_threshold": self.sqi_drift_threshold,
            "sqi_spike_threshold": self.sqi_spike_threshold,
            "sqi_oscillation_threshold": self.sqi_oscillation_threshold,
            "sqi_critical_threshold": self.sqi_critical_threshold,
            "sqi_warning_threshold": self.sqi_warning_threshold,
            "drift_alert_threshold": self.drift_alert_threshold,
            "spike_alert_threshold": self.spike_alert_threshold,
            "step_threshold": self.step_threshold,
        }
        for name, value in non_negative_params.items():
            if value < 0:
                raise ValueError(f"{name} must be >= 0 (got {value}).")

        if (
            self.plausibility_min is not None
            and self.plausibility_max is not None
            and self.plausibility_min > self.plausibility_max
        ):
            raise ValueError(
                "plausibility_min must be <= plausibility_max "
                f"(got {self.plausibility_min} > {self.plausibility_max})."
            )

        if self.reference_frequencies is None:
            # Default frequencies: 0.1 Hz, 0.5 Hz, 1 Hz
            self.reference_frequencies = [0.1, 0.5, 1.0]


@dataclass
class ProcessedSignal:
    """Output of signal processing pipeline."""
    signal_id: str
    timestamp: float

    # Raw and filtered values
    raw: float
    filtered_ewma: float
    filtered_ma: float
    highpass: float

    # Drift analysis
    drift: float
    drift_type: str
    drift_severity: float
    monotonic_samples: int

    # Variance and spike detection
    variance: float
    std_dev: float
    noise_level: float
    is_spike: bool
    spike_frequency: float

    # Frequency analysis
    oscillation_energy: float
    dominant_frequency: Optional[float]

    # Signal quality
    sqi: float
    quality_class: str
    sqi_trend: str
    sqi_components: Dict[str, float]
    sqi_weights: Dict[str, float]

    stale: bool
    stale_reason: Optional[str]
    step_change: bool
    step_offset: Optional[float]
    plausibility_violation: bool
    plausibility_reasons: List[str]
    plausibility_rate: Optional[float]

    # Alerts
    alert_level: str
    drift_alert: bool
    spike_alert: bool

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class SignalProcessor:
    """
    Complete signal processing pipeline for a single signal.

    Integrates filtering, drift detection, variance analysis,
    frequency detection, and quality indexing.
    """

    def __init__(self, config: SignalConfig):
        """
        Initialize signal processor.

        Args:
            config: Signal configuration
        """
        self.config = config
        self.sample_count = 0

        # Initialize filters
        self.ewma_filter = EWMAFilter(config.ewma_alpha)
        self.ma_filter = MovingAverageFilter(config.ma_window)
        self.hp_filter = HighPassFilter(config.ewma_alpha)

        # Initialize drift detector
        self.drift_detector = DriftDetector(
            small_drift_threshold=config.small_drift_threshold,
            large_drift_threshold=config.large_drift_threshold
        )

        # Initialize variance and spike detection
        self.variance_calc = VarianceCalculator(config.variance_window)
        self.spike_detector = SpikeDetector(
            window_size=config.variance_window,
            k_sigma=config.spike_k_sigma
        )

        # Initialize frequency detection
        self.osc_detector = OscillationDetector(
            reference_frequencies=config.reference_frequencies,
            sample_interval=config.sample_interval,
            window_size=config.freq_window
        )

        # Initialize SQI calculator
        sqi_weights = None
        if self.config.sqi_weights:
            sqi_weights = SQIWeights(**self.config.sqi_weights)
        self.sqi_calc = SignalQualityIndex(
            weights=sqi_weights,
            noise_threshold=self.config.sqi_noise_threshold,
            drift_threshold=self.config.sqi_drift_threshold,
            spike_threshold=self.config.sqi_spike_threshold,
            oscillation_threshold=self.config.sqi_oscillation_threshold
        )

        # Track missing samples
        self.missing_count = 0
        self.missing_buffer = SignalBuffer(config.missing_window)
        self.quality_penalties = deque(maxlen=config.missing_window)
        self.last_quality_class: Optional[str] = None

        # Initialize stale detector
        self.stale_detector = StaleDetector(
            window_size=config.stale_window,
            recovery_window=config.stale_recovery_window,
        )

        # Initialize step-change detector
        self.step_detector = StepChangeDetector(
            baseline_window=config.step_baseline_window,
            step_threshold=config.step_threshold,
            persistence_scans=config.step_persistence_scans,
            recovery_scans=config.step_recovery_scans,
        )

        # Initialize plausibility checker
        self.plausibility_checker = PlausibilityChecker(
            min_value=config.plausibility_min,
            max_value=config.plausibility_max,
            max_rate=config.plausibility_max_rate,
            persistence_scans=config.plausibility_persistence_scans,
            recovery_scans=config.plausibility_recovery_scans,
        )

    def update(
        self,
        x: Optional[float],
        timestamp: Optional[float] = None,
        *,
        quality: SampleQuality = SampleQuality.GOOD,
        source_timestamp: Optional[float] = None,
    ) -> Optional[ProcessedSignal]:
        """
        Process new sample through complete pipeline.

        Args:
            x: Raw signal value (None if missing)
            timestamp: Optional sample timestamp override

        Returns:
            ProcessedSignal with all analysis results, or None if sample is missing
        """
        self.sample_count += 1
        if quality == SampleQuality.BAD:
            x = None

        penalty = 0.0
        if x is None or quality == SampleQuality.BAD:
            penalty = 1.0
        elif quality == SampleQuality.UNCERTAIN:
            penalty = 0.5
        self.quality_penalties.append(penalty)
        self.missing_buffer.push(x)

        # Handle missing sample
        if x is None:
            self.missing_count += 1
            return None

        if timestamp is None:
            timestamp = time.time()
        effective_timestamp = (
            source_timestamp if source_timestamp is not None else timestamp
        )

        # Apply filters
        filtered_ewma = self.ewma_filter.update(x)
        filtered_ma = self.ma_filter.update(x)
        highpass = self.hp_filter.update(x)

        # Drift detection
        drift_event = self.drift_detector.update(x)

        # Variance and spike detection
        variance_result = self.variance_calc.update(x)
        spike_result = self.spike_detector.update(x)

        # Frequency detection
        freq_result = self.osc_detector.update(x)

        # Stale detection
        stale_result = self.stale_detector.update(x, effective_timestamp)

        # Step-change detection
        step_result = self.step_detector.update(x)

        # Plausibility checks
        plausibility_result = self.plausibility_checker.update(
            x, effective_timestamp
        )

        # Calculate SQI
        missing_ratio = self.get_effective_missing_ratio()
        stale_score = 0.0 if stale_result.is_stale else 100.0
        step_score = 0.0 if step_result.is_step else 100.0
        plausibility_score = 0.0 if plausibility_result.is_violation else 100.0
        sqi_result = self.sqi_calc.calculate(
            noise_level=variance_result["noise_level"],
            drift_rate=abs(drift_event.drift_rate),
            spike_frequency=spike_result["spike_frequency"],
            oscillation_energy=freq_result["total_oscillation_energy"],
            missing_ratio=missing_ratio,
            stale_score=stale_score,
            step_score=step_score,
            plausibility_score=plausibility_score,
        )
        self.last_quality_class = sqi_result["quality_class"]

        alert_level = "none"
        if sqi_result["sqi"] <= self.config.sqi_critical_threshold:
            alert_level = "critical"
        elif sqi_result["sqi"] <= self.config.sqi_warning_threshold:
            alert_level = "warning"

        drift_alert = abs(drift_event.drift_rate) >= self.config.drift_alert_threshold
        spike_alert = spike_result["spike_frequency"] >= self.config.spike_alert_threshold

        # Build processed signal output
        return ProcessedSignal(
            signal_id=self.config.signal_id,
            timestamp=timestamp,
            raw=x,
            filtered_ewma=filtered_ewma,
            filtered_ma=filtered_ma,
            highpass=highpass,
            drift=drift_event.drift_rate,
            drift_type=drift_event.drift_type.value,
            drift_severity=drift_event.severity,
            monotonic_samples=drift_event.monotonic_samples,
            variance=variance_result["variance"],
            std_dev=variance_result["std_dev"],
            noise_level=variance_result["noise_level"],
            is_spike=spike_result["is_spike"],
            spike_frequency=spike_result["spike_frequency"],
            oscillation_energy=freq_result["total_oscillation_energy"],
            dominant_frequency=freq_result["dominant_frequency"],
            sqi=sqi_result["sqi"],
            quality_class=sqi_result["quality_class"],
            sqi_trend=sqi_result["trend"],
            sqi_components=sqi_result["components"],
            sqi_weights=sqi_result["weights"],
            stale=stale_result.is_stale,
            stale_reason=stale_result.reason,
            step_change=step_result.is_step,
            step_offset=step_result.offset,
            plausibility_violation=plausibility_result.is_violation,
            plausibility_reasons=plausibility_result.reasons,
            plausibility_rate=plausibility_result.rate_of_change,
            alert_level=alert_level,
            drift_alert=drift_alert,
            spike_alert=spike_alert
        )

    def reset(self) -> None:
        """Reset all processor state."""
        self.sample_count = 0
        self.missing_count = 0
        self.missing_buffer.clear()
        self.quality_penalties.clear()
        self.last_quality_class = None
        self.ewma_filter.reset()
        self.ma_filter.reset()
        self.hp_filter.reset()
        self.drift_detector.reset()
        self.variance_calc.reset()
        self.spike_detector.reset()
        self.osc_detector.reset()
        self.sqi_calc.reset()
        self.stale_detector.reset()
        self.step_detector.reset()
        self.plausibility_checker.reset()

    def get_effective_missing_ratio(self) -> float:
        """Return the mean quality penalty for the missing window."""
        if not self.quality_penalties:
            return 0.0
        return sum(self.quality_penalties) / len(self.quality_penalties)


class SignalQualityEngine:
    """
    Main Signal Quality Engine.

    Manages multiple signal processors and provides unified interface
    for signal registration and processing.
    """

    def __init__(
        self,
        scan_interval: float = 0.1,
        auto_register: bool = True,
        max_signals: Optional[int] = None,
        treat_missing_signals_as_none: bool = True,
        log_scan_timing: bool = False,
        log_quality_changes: bool = False,
        log_anomalies: bool = False,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize Signal Quality Engine.

        Args:
            scan_interval: Expected time between scans (seconds)
            auto_register: Automatically register unknown signals on update
            max_signals: Maximum number of registered signals (None for unlimited)
            treat_missing_signals_as_none: Treat missing registered signals as None
        """
        self.scan_interval = scan_interval
        self.auto_register = auto_register
        if max_signals is not None and max_signals <= 0:
            raise ValueError("max_signals must be positive or None")
        self.max_signals = max_signals
        self.treat_missing_signals_as_none = treat_missing_signals_as_none
        self.processors: Dict[str, SignalProcessor] = {}
        self.scan_count = 0
        self.last_scan_time: Optional[float] = None
        self.log_scan_timing = log_scan_timing
        self.log_quality_changes = log_quality_changes
        self.log_anomalies = log_anomalies
        self.logger = logger or logging.getLogger(__name__)

    def register_signal(
        self,
        signal_id: str,
        config: Optional[SignalConfig] = None
    ) -> None:
        """
        Register a new signal for processing.

        Args:
            signal_id: Unique identifier for signal
            config: Signal configuration (uses defaults if None)
        """
        if signal_id in self.processors:
            raise ValueError(f"Signal {signal_id} already registered")
        if self.max_signals is not None and len(self.processors) >= self.max_signals:
            raise ValueError("Maximum number of registered signals reached")

        if config is None:
            config = SignalConfig(
                signal_id=signal_id,
                sample_interval=self.scan_interval
            )
        elif config.signal_id != signal_id:
            raise ValueError(
                "Signal config signal_id must match registration key"
            )

        self.processors[signal_id] = SignalProcessor(config)

    def unregister_signal(self, signal_id: str) -> None:
        """
        Remove a signal from processing.

        Args:
            signal_id: Signal to remove
        """
        if signal_id in self.processors:
            del self.processors[signal_id]

    def update(
        self,
        signals: Dict[str, Optional[float]],
        timestamp: Optional[float] = None,
    ) -> Dict[str, ProcessedSignal]:
        """
        Process one scan cycle for all signals.

        Args:
            signals: Dictionary mapping signal_id to raw value (None if missing)
            timestamp: Optional scan timestamp override

        Returns:
            Dictionary mapping signal_id to ProcessedSignal
        """
        self.scan_count += 1
        current_time = time.time()

        # Track scan timing
        if self.last_scan_time is not None:
            actual_interval = current_time - self.last_scan_time
            if self.log_scan_timing:
                self.logger.debug("Scan interval %.4fs", actual_interval)

        self.last_scan_time = current_time

        results = {}

        signal_ids = set(signals.keys())
        if self.treat_missing_signals_as_none:
            signal_ids |= set(self.processors.keys())

        for signal_id in signal_ids:
            if signal_id not in self.processors:
                if not self.auto_register:
                    raise ValueError(f"Signal {signal_id} not registered")
                # Auto-register unknown signals
                self.register_signal(signal_id)

            value = signals.get(signal_id)
            processor = self.processors[signal_id]
            prev_quality = processor.last_quality_class
            processed = processor.update(value, timestamp=timestamp)
            if processed is not None:
                if (
                    self.log_quality_changes
                    and prev_quality is not None
                    and prev_quality != processed.quality_class
                ):
                    self.logger.info(
                        "Signal %s quality changed %s -> %s",
                        signal_id,
                        prev_quality,
                        processed.quality_class,
                    )
                if self.log_anomalies and (
                    processed.drift_type != "none"
                    or processed.is_spike
                    or processed.alert_level != "none"
                ):
                    self.logger.warning(
                        "Signal %s anomaly drift=%s spike=%s alert=%s",
                        signal_id,
                        processed.drift_type,
                        processed.is_spike,
                        processed.alert_level,
                    )
                results[signal_id] = processed

        return results

    def update_samples(
        self,
        samples: Dict[str, Sample],
        timestamp: Optional[float] = None,
    ) -> Dict[str, ProcessedSignal]:
        """Process one scan cycle for all signals with sample metadata."""
        self.scan_count += 1
        current_time = time.time()

        if self.last_scan_time is not None:
            actual_interval = current_time - self.last_scan_time
            if self.log_scan_timing:
                self.logger.debug("Scan interval %.4fs", actual_interval)

        self.last_scan_time = current_time

        results: Dict[str, ProcessedSignal] = {}

        signal_ids = set(samples.keys())
        if self.treat_missing_signals_as_none:
            signal_ids |= set(self.processors.keys())

        for signal_id in signal_ids:
            if signal_id not in self.processors:
                if not self.auto_register:
                    raise ValueError(f"Signal {signal_id} not registered")
                self.register_signal(signal_id)

            sample = samples.get(signal_id)
            if sample is None:
                sample = Sample(value=None)

            processor = self.processors[signal_id]
            prev_quality = processor.last_quality_class
            processed = processor.update(
                sample.value,
                timestamp=timestamp,
                quality=sample.quality,
                source_timestamp=sample.source_timestamp,
            )
            if processed is not None:
                if (
                    self.log_quality_changes
                    and prev_quality is not None
                    and prev_quality != processed.quality_class
                ):
                    self.logger.info(
                        "Signal %s quality changed %s -> %s",
                        signal_id,
                        prev_quality,
                        processed.quality_class,
                    )
                if self.log_anomalies and (
                    processed.drift_type != "none"
                    or processed.is_spike
                    or processed.alert_level != "none"
                ):
                    self.logger.warning(
                        "Signal %s anomaly drift=%s spike=%s alert=%s",
                        signal_id,
                        processed.drift_type,
                        processed.is_spike,
                        processed.alert_level,
                    )
                results[signal_id] = processed

        return results

    def update_single(
        self,
        signal_id: str,
        value: Optional[float],
        timestamp: Optional[float] = None,
    ) -> Optional[ProcessedSignal]:
        """
        Process single signal update.

        Args:
            signal_id: Signal identifier
            value: Raw signal value
            timestamp: Optional sample timestamp override

        Returns:
            ProcessedSignal or None if missing
        """
        results = self.update({signal_id: value}, timestamp=timestamp)
        return results.get(signal_id)

    def get_signal_stats(self, signal_id: str) -> Dict:
        """
        Get statistics for a specific signal.

        Args:
            signal_id: Signal identifier

        Returns:
            Dictionary with signal statistics
        """
        if signal_id not in self.processors:
            raise ValueError(f"Signal {signal_id} not registered")

        processor = self.processors[signal_id]

        return {
            "signal_id": signal_id,
            "sample_count": processor.sample_count,
            "missing_count": processor.missing_count,
            "missing_ratio": processor.missing_buffer.get_missing_ratio(),
            "effective_missing_ratio": processor.get_effective_missing_ratio(),
            "sqi_stats": processor.sqi_calc.get_statistics()
        }

    def get_all_stats(self) -> Dict[str, Dict]:
        """
        Get statistics for all registered signals.

        Returns:
            Dictionary mapping signal_id to statistics
        """
        return {
            signal_id: self.get_signal_stats(signal_id)
            for signal_id in self.processors.keys()
        }

    def reset_signal(self, signal_id: str) -> None:
        """
        Reset state for a specific signal.

        Args:
            signal_id: Signal to reset
        """
        if signal_id in self.processors:
            self.processors[signal_id].reset()

    def reset_all(self) -> None:
        """Reset all signals and engine state."""
        for processor in self.processors.values():
            processor.reset()
        self.scan_count = 0
        self.last_scan_time = None

    def get_registered_signals(self) -> List[str]:
        """
        Get list of registered signal IDs.

        Returns:
            List of signal identifiers
        """
        return list(self.processors.keys())
