"""Tests for variance calculation and spike detection."""

import pytest
import numpy as np

from sqe.core.variance import VarianceCalculator, WelfordVariance, SpikeDetector


class TestVarianceCalculator:
    """Test variance calculator."""

    def test_initialization(self):
        """Test calculator initialization."""
        calc = VarianceCalculator(window_size=10)
        assert calc.window_size == 10

    def test_invalid_window(self):
        """Test that window size <= 1 raises error."""
        with pytest.raises(ValueError):
            VarianceCalculator(window_size=1)

    def test_insufficient_data(self):
        """Test behavior with insufficient data."""
        calc = VarianceCalculator(window_size=10)
        result = calc.update(10.0)

        assert result["variance"] == 0.0
        assert result["sample_count"] == 1

    def test_constant_signal_zero_variance(self):
        """Test that constant signal has zero variance."""
        calc = VarianceCalculator(window_size=10)

        for _ in range(10):
            result = calc.update(10.0)

        assert result["variance"] < 0.01
        assert result["std_dev"] < 0.01

    def test_variance_calculation(self):
        """Test variance calculation."""
        calc = VarianceCalculator(window_size=5)

        # Known variance: [1, 2, 3, 4, 5]
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for v in values:
            result = calc.update(v)

        # Sample variance of [1,2,3,4,5] = 2.5
        expected_var = 2.5
        assert abs(result["variance"] - expected_var) < 0.01

    def test_noise_level(self):
        """Test noise level (coefficient of variation)."""
        calc = VarianceCalculator(window_size=20)

        # Generate signal with known CV
        np.random.seed(42)
        mean = 10.0
        std = 2.0
        signal = np.random.normal(mean, std, 20)

        for s in signal:
            result = calc.update(s)

        # CV should be approximately std/mean = 0.2
        assert 0.1 < result["noise_level"] < 0.3

    def test_spike_threshold(self):
        """Test spike threshold calculation."""
        calc = VarianceCalculator(window_size=10)

        # Feed samples with mean=10, std=1
        for i in range(10):
            calc.update(10.0 + (i % 2) * 0.5)

        threshold = calc.get_spike_threshold(k=3.0)
        assert threshold is not None
        assert threshold > 10.0

    def test_is_spike(self):
        """Test spike detection."""
        calc = VarianceCalculator(window_size=10)

        # Feed normal samples
        for _ in range(10):
            calc.update(10.0)

        # Test spike
        assert calc.is_spike(20.0, k=3.0) is True
        assert calc.is_spike(10.0, k=3.0) is False


class TestWelfordVariance:
    """Test Welford's online variance algorithm."""

    def test_initialization(self):
        """Test algorithm initialization."""
        welford = WelfordVariance()
        assert welford.count == 0
        assert welford.mean == 0.0

    def test_single_sample(self):
        """Test with single sample."""
        welford = WelfordVariance()
        result = welford.update(10.0)

        assert result["mean"] == 10.0
        assert result["variance"] == 0.0
        assert result["count"] == 1

    def test_mean_calculation(self):
        """Test running mean calculation."""
        welford = WelfordVariance()

        for i in range(1, 6):
            result = welford.update(float(i))

        # Mean of [1,2,3,4,5] = 3
        assert abs(result["mean"] - 3.0) < 0.01

    def test_variance_calculation(self):
        """Test running variance calculation."""
        welford = WelfordVariance()

        for i in range(1, 6):
            result = welford.update(float(i))

        # Variance of [1,2,3,4,5] = 2.5
        assert abs(result["variance"] - 2.5) < 0.01

    def test_reset(self):
        """Test algorithm reset."""
        welford = WelfordVariance()
        welford.update(10.0)
        welford.reset()

        assert welford.count == 0
        assert welford.mean == 0.0


class TestSpikeDetector:
    """Test spike detector."""

    def test_initialization(self):
        """Test detector initialization."""
        detector = SpikeDetector(window_size=20, k_sigma=3.0)
        assert detector.k_sigma == 3.0

    def test_no_spike_normal_signal(self):
        """Test that normal signals don't trigger spikes."""
        detector = SpikeDetector(window_size=20, k_sigma=3.0)

        # Feed normal signal
        for i in range(30):
            result = detector.update(10.0 + np.sin(i * 0.1))

        assert result["spike_count"] == 0
        assert result["is_spike"] is False

    def test_spike_detection(self):
        """Test spike detection."""
        detector = SpikeDetector(window_size=20, k_sigma=3.0)

        # Feed normal samples
        for _ in range(20):
            detector.update(10.0)

        # Inject spike
        result = detector.update(50.0)

        assert result["is_spike"] is True
        assert result["spike_count"] == 1

    def test_spike_frequency(self):
        """Test spike frequency calculation."""
        detector = SpikeDetector(window_size=10, k_sigma=3.0)

        # Feed mostly normal with occasional spikes
        for i in range(100):
            if i % 20 == 0:
                result = detector.update(50.0)  # Spike
            else:
                result = detector.update(10.0)  # Normal

        # Should have 5 spikes in 100 samples = 5% frequency
        assert 0.03 < result["spike_frequency"] < 0.07

    def test_reset(self):
        """Test detector reset."""
        detector = SpikeDetector()
        detector.update(10.0)
        detector.update(50.0)  # Spike

        detector.reset()

        assert detector.spike_count == 0
        assert detector.total_samples == 0
