"""
Signal Quality Engine - Main processing engine.

Integrates all DSP components into a unified signal processing pipeline.
Designed for deterministic, real-time operation within PLC scan cycles.
"""

from typing import Dict, Optional, List, Any, Union
from dataclasses import dataclass, asdict
import time

from sqe.core.filters import EWMAFilter, HighPassFilter, MovingAverageFilter
from sqe.core.drift import DriftDetector, DriftEvent
from sqe.core.variance import VarianceCalculator, SpikeDetector
from sqe.core.freq_detect import OscillationDetector
from sqe.core.sqi import SignalQualityIndex, SQIWeights
from sqe.config.loader import normalize_config, SQEConfig


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
    sustained_drift_window: int = 10
    monotonic_drift_window: int = 5

    # Variance parameters
    variance_window: int = 20
    spike_k_sigma: float = 3.0
    spike_debounce_samples: int = 2

    # Frequency parameters
    reference_frequencies: List[float] = None
    sample_interval: float = 0.1
    freq_window: int = 50
    freq_threshold: float = 0.5
    freq_use_fft: bool = True

    # SQI parameters
    sqi_weights: Optional[Dict[str, float]] = None
    sqi_thresholds: Optional[Dict[str, float]] = None

    def __post_init__(self):
        """Set default reference frequencies if not provided."""
        if self.reference_frequencies is None:
            # Default frequencies: 0.1 Hz, 0.5 Hz, 1 Hz
            self.reference_frequencies = [0.1, 0.5, 1.0]

    @classmethod
    def from_config(
        cls,
        signal_id: str,
        config: Optional[Union[Dict[str, Any], SQEConfig]] = None,
        *,
        overrides: Optional[Dict[str, Any]] = None,
        sample_interval: Optional[float] = None
    ) -> "SignalConfig":
        """Build a SignalConfig from a global config and optional overrides."""
        config_data = normalize_config(config)
        filters = config_data.get("filters", {})
        drift = config_data.get("drift", {})
        variance = config_data.get("variance", {})
        frequency = config_data.get("frequency", {})
        sqi = config_data.get("sqi", {})

        base = {
            "ewma_alpha": filters.get("default_ewma_alpha", 0.3),
            "ma_window": filters.get("default_ma_window", 10),
            "small_drift_threshold": drift.get("small_threshold", 0.5),
            "large_drift_threshold": drift.get("large_threshold", 5.0),
            "sustained_drift_window": drift.get("sustained_window", 10),
            "monotonic_drift_window": drift.get("monotonic_window", 5),
            "variance_window": variance.get("default_window", 20),
            "spike_k_sigma": variance.get("spike_k_sigma", 3.0),
            "spike_debounce_samples": variance.get("debounce_samples", 2),
            "reference_frequencies": frequency.get("default_references", [0.1, 0.5, 1.0]),
            "sample_interval": sample_interval or config_data.get("engine", {}).get("scan_interval", 0.1),
            "freq_window": frequency.get("window_size", 50),
            "freq_threshold": frequency.get("threshold", 0.5),
            "freq_use_fft": frequency.get("use_fft", True),
            "sqi_weights": sqi.get("weights"),
            "sqi_thresholds": sqi.get("thresholds"),
        }

        if overrides:
            base.update(overrides)

        return cls(signal_id=signal_id, **base)


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
            large_drift_threshold=config.large_drift_threshold,
            sustained_window=config.sustained_drift_window,
            monotonic_window=config.monotonic_drift_window
        )

        # Initialize variance and spike detection
        self.variance_calc = VarianceCalculator(config.variance_window)
        self.spike_detector = SpikeDetector(
            window_size=config.variance_window,
            k_sigma=config.spike_k_sigma,
            debounce_samples=config.spike_debounce_samples
        )

        # Initialize frequency detection
        self.osc_detector = OscillationDetector(
            reference_frequencies=config.reference_frequencies,
            sample_interval=config.sample_interval,
            window_size=config.freq_window,
            threshold=config.freq_threshold,
            use_fft=config.freq_use_fft
        )

        # Initialize SQI calculator
        sqi_weights = None
        if config.sqi_weights:
            sqi_weights = SQIWeights(**config.sqi_weights)
        sqi_thresholds = config.sqi_thresholds or {}
        self.sqi_calc = SignalQualityIndex(
            weights=sqi_weights,
            noise_threshold=sqi_thresholds.get("noise", 0.1),
            drift_threshold=sqi_thresholds.get("drift", 1.0),
            spike_threshold=sqi_thresholds.get("spike_frequency", 0.05),
            oscillation_threshold=sqi_thresholds.get("oscillation", 0.3)
        )

        # Track missing samples
        self.missing_count = 0

    def update(self, x: Optional[float]) -> Optional[ProcessedSignal]:
        """
        Process new sample through complete pipeline.

        Args:
            x: Raw signal value (None if missing)

        Returns:
            ProcessedSignal with all analysis results, or None if sample is missing
        """
        self.sample_count += 1

        # Handle missing sample
        if x is None:
            self.missing_count += 1
            return None

        timestamp = time.time()

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

        # Calculate SQI
        missing_ratio = self.missing_count / self.sample_count
        sqi_result = self.sqi_calc.calculate(
            noise_level=variance_result["noise_level"],
            drift_rate=abs(drift_event.drift_rate),
            spike_frequency=spike_result["spike_frequency"],
            oscillation_energy=freq_result["total_oscillation_energy"],
            missing_ratio=missing_ratio
        )

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
            sqi_trend=sqi_result["trend"]
        )

    def reset(self) -> None:
        """Reset all processor state."""
        self.sample_count = 0
        self.missing_count = 0
        self.ewma_filter.reset()
        self.ma_filter.reset()
        self.hp_filter.reset()
        self.drift_detector.reset()
        self.variance_calc.reset()
        self.spike_detector.reset()
        self.osc_detector.reset()
        self.sqi_calc.reset()


class SignalQualityEngine:
    """
    Main Signal Quality Engine.

    Manages multiple signal processors and provides unified interface
    for signal registration and processing.
    """

    def __init__(
        self,
        scan_interval: Optional[float] = None,
        config: Optional[Union[Dict[str, Any], SQEConfig]] = None
    ):
        """
        Initialize Signal Quality Engine.

        Args:
            scan_interval: Expected time between scans (seconds)
            config: Configuration dictionary or SQEConfig
        """
        self.config = normalize_config(config)
        if scan_interval is None:
            scan_interval = self.config.get("engine", {}).get("scan_interval", 0.1)
        else:
            self.config.setdefault("engine", {})["scan_interval"] = scan_interval
        self.scan_interval = scan_interval
        self.processors: Dict[str, SignalProcessor] = {}
        self.scan_count = 0
        self.last_scan_time: Optional[float] = None

    def register_signal(
        self,
        signal_id: str,
        config: Optional[Union[SignalConfig, Dict[str, Any], SQEConfig]] = None
    ) -> None:
        """
        Register a new signal for processing.

        Args:
            signal_id: Unique identifier for signal
            config: Signal configuration (uses defaults if None)
        """
        if signal_id in self.processors:
            raise ValueError(f"Signal {signal_id} already registered")

        if isinstance(config, SignalConfig):
            resolved_config = config
        else:
            overrides = None
            base_config = self.config
            if config is not None:
                if isinstance(config, SQEConfig):
                    base_config = config
                elif isinstance(config, dict):
                    is_global = any(
                        key in config
                        for key in ("engine", "filters", "drift", "variance", "frequency", "sqi")
                    )
                    if is_global:
                        base_config = config
                    else:
                        overrides = config
                else:
                    raise TypeError("Config must be a SignalConfig, dict, or SQEConfig")

            resolved_config = SignalConfig.from_config(
                signal_id=signal_id,
                config=base_config,
                overrides=overrides,
                sample_interval=self.scan_interval
            )

        self.processors[signal_id] = SignalProcessor(resolved_config)

    def unregister_signal(self, signal_id: str) -> None:
        """
        Remove a signal from processing.

        Args:
            signal_id: Signal to remove
        """
        if signal_id in self.processors:
            del self.processors[signal_id]

    def update(self, signals: Dict[str, Optional[float]]) -> Dict[str, ProcessedSignal]:
        """
        Process one scan cycle for all signals.

        Args:
            signals: Dictionary mapping signal_id to raw value (None if missing)

        Returns:
            Dictionary mapping signal_id to ProcessedSignal
        """
        self.scan_count += 1
        current_time = time.time()

        # Track scan timing
        if self.last_scan_time is not None:
            actual_interval = current_time - self.last_scan_time
            # Could log warning if actual_interval deviates significantly

        self.last_scan_time = current_time

        results = {}

        for signal_id, value in signals.items():
            if signal_id not in self.processors:
                # Auto-register unknown signals
                self.register_signal(signal_id)

            processed = self.processors[signal_id].update(value)
            if processed is not None:
                results[signal_id] = processed

        return results

    def update_single(self, signal_id: str, value: Optional[float]) -> Optional[ProcessedSignal]:
        """
        Process single signal update.

        Args:
            signal_id: Signal identifier
            value: Raw signal value

        Returns:
            ProcessedSignal or None if missing
        """
        if signal_id not in self.processors:
            self.register_signal(signal_id)

        return self.processors[signal_id].update(value)

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
            "missing_ratio": processor.missing_count / processor.sample_count if processor.sample_count > 0 else 0,
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
