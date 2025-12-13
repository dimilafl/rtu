"""Tests for frequency detection."""

import pytest
import numpy as np

from sqe.core.freq_detect import FrequencyDetector, FFTFrequencyAnalyzer, OscillationDetector


class TestFrequencyDetector:
    """Test correlation-based frequency detector."""

    def test_initialization(self):
        """Test detector initialization."""
        detector = FrequencyDetector(
            reference_frequencies=[0.1, 0.5, 1.0],
            sample_interval=0.1,
            window_size=50
        )
        assert len(detector.ref_frequencies) == 3
        assert detector.dt == 0.1

    def test_insufficient_data(self):
        """Test behavior before window is full."""
        detector = FrequencyDetector(
            reference_frequencies=[1.0],
            sample_interval=0.1,
            window_size=50
        )

        for i in range(30):
            result = detector.update(np.sin(2 * np.pi * 1.0 * i * 0.1))

        # Should return empty until window is full
        assert len(result) == 0

    def test_sine_wave_detection(self):
        """Test detection of pure sine wave."""
        freq = 1.0
        dt = 0.1
        detector = FrequencyDetector(
            reference_frequencies=[freq],
            sample_interval=dt,
            window_size=50,
            threshold=0.3
        )

        # Generate pure sine wave at reference frequency
        for i in range(50):
            value = np.sin(2 * np.pi * freq * i * dt)
            result = detector.update(value)

        # Should detect the frequency
        assert len(result) > 0
        assert freq in result
        assert result[freq].magnitude > 0.3

    def test_multiple_frequency_detection(self):
        """Test detection of multiple frequencies."""
        freqs = [0.5, 1.0]
        dt = 0.1
        detector = FrequencyDetector(
            reference_frequencies=freqs,
            sample_interval=dt,
            window_size=100,
            threshold=0.2
        )

        # Generate signal with both frequencies
        for i in range(100):
            value = (
                np.sin(2 * np.pi * 0.5 * i * dt) +
                np.sin(2 * np.pi * 1.0 * i * dt)
            )
            result = detector.update(value)

        # Should detect both frequencies
        detected_freqs = list(result.keys())
        assert len(detected_freqs) > 0

    def test_dominant_frequency(self):
        """Test dominant frequency detection."""
        detector = FrequencyDetector(
            reference_frequencies=[0.5, 1.0, 2.0],
            sample_interval=0.1,
            window_size=50,
            threshold=0.2
        )

        # Generate signal dominated by 1.0 Hz
        for i in range(50):
            value = 2.0 * np.sin(2 * np.pi * 1.0 * i * 0.1) + \
                    0.5 * np.sin(2 * np.pi * 0.5 * i * 0.1)
            detector.update(value)

        dominant = detector.get_dominant_frequency()

        if dominant:
            # 1.0 Hz should be dominant
            assert dominant.frequency == 1.0

    def test_oscillation_energy(self):
        """Test total oscillation energy calculation."""
        detector = FrequencyDetector(
            reference_frequencies=[1.0],
            sample_interval=0.1,
            window_size=50,
            threshold=0.2
        )

        # Generate signal
        for i in range(50):
            value = np.sin(2 * np.pi * 1.0 * i * 0.1)
            detector.update(value)

        energy = detector.get_total_oscillation_energy()
        assert energy > 0

    def test_reset(self):
        """Test detector reset."""
        detector = FrequencyDetector(
            reference_frequencies=[1.0],
            sample_interval=0.1,
            window_size=50
        )

        for i in range(50):
            detector.update(np.sin(i * 0.1))

        detector.reset()
        assert detector.sample_count == 0


class TestFFTFrequencyAnalyzer:
    """Test FFT-based frequency analyzer."""

    def test_initialization(self):
        """Test analyzer initialization."""
        analyzer = FFTFrequencyAnalyzer(window_size=64, sample_interval=0.1)
        assert analyzer.window_size == 64

    def test_insufficient_data(self):
        """Test behavior before window is full."""
        analyzer = FFTFrequencyAnalyzer(window_size=64, sample_interval=0.1)

        for i in range(30):
            result = analyzer.update(np.sin(i * 0.1))

        assert result["peak_frequency"] is None

    def test_peak_detection(self):
        """Test FFT peak detection."""
        analyzer = FFTFrequencyAnalyzer(window_size=64, sample_interval=0.1)

        # Generate 1 Hz sine wave
        freq = 1.0
        dt = 0.1

        for i in range(64):
            value = np.sin(2 * np.pi * freq * i * dt)
            result = analyzer.update(value)

        # Peak should be near 1 Hz
        if result["peak_frequency"]:
            assert 0.5 < result["peak_frequency"] < 1.5

    def test_spectrum_output(self):
        """Test spectrum output format."""
        analyzer = FFTFrequencyAnalyzer(window_size=32, sample_interval=0.1)

        for i in range(32):
            result = analyzer.update(np.sin(i * 0.1))

        assert "frequencies" in result
        assert "magnitudes" in result
        assert len(result["frequencies"]) > 0


class TestOscillationDetector:
    """Test combined oscillation detector."""

    def test_initialization(self):
        """Test detector initialization."""
        detector = OscillationDetector(
            reference_frequencies=[0.5, 1.0],
            sample_interval=0.1,
            window_size=50
        )
        assert detector.freq_detector is not None
        assert detector.fft_analyzer is not None

    def test_combined_detection(self):
        """Test detection using both methods."""
        detector = OscillationDetector(
            reference_frequencies=[1.0],
            sample_interval=0.1,
            window_size=50
        )

        # Generate oscillating signal
        for i in range(50):
            value = np.sin(2 * np.pi * 1.0 * i * 0.1)
            result = detector.update(value)

        assert "correlation_components" in result
        assert "fft_peak_frequency" in result
        assert "total_oscillation_energy" in result

    def test_reset(self):
        """Test detector reset."""
        detector = OscillationDetector(
            reference_frequencies=[1.0],
            sample_interval=0.1,
            window_size=50
        )

        for i in range(50):
            detector.update(np.sin(i * 0.1))

        detector.reset()
        # After reset, should start fresh
        result = detector.update(0.0)
        assert result["total_oscillation_energy"] == 0.0
