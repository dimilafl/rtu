"""
Low-Frequency Oscillation Detection using Correlation

Detects periodic oscillations by correlating signal with reference sinusoids.

Implements:
    corr = Σ x[n] * sin(2π fᵢ n Δt)

For multiple reference frequencies.
"""

from typing import List, Dict, Optional
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

        # Pre-compute reference waveforms for efficiency
        self._precompute_references()

    def _precompute_references(self) -> None:
        """Pre-compute sine and cosine references for all frequencies."""
        self.sin_refs = {}
        self.cos_refs = {}

        n = np.arange(self.window_size)

        for freq in self.ref_frequencies:
            # Generate reference waveforms
            omega = 2 * np.pi * freq * self.dt
            self.sin_refs[freq] = np.sin(omega * n)
            self.cos_refs[freq] = np.cos(omega * n)

    def update(self, x: float) -> Dict[float, FrequencyComponent]:
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

        samples = self.buffer.get_samples()
        detected = {}

        for freq in self.ref_frequencies:
            component = self._detect_frequency(samples, freq)

            if component.magnitude > self.threshold:
                detected[freq] = component

        return detected

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
        sin_corr = np.sum(samples_normalized * self.sin_refs[freq]) / len(samples)
        cos_corr = np.sum(samples_normalized * self.cos_refs[freq]) / len(samples)

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

        samples = self.buffer.get_samples()
        components = [
            self._detect_frequency(samples, freq)
            for freq in self.ref_frequencies
        ]

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

        samples = self.buffer.get_samples()
        total_energy = 0.0

        for freq in self.ref_frequencies:
            component = self._detect_frequency(samples, freq)
            if component.magnitude > self.threshold:
                total_energy += component.energy

        return total_energy

    def reset(self) -> None:
        """Reset detector state."""
        self.buffer.clear()
        self.sample_count = 0


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

    def update(self, x: float) -> Dict:
        """
        Process new sample and compute spectrum.

        Args:
            x: New signal sample

        Returns:
            Dictionary with frequency spectrum information
        """
        self.buffer.push(x)

        if not self.buffer.is_full():
            return {
                "frequencies": [],
                "magnitudes": [],
                "peak_frequency": None,
                "peak_magnitude": 0.0
            }

        samples = self.buffer.get_samples()

        # Apply Hanning window to reduce spectral leakage
        windowed = samples * np.hanning(len(samples))

        # Compute FFT
        fft = np.fft.rfft(windowed)
        magnitudes = np.abs(fft) / len(samples)

        # Frequency bins
        frequencies = np.fft.rfftfreq(len(samples), self.dt)

        # Find peak (exclude DC component)
        if len(magnitudes) > 1:
            peak_idx = np.argmax(magnitudes[1:]) + 1
            peak_freq = frequencies[peak_idx]
            peak_mag = magnitudes[peak_idx]
        else:
            peak_freq = None
            peak_mag = 0.0

        return {
            "frequencies": frequencies.tolist(),
            "magnitudes": magnitudes.tolist(),
            "peak_frequency": float(peak_freq) if peak_freq else None,
            "peak_magnitude": float(peak_mag)
        }

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
        window_size: int = 50
    ):
        """
        Initialize combined oscillation detector.

        Args:
            reference_frequencies: Frequencies to detect via correlation
            sample_interval: Time between samples
            window_size: Analysis window size
        """
        self.freq_detector = FrequencyDetector(
            reference_frequencies,
            sample_interval,
            window_size
        )
        self.fft_analyzer = FFTFrequencyAnalyzer(window_size, sample_interval)

    def update(self, x: float) -> Dict:
        """
        Process sample with both detection methods.

        Args:
            x: New signal sample

        Returns:
            Combined oscillation analysis results
        """
        # Correlation-based detection
        components = self.freq_detector.update(x)
        total_energy = self.freq_detector.get_total_oscillation_energy()
        dominant = self.freq_detector.get_dominant_frequency()

        # FFT-based analysis
        spectrum = self.fft_analyzer.update(x)

        return {
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

    def reset(self) -> None:
        """Reset both detectors."""
        self.freq_detector.reset()
        self.fft_analyzer.reset()
