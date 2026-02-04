"""
Low-Frequency Oscillation Detection using Correlation

Detects periodic oscillations by correlating signal with reference sinusoids.

Implements:
    corr = Σ x[n] * sin(2π fᵢ n Δt)

For multiple reference frequencies.
"""

from typing import Any, List, Dict, Optional
import numpy as np
from dataclasses import dataclass
from sqe.core.signal_buffer import SignalBuffer


@dataclass
class FrequencyComponent:
    """Detected frequency component."""
    frequency: float        # Frequency in Hz
    magnitude: float        # Correlation magnitude
    phase: float           # Phase offset in radians
    energy: float          # Oscillation energy


class FrequencyDetector:
    """
    Detects low-frequency oscillations using correlation method.

    Correlates signal with sine and cosine reference waveforms
    at specified frequencies to detect periodic components.
    """

    def __init__(
        self,
        reference_frequencies: List[float],
        sample_interval: float,
        window_size: int = 50,
        threshold: float = 0.5
    ):
        """
        Initialize frequency detector.

        Args:
            reference_frequencies: List of frequencies to detect (Hz)
            sample_interval: Time between samples (Δt in seconds)
            window_size: Number of samples for correlation window
            threshold: Correlation threshold for detection
        """
        self.ref_frequencies = reference_frequencies
        self.dt = sample_interval
        self.window_size = window_size
        self.threshold = threshold

        self.buffer = SignalBuffer(window_size)
        self.sample_count = 0
        self._last_sample_count: Optional[int] = None
        self._last_components: Optional[List[FrequencyComponent]] = None
        self._samples = np.empty(window_size, dtype=float)

        # Pre-compute reference waveforms for efficiency
        self._precompute_references()

    def _precompute_references(self) -> None:
        """Pre-compute sine and cosine references for all frequencies."""
        n = np.arange(self.window_size)
        freq_array = np.array(self.ref_frequencies, dtype=float)
        omega = 2 * np.pi * freq_array[:, np.newaxis] * self.dt
        self._sin_refs = np.sin(omega * n)
        self._cos_refs = np.cos(omega * n)
        self._freq_index = {freq: index for index, freq in enumerate(self.ref_frequencies)}

    def update(
        self, x: float, *, compute: bool = True
    ) -> Dict[float, FrequencyComponent]:
        """
        Process new sample and detect frequency components.

        Args:
            x: New signal sample

        Returns:
            Dictionary mapping frequencies to detected components
        """
        self.buffer.push(x)
        self.sample_count += 1

        # Need full window for reliable detection
        if not self.buffer.is_full():
            return {}

        if not compute:
            return {}

        count = self.buffer.fill_samples(self._samples)
        if count < self.window_size:
            return {}

        components = self._get_components(self._samples[:count])
        detected: Dict[float, FrequencyComponent] = {}

        for freq, component in zip(self.ref_frequencies, components):
            if component.magnitude > self.threshold:
                detected[freq] = component

        return detected

    def _get_components(self, samples: np.ndarray) -> List[FrequencyComponent]:
        """Return cached or freshly computed components for current window."""
        if self._last_sample_count == self.sample_count and self._last_components is not None:
            return self._last_components

        components = self._detect_all_frequencies(samples)
        self._last_sample_count = self.sample_count
        self._last_components = components
        return components

    def _detect_all_frequencies(self, samples: np.ndarray) -> List[FrequencyComponent]:
        """
        Detect frequency components using vectorized correlation.

        Args:
            samples: Signal samples

        Returns:
            List of FrequencyComponent in the same order as reference_frequencies
        """
        samples_normalized = samples - np.mean(samples)
        std = np.std(samples_normalized)
        if std > 0:
            samples_normalized = samples_normalized / std

        sin_corr = (self._sin_refs @ samples_normalized) / len(samples)
        cos_corr = (self._cos_refs @ samples_normalized) / len(samples)

        magnitudes = np.sqrt(sin_corr**2 + cos_corr**2)
        phases = np.arctan2(sin_corr, cos_corr)
        energies = magnitudes**2

        components = []
        for freq, magnitude, phase, energy in zip(
            self.ref_frequencies, magnitudes, phases, energies
        ):
            components.append(
                FrequencyComponent(
                    frequency=freq,
                    magnitude=float(magnitude),
                    phase=float(phase),
                    energy=float(energy),
                )
            )
        return components

    def _detect_frequency(
        self,
        samples: np.ndarray,
        freq: float
    ) -> FrequencyComponent:
        """
        Detect specific frequency component using correlation.

        Args:
            samples: Signal samples
            freq: Frequency to detect

        Returns:
            FrequencyComponent with correlation results
        """
        # Normalize samples
        samples_normalized = samples - np.mean(samples)
        if np.std(samples_normalized) > 0:
            samples_normalized /= np.std(samples_normalized)

        # Correlate with sine and cosine references
        freq_index = self._freq_index[freq]
        sin_corr = np.sum(samples_normalized * self._sin_refs[freq_index]) / len(samples)
        cos_corr = np.sum(samples_normalized * self._cos_refs[freq_index]) / len(samples)

        # Calculate magnitude and phase
        magnitude = np.sqrt(sin_corr**2 + cos_corr**2)
        phase = np.arctan2(sin_corr, cos_corr)

        # Energy is magnitude squared
        energy = magnitude**2

        return FrequencyComponent(
            frequency=freq,
            magnitude=float(magnitude),
            phase=float(phase),
            energy=float(energy)
        )

    def get_dominant_frequency(self) -> Optional[FrequencyComponent]:
        """
        Get the dominant (highest magnitude) frequency component.

        Returns:
            Dominant FrequencyComponent or None if none detected
        """
        if not self.buffer.is_full():
            return None

        count = self.buffer.fill_samples(self._samples)
        if count < self.window_size:
            return None
        components = self._get_components(self._samples[:count])

        # Filter by threshold
        detected = [c for c in components if c.magnitude > self.threshold]

        if not detected:
            return None

        # Return component with highest magnitude
        return max(detected, key=lambda c: c.magnitude)

    def get_total_oscillation_energy(self) -> float:
        """
        Calculate total oscillation energy across all frequencies.

        Returns:
            Sum of energy across detected components
        """
        if not self.buffer.is_full():
            return 0.0

        count = self.buffer.fill_samples(self._samples)
        if count < self.window_size:
            return 0.0
        components = self._get_components(self._samples[:count])
        return sum(
            component.energy
            for component in components
            if component.magnitude > self.threshold
        )

    def reset(self) -> None:
        """Reset detector state."""
        self.buffer.clear()
        self.sample_count = 0
        self._last_sample_count = None
        self._last_components = None


class FFTFrequencyAnalyzer:
    """
    FFT-based frequency analysis for more comprehensive spectrum.

    Complements correlation-based detection with full spectrum analysis.
    """

    def __init__(self, window_size: int, sample_interval: float):
        """
        Initialize FFT analyzer.

        Args:
            window_size: FFT window size (power of 2 preferred)
            sample_interval: Time between samples (seconds)
        """
        self.window_size = window_size
        self.dt = sample_interval
        self.buffer = SignalBuffer(window_size)
        self._window = np.hanning(window_size)
        self._frequencies = np.fft.rfftfreq(window_size, self.dt)
        self._samples = np.empty(window_size, dtype=float)
        self._windowed = np.empty(window_size, dtype=float)
        self._last_result: Dict[str, Any] = {
            "frequencies": [],
            "magnitudes": [],
            "peak_frequency": None,
            "peak_magnitude": 0.0,
        }

    def update(self, x: float, *, compute: bool = True) -> Dict:
        """
        Process new sample and compute spectrum.

        Args:
            x: New signal sample

        Returns:
            Dictionary with frequency spectrum information
        """
        self.buffer.push(x)

        if not self.buffer.is_full():
            self._last_result = {
                "frequencies": [],
                "magnitudes": [],
                "peak_frequency": None,
                "peak_magnitude": 0.0,
            }
            return self._last_result

        if not compute:
            return self._last_result

        count = self.buffer.fill_samples(self._samples)
        if count < self.window_size:
            return self._last_result

        # Apply Hanning window to reduce spectral leakage
        self._windowed[:] = self._samples * self._window

        # Compute FFT
        fft = np.fft.rfft(self._windowed)
        magnitudes = np.abs(fft) / self.window_size

        # Frequency bins
        frequencies = self._frequencies

        # Find peak (exclude DC component)
        if len(magnitudes) > 1:
            peak_idx = np.argmax(magnitudes[1:]) + 1
            peak_freq = frequencies[peak_idx]
            peak_mag = magnitudes[peak_idx]
        else:
            peak_freq = None
            peak_mag = 0.0

        self._last_result = {
            "frequencies": frequencies.tolist(),
            "magnitudes": magnitudes.tolist(),
            "peak_frequency": float(peak_freq) if peak_freq else None,
            "peak_magnitude": float(peak_mag)
        }
        return self._last_result

    def reset(self) -> None:
        """Reset analyzer state."""
        self.buffer.clear()


class OscillationDetector:
    """
    Combined oscillation detector using multiple methods.

    Integrates correlation-based and FFT-based detection
    for robust oscillation analysis.
    """

    def __init__(
        self,
        reference_frequencies: List[float],
        sample_interval: float,
        window_size: int = 50,
        enable_fft: bool = True,
    ):
        """
        Initialize combined oscillation detector.

        Args:
            reference_frequencies: Frequencies to detect via correlation
            sample_interval: Time between samples
            window_size: Analysis window size
            enable_fft: Toggle FFT-based spectrum analysis
        """
        self.freq_detector = FrequencyDetector(
            reference_frequencies,
            sample_interval,
            window_size
        )
        self.fft_analyzer = (
            FFTFrequencyAnalyzer(window_size, sample_interval)
            if enable_fft
            else None
        )
        self._update_counter = 0
        self._last_result: Dict[str, Any] = {
            "correlation_components": {},
            "total_oscillation_energy": 0.0,
            "dominant_frequency": None,
            "dominant_magnitude": 0.0,
            "fft_peak_frequency": None,
            "fft_peak_magnitude": 0.0,
        }

    def update(
        self,
        x: float,
        *,
        load_shed: bool = False,
        cadence: int = 1,
        skip_fft: bool = False,
    ) -> Dict:
        """
        Process sample with both detection methods.

        Args:
            x: New signal sample

        Returns:
            Combined oscillation analysis results
        """
        self._update_counter += 1
        cadence = max(cadence, 1)
        should_compute = (self._update_counter % cadence) == 0

        # Correlation-based detection
        components = self.freq_detector.update(
            x,
            compute=not load_shed or should_compute,
        )
        if load_shed and not should_compute:
            if self.fft_analyzer:
                self.fft_analyzer.update(x, compute=False)
            return self._last_result

        total_energy = self.freq_detector.get_total_oscillation_energy()
        dominant = self.freq_detector.get_dominant_frequency()

        # FFT-based analysis
        if self.fft_analyzer:
            if load_shed and skip_fft:
                self.fft_analyzer.update(x, compute=False)
                spectrum = {"peak_frequency": None, "peak_magnitude": 0.0}
            else:
                spectrum = self.fft_analyzer.update(
                    x,
                    compute=not load_shed or should_compute,
                )
        else:
            spectrum = {"peak_frequency": None, "peak_magnitude": 0.0}

        self._last_result = {
            "correlation_components": {
                f: {"magnitude": c.magnitude, "energy": c.energy, "phase": c.phase}
                for f, c in components.items()
            },
            "total_oscillation_energy": total_energy,
            "dominant_frequency": dominant.frequency if dominant else None,
            "dominant_magnitude": dominant.magnitude if dominant else 0.0,
            "fft_peak_frequency": spectrum["peak_frequency"],
            "fft_peak_magnitude": spectrum["peak_magnitude"]
        }
        return self._last_result

    def reset(self) -> None:
        """Reset both detectors."""
        self.freq_detector.reset()
        if self.fft_analyzer:
            self.fft_analyzer.reset()
        self._update_counter = 0
        self._last_result = {
            "correlation_components": {},
            "total_oscillation_energy": 0.0,
            "dominant_frequency": None,
            "dominant_magnitude": 0.0,
            "fft_peak_frequency": None,
            "fft_peak_magnitude": 0.0,
        }
