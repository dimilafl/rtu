"""
Signal Quality Engine - Main processing engine.

Integrates all DSP components into a unified signal processing pipeline.
Designed for deterministic, real-time operation within PLC scan cycles.
"""

from dataclasses import dataclass, asdict, field
from typing import Callable, Deque, Dict, Iterable, List, Optional, Set
from collections import deque
import logging
import time

from sqe.core.sample import Sample, SampleQuality
from sqe.core.filters import EWMAFilter, HighPassFilter, MovingAverageFilter
from sqe.core.drift import DriftDetector, DriftEvent
from sqe.core.variance import VarianceCalculator, SpikeDetector
from sqe.core.freq_detect import OscillationDetector
from sqe.core.sqi import SignalQualityIndex, SQIWeights
from sqe.core.stale import StaleDetector, StaleResult
from sqe.core.step_change import StepChangeDetector, StepChangeResult
from sqe.core.plausibility import PlausibilityChecker, PlausibilityResult
from sqe.core.signal_buffer import SignalBuffer
from sqe.core.innovation import InnovationModel


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
    reference_frequencies: List[float] = field(default_factory=list)
    sample_interval: float = 0.1
    freq_window: int = 50
    enable_fft: bool = False

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

    # Innovation model settings (plumbing only; runtime integration is gated)
    innovation_enabled: bool = False
    innovation_q: float = 0.01
    innovation_r: float = 1.0
    innovation_beta: float = 0.05
    innovation_s_min: float = 1.0e-12
    innovation_p0_var: float = 1.0e6
    innovation_v0_var: float = 1.0e4
    innovation_z_spike: float = 6.0

    def __post_init__(self):
        """Set default reference frequencies if not provided."""
        positive_int_params = {
            "ma_window": self.ma_window,
            "variance_window": self.variance_window,
            "freq_window": self.freq_window,
            "missing_window": self.missing_window,
            "plausibility_persistence_scans": self.plausibility_persistence_scans,
            "plausibility_recovery_scans": self.plausibility_recovery_scans,
        }
        for name, value in positive_int_params.items():
            if value <= 0:
                raise ValueError(f"{name} must be > 0 (got {value}).")

        optional_window_params = {
            "stale_window": self.stale_window,
            "stale_recovery_window": self.stale_recovery_window,
            "step_baseline_window": self.step_baseline_window,
            "step_persistence_scans": self.step_persistence_scans,
            "step_recovery_scans": self.step_recovery_scans,
        }
        for name, value in optional_window_params.items():
            if value < 0:
                raise ValueError(f"{name} must be >= 0 (got {value}).")

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


        if self.innovation_q < 0:
            raise ValueError("innovation.q must be >= 0")
        if self.innovation_r <= 0:
            raise ValueError("innovation.r must be > 0")
        if self.innovation_beta <= 0 or self.innovation_beta > 1:
            raise ValueError("innovation.beta must be > 0 and <= 1")
        if self.innovation_s_min <= 0:
            raise ValueError("innovation.s_min must be > 0")
        if self.innovation_p0_var <= 0:
            raise ValueError("innovation.p0_var must be > 0")
        if self.innovation_v0_var <= 0:
            raise ValueError("innovation.v0_var must be > 0")
        if self.innovation_z_spike <= 0:
            raise ValueError("innovation.z_spike must be > 0")

        if self.reference_frequencies is None:
            self.reference_frequencies = []

    def enabled_components(self, required_causes: Iterable[str]) -> Set[str]:
        """Return SQI component names that should be computed."""
        required = {str(cause).lower() for cause in required_causes}
        weight_map = self.sqi_weights or SQIWeights().__dict__

        def weight_enabled(name: str) -> bool:
            return float(weight_map.get(name, 0.0)) > 0.0

        thresholds = {
            "stale": self.stale_window > 1 and self.stale_recovery_window > 0,
            "step": (
                self.step_baseline_window > 1
                and self.step_threshold > 0
                and self.step_persistence_scans > 0
                and self.step_recovery_scans > 0
            ),
            "plausibility": (
                self.plausibility_min is not None
                or self.plausibility_max is not None
                or self.plausibility_max_rate is not None
            ),
            "oscillation": self.freq_window > 1
            and (
                self.enable_fft
                or (self.reference_frequencies and len(self.reference_frequencies) > 0)
            ),
        }

        enabled: Set[str] = set()
        for component in (
            "noise",
            "drift",
            "spikes",
            "oscillation",
            "missing",
            "stale",
            "step",
            "plausibility",
        ):
            threshold_enabled = thresholds.get(component, True)
            if component in required and not threshold_enabled:
                raise ValueError(
                    f"{component} is required but disabled by thresholds."
                )
            if component in required or (weight_enabled(component) and threshold_enabled):
                enabled.add(component)
        return enabled


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
    innovation_residual: Optional[float] = None
    innovation_S: Optional[float] = None
    innovation_z: Optional[float] = None
    innovation_v_hat: Optional[float] = None
    innovation_eta: Optional[float] = None
    innovation_z_spike: Optional[float] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class SignalProcessor:
    """
    Complete signal processing pipeline for a single signal.

    Integrates filtering, drift detection, variance analysis,
    frequency detection, and quality indexing.
    """

    def __init__(
        self,
        config: SignalConfig,
        *,
        required_causes: Optional[Iterable[str]] = None,
    ):
        """
        Initialize signal processor.

        Args:
            config: Signal configuration
        """
        self.config = config
        self.sample_count = 0
        required_causes = required_causes or set()
        enabled_components = self.config.enabled_components(required_causes)
        self.compute_stale = "stale" in enabled_components
        self.compute_step = "step" in enabled_components
        self.compute_plausibility = "plausibility" in enabled_components
        self.compute_oscillation = "oscillation" in enabled_components

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
        # Share single VarianceCalculator between variance tracking and spike detection
        self.variance_calc = VarianceCalculator(config.variance_window)
        self.spike_detector = SpikeDetector(
            window_size=config.variance_window,
            k_sigma=config.spike_k_sigma,
            variance_calc=self.variance_calc,
        )

        # Initialize frequency detection
        self.osc_detector = OscillationDetector(
            reference_frequencies=config.reference_frequencies,
            sample_interval=config.sample_interval,
            window_size=config.freq_window,
            enable_fft=config.enable_fft,
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
        self.stale_detector = None
        if self.compute_stale:
            self.stale_detector = StaleDetector(
                window_size=config.stale_window,
                recovery_window=config.stale_recovery_window,
            )

        # Initialize step-change detector
        self.step_detector = None
        if self.compute_step:
            self.step_detector = StepChangeDetector(
                baseline_window=config.step_baseline_window,
                step_threshold=config.step_threshold,
                persistence_scans=config.step_persistence_scans,
                recovery_scans=config.step_recovery_scans,
            )

        # Initialize plausibility checker
        self.plausibility_checker = None
        if self.compute_plausibility:
            self.plausibility_checker = PlausibilityChecker(
                min_value=config.plausibility_min,
                max_value=config.plausibility_max,
                max_rate=config.plausibility_max_rate,
                persistence_scans=config.plausibility_persistence_scans,
                recovery_scans=config.plausibility_recovery_scans,
            )

        self.innovation_model: Optional[InnovationModel] = None
        self._innovation_last_t: Optional[float] = None
        self._innovation_spike_ema: float = 0.0
        if self.config.innovation_enabled:
            self.innovation_model = InnovationModel(
                q=self.config.innovation_q,
                r=self.config.innovation_r,
                beta=self.config.innovation_beta,
                s_min=self.config.innovation_s_min,
                p0_var=self.config.innovation_p0_var,
                v0_var=self.config.innovation_v0_var,
            )

    def _innovation_dt(self, effective_timestamp: Optional[float]) -> float:
        """Compute deterministic monotone dt for innovation updates."""
        if effective_timestamp is None:
            return self.config.sample_interval

        if self._innovation_last_t is None:
            self._innovation_last_t = effective_timestamp
            return self.config.sample_interval

        if effective_timestamp <= self._innovation_last_t:
            return 0.0

        dt = effective_timestamp - self._innovation_last_t
        self._innovation_last_t = effective_timestamp
        return dt

    def update(
        self,
        x: Optional[float],
        timestamp: Optional[float] = None,
        *,
        quality: SampleQuality = SampleQuality.GOOD,
        source_timestamp: Optional[float] = None,
        baseline_stats_cache: Optional[Dict[str, Dict[str, float]]] = None,
        load_shed: bool = False,
        oscillation_cadence: int = 1,
        skip_fft: bool = False,
    ) -> Optional[ProcessedSignal]:
        """
        Process new sample through complete pipeline.

        Args:
            x: Raw signal value (None if missing)
            timestamp: Sample timestamp (required for non-missing samples)

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

        effective_timestamp = (
            source_timestamp if source_timestamp is not None else timestamp
        )

        # Handle missing sample
        if x is None:
            self.missing_count += 1
            if self.innovation_model is not None:
                dt = self._innovation_dt(effective_timestamp)
                self.innovation_model.update(None, dt)
            return None

        if timestamp is None:
            raise ValueError("timestamp is required for non-missing samples")

        # Apply filters
        filtered_ewma = self.ewma_filter.update(x)
        filtered_ma = self.ma_filter.update(x)
        highpass = self.hp_filter.update(x)

        # Drift detection
        drift_event = self.drift_detector.update(x)

        if self.innovation_model is not None:
            dt = self._innovation_dt(effective_timestamp)
            residual, innovation_S, z_score, innovation_v_hat, innovation_eta = (
                self.innovation_model.update(x, dt)
            )
            is_spike = (
                z_score is not None
                and abs(z_score) >= self.config.innovation_z_spike
            )
            if z_score is not None:
                beta = self.config.innovation_beta
                self._innovation_spike_ema = (
                    (1.0 - beta) * self._innovation_spike_ema
                    + beta * float(is_spike)
                )
            spike_result = {
                "is_spike": bool(is_spike),
                "spike_frequency": self._innovation_spike_ema,
            }
            innovation_result = {
                "innovation_residual": residual,
                "innovation_S": innovation_S,
                "innovation_z": z_score,
                "innovation_v_hat": innovation_v_hat,
                "innovation_eta": innovation_eta,
                "innovation_z_spike": self.config.innovation_z_spike,
            }
        else:
            # Spike detection BEFORE variance update (spike needs pre-update baseline stats)
            spike_result = self.spike_detector.update(
                x,
                signal_id=self.config.signal_id,
                baseline_stats_cache=baseline_stats_cache,
            )
            innovation_result = {
                "innovation_residual": None,
                "innovation_S": None,
                "innovation_z": None,
                "innovation_v_hat": None,
                "innovation_eta": None,
                "innovation_z_spike": None,
            }
        # Variance update (shared variance_calc is updated exactly once per sample)
        variance_result = self.variance_calc.update(x)

        # Frequency detection
        if self.compute_oscillation:
            freq_result = self.osc_detector.update(
                x,
                load_shed=load_shed,
                cadence=oscillation_cadence,
                skip_fft=skip_fft,
            )
        else:
            freq_result = {
                "correlation_components": {},
                "total_oscillation_energy": 0.0,
                "dominant_frequency": None,
                "dominant_magnitude": 0.0,
                "fft_peak_frequency": None,
                "fft_peak_magnitude": 0.0,
            }

        # Stale detection
        if self.compute_stale and self.stale_detector:
            stale_result = self.stale_detector.update(x, effective_timestamp)
        else:
            stale_result = StaleResult(
                is_stale=False,
                reason=None,
                flatline=False,
                timestamp_stale=False,
            )

        # Step-change detection
        if self.compute_step and self.step_detector:
            step_result = self.step_detector.update(x)
        else:
            step_result = StepChangeResult(
                is_step=False,
                baseline=None,
                step_level=None,
                offset=None,
            )

        # Plausibility checks
        if self.compute_plausibility and self.plausibility_checker:
            plausibility_result = self.plausibility_checker.update(
                x, effective_timestamp
            )
        else:
            plausibility_result = PlausibilityResult(
                is_violation=False,
                reasons=[],
                rate_of_change=None,
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
            innovation_residual=innovation_result["innovation_residual"],
            innovation_S=innovation_result["innovation_S"],
            innovation_z=innovation_result["innovation_z"],
            innovation_v_hat=innovation_result["innovation_v_hat"],
            innovation_eta=innovation_result["innovation_eta"],
            innovation_z_spike=innovation_result["innovation_z_spike"],
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
        self._innovation_last_t = None
        self._innovation_spike_ema = 0.0
        if self.innovation_model is not None:
            self.innovation_model.reset()
        self.osc_detector.reset()
        self.sqi_calc.reset()
        if self.stale_detector:
            self.stale_detector.reset()
        if self.step_detector:
            self.step_detector.reset()
        if self.plausibility_checker:
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
        unknown_signal_policy: str = "error",
        max_signals_policy: str = "error",
        log_scan_timing: bool = False,
        log_quality_changes: bool = False,
        log_anomalies: bool = False,
        compute_budget_ms: Optional[float] = None,
        load_shed_p95_window: int = 50,
        load_shed_oscillation_cadence: int = 3,
        load_shed_skip_fft: bool = True,
        required_incident_causes: Optional[Iterable[str]] = None,
        logger: Optional[logging.Logger] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        """
        Initialize Signal Quality Engine.

        Args:
            scan_interval: Expected time between scans (seconds)
            auto_register: Automatically register unknown signals on update
            max_signals: Maximum number of registered signals (None for unlimited)
            treat_missing_signals_as_none: Treat missing registered signals as None
            unknown_signal_policy: "error" or "ignore" for unknown signals
            max_signals_policy: "error", "ignore_new", or "evict_oldest"
        """
        self.scan_interval = scan_interval
        self.auto_register = auto_register
        if max_signals is not None and max_signals <= 0:
            raise ValueError("max_signals must be positive or None")
        self.max_signals = max_signals
        self.treat_missing_signals_as_none = treat_missing_signals_as_none
        self.unknown_signal_policy = self._validate_unknown_signal_policy(
            unknown_signal_policy
        )
        self.max_signals_policy = self._validate_max_signals_policy(
            max_signals_policy
        )
        self.processors: Dict[str, SignalProcessor] = {}
        self._registration_order: Deque[str] = deque()
        self.scan_count = 0
        self.last_scan_time: Optional[float] = None
        self.log_scan_timing = log_scan_timing
        self.log_quality_changes = log_quality_changes
        self.log_anomalies = log_anomalies
        self.logger = logger or logging.getLogger(__name__)
        self.compute_budget_s = (
            compute_budget_ms / 1000.0 if compute_budget_ms else None
        )
        self._scan_durations: Deque[float] = deque(
            maxlen=max(1, int(load_shed_p95_window))
        )
        self._scan_duration_p95: Optional[float] = None
        self._load_shed_active = False
        self._load_shed_oscillation_cadence = max(1, load_shed_oscillation_cadence)
        self._load_shed_skip_fft = load_shed_skip_fft
        self.required_incident_causes = (
            {str(cause).lower() for cause in required_incident_causes}
            if required_incident_causes
            else set()
        )
        self._clock = clock

    def _resolve_scan_timestamp(self, timestamp: Optional[float]) -> float:
        if timestamp is not None:
            return timestamp
        if self._clock is None:
            raise ValueError("scan timestamp is required when no clock is configured")
        return self._clock()

    def register_signal(
        self, signal_id: str, config: Optional[SignalConfig] = None
    ) -> bool:
        """
        Register a new signal for processing.

        Args:
            signal_id: Unique identifier for signal
            config: Signal configuration (uses defaults if None)
        """
        if signal_id in self.processors:
            raise ValueError(f"Signal {signal_id} already registered")
        if self.max_signals is not None and len(self.processors) >= self.max_signals:
            if self.max_signals_policy == "ignore_new":
                self.logger.warning(
                    "Maximum number of registered signals reached; ignoring %s",
                    signal_id,
                )
                return False
            if self.max_signals_policy == "evict_oldest":
                self._evict_oldest_signal()
            else:
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

        self.processors[signal_id] = SignalProcessor(
            config,
            required_causes=self.required_incident_causes,
        )
        self._registration_order.append(signal_id)
        return True

    def unregister_signal(self, signal_id: str) -> None:
        """
        Remove a signal from processing.

        Args:
            signal_id: Signal to remove
        """
        if signal_id in self.processors:
            del self.processors[signal_id]
            try:
                self._registration_order.remove(signal_id)
            except ValueError:
                pass

    def update(
        self,
        signals: Dict[str, Optional[float]],
        timestamp: Optional[float] = None,
    ) -> Dict[str, ProcessedSignal]:
        """
        Process one scan cycle for all signals.

        Args:
            signals: Dictionary mapping signal_id to raw value (None if missing)
            timestamp: Scan timestamp (required unless a clock is configured)

        Returns:
            Dictionary mapping signal_id to ProcessedSignal
        """
        self.scan_count += 1
        scan_timestamp = self._resolve_scan_timestamp(timestamp)

        # Track scan timing
        if self.last_scan_time is not None:
            actual_interval = scan_timestamp - self.last_scan_time
            if self.log_scan_timing:
                self.logger.debug("Scan interval %.4fs", actual_interval)

        self.last_scan_time = scan_timestamp

        results = {}
        # Cache baseline stats per signal for this scan. The cache is invalidated
        # after each scan because variance buffers update with new samples.
        baseline_stats_cache: Dict[str, Dict[str, float]] = {}

        registered_ids = [
            signal_id
            for signal_id in self._registration_order
            if signal_id in self.processors
        ]
        unknown_ids = [
            signal_id
            for signal_id in signals.keys()
            if signal_id not in self.processors
        ]

        for signal_id in registered_ids:
            if not self.treat_missing_signals_as_none and signal_id not in signals:
                continue
            value = signals.get(signal_id)
            processor = self.processors[signal_id]
            prev_quality = processor.last_quality_class
            scan_start = time.perf_counter() if self.compute_budget_s else None
            processed = processor.update(
                value,
                timestamp=scan_timestamp,
                baseline_stats_cache=baseline_stats_cache,
                load_shed=self._load_shed_active,
                oscillation_cadence=self._load_shed_oscillation_cadence,
                skip_fft=self._load_shed_skip_fft,
            )
            if scan_start is not None:
                scan_duration = time.perf_counter() - scan_start
                self._update_load_shedding(scan_duration)
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

        if unknown_ids:
            if not self.auto_register:
                if self.unknown_signal_policy == "ignore":
                    return results
                unknown_id = sorted(unknown_ids)[0]
                raise ValueError(f"Signal {unknown_id} not registered")
            for signal_id in sorted(unknown_ids):
                if not self.register_signal(signal_id):
                    continue
                value = signals.get(signal_id)
                processor = self.processors[signal_id]
                prev_quality = processor.last_quality_class
                scan_start = time.perf_counter() if self.compute_budget_s else None
                processed = processor.update(
                    value,
                    timestamp=scan_timestamp,
                    baseline_stats_cache=baseline_stats_cache,
                    load_shed=self._load_shed_active,
                    oscillation_cadence=self._load_shed_oscillation_cadence,
                    skip_fft=self._load_shed_skip_fft,
                )
                if scan_start is not None:
                    scan_duration = time.perf_counter() - scan_start
                    self._update_load_shedding(scan_duration)
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
        scan_timestamp = self._resolve_scan_timestamp(timestamp)

        if self.last_scan_time is not None:
            actual_interval = scan_timestamp - self.last_scan_time
            if self.log_scan_timing:
                self.logger.debug("Scan interval %.4fs", actual_interval)

        self.last_scan_time = scan_timestamp

        results: Dict[str, ProcessedSignal] = {}
        # Cache baseline stats per signal for this scan. The cache is invalidated
        # after each scan because variance buffers update with new samples.
        baseline_stats_cache: Dict[str, Dict[str, float]] = {}

        registered_ids = [
            signal_id
            for signal_id in self._registration_order
            if signal_id in self.processors
        ]
        unknown_ids = [
            signal_id
            for signal_id in samples.keys()
            if signal_id not in self.processors
        ]

        for signal_id in registered_ids:
            if not self.treat_missing_signals_as_none and signal_id not in samples:
                continue
            sample = samples.get(signal_id)
            if sample is None:
                sample = Sample(value=None)

            processor = self.processors[signal_id]
            prev_quality = processor.last_quality_class
            scan_start = time.perf_counter() if self.compute_budget_s else None
            processed = processor.update(
                sample.value,
                timestamp=scan_timestamp,
                quality=sample.quality,
                source_timestamp=sample.source_timestamp,
                baseline_stats_cache=baseline_stats_cache,
                load_shed=self._load_shed_active,
                oscillation_cadence=self._load_shed_oscillation_cadence,
                skip_fft=self._load_shed_skip_fft,
            )
            if scan_start is not None:
                scan_duration = time.perf_counter() - scan_start
                self._update_load_shedding(scan_duration)
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

        if unknown_ids:
            if not self.auto_register:
                if self.unknown_signal_policy == "ignore":
                    return results
                unknown_id = sorted(unknown_ids)[0]
                raise ValueError(f"Signal {unknown_id} not registered")
            for signal_id in sorted(unknown_ids):
                if not self.register_signal(signal_id):
                    continue
                sample = samples.get(signal_id)
                if sample is None:
                    sample = Sample(value=None)
                processor = self.processors[signal_id]
                prev_quality = processor.last_quality_class
                scan_start = time.perf_counter() if self.compute_budget_s else None
                processed = processor.update(
                    sample.value,
                    timestamp=scan_timestamp,
                    quality=sample.quality,
                    source_timestamp=sample.source_timestamp,
                    baseline_stats_cache=baseline_stats_cache,
                    load_shed=self._load_shed_active,
                    oscillation_cadence=self._load_shed_oscillation_cadence,
                    skip_fft=self._load_shed_skip_fft,
                )
                if scan_start is not None:
                    scan_duration = time.perf_counter() - scan_start
                    self._update_load_shedding(scan_duration)
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
        self._scan_durations.clear()
        self._scan_duration_p95 = None
        self._load_shed_active = False

    def get_registered_signals(self) -> List[str]:
        """
        Get list of registered signal IDs.

        Returns:
            List of signal identifiers
        """
        return list(self.processors.keys())

    @staticmethod
    def _validate_unknown_signal_policy(policy: str) -> str:
        normalized = str(policy).lower()
        if normalized not in {"error", "ignore"}:
            raise ValueError(
                "unknown_signal_policy must be 'error' or 'ignore'"
            )
        return normalized

    @staticmethod
    def _validate_max_signals_policy(policy: str) -> str:
        normalized = str(policy).lower()
        if normalized not in {"error", "ignore_new", "evict_oldest"}:
            raise ValueError(
                "max_signals_policy must be 'error', 'ignore_new', "
                "or 'evict_oldest'"
            )
        return normalized

    def _evict_oldest_signal(self) -> None:
        while self._registration_order:
            oldest = self._registration_order.popleft()
            if oldest in self.processors:
                del self.processors[oldest]
                self.logger.warning(
                    "Evicted oldest signal %s to honor max_signals policy",
                    oldest,
                )
                return

    def _update_load_shedding(self, scan_duration: float) -> None:
        self._scan_durations.append(scan_duration)
        if not self.compute_budget_s or len(self._scan_durations) < 2:
            self._load_shed_active = False
            self._scan_duration_p95 = None
            return

        sorted_times = sorted(self._scan_durations)
        p95_index = int(0.95 * (len(sorted_times) - 1))
        self._scan_duration_p95 = sorted_times[p95_index]
        self._load_shed_active = (
            self._scan_duration_p95 > self.compute_budget_s
        )
