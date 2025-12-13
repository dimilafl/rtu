"""Tests for signal filters."""

import pytest
import numpy as np

from sqe.core.filters import EWMAFilter, HighPassFilter, MovingAverageFilter, FilterBank


class TestEWMAFilter:
    """Test EWMA (low-pass) filter."""

    def test_initialization(self):
        """Test filter initialization."""
        filt = EWMAFilter(alpha=0.3)
        assert filt.alpha == 0.3
        assert filt.last_output is None

    def test_invalid_alpha(self):
        """Test that invalid alpha values raise error."""
        with pytest.raises(ValueError):
            EWMAFilter(alpha=0.0)
        with pytest.raises(ValueError):
            EWMAFilter(alpha=1.5)

    def test_first_sample(self):
        """Test that first sample initializes filter."""
        filt = EWMAFilter(alpha=0.3)
        result = filt.update(10.0)
        assert result == 10.0

    def test_smoothing(self):
        """Test smoothing behavior."""
        filt = EWMAFilter(alpha=0.3)

        # Feed constant signal
        for _ in range(10):
            result = filt.update(10.0)

        # Should converge to input value
        assert abs(result - 10.0) < 0.01

    def test_step_response(self):
        """Test response to step input."""
        filt = EWMAFilter(alpha=0.5)

        # Step from 0 to 10
        filt.update(0.0)
        result = filt.update(10.0)

        # Should be between 0 and 10
        assert 0 < result < 10

    def test_reset(self):
        """Test filter reset."""
        filt = EWMAFilter(alpha=0.3)
        filt.update(10.0)
        filt.reset()
        assert filt.last_output is None


class TestHighPassFilter:
    """Test high-pass filter."""

    def test_initialization(self):
        """Test filter initialization."""
        filt = HighPassFilter(alpha=0.3)
        assert filt.lowpass.alpha == 0.3

    def test_dc_removal(self):
        """Test that DC component is removed."""
        filt = HighPassFilter(alpha=0.1)

        # Feed constant signal (DC)
        results = []
        for _ in range(20):
            results.append(filt.update(10.0))

        # High-pass output should approach zero for DC
        assert abs(results[-1]) < 1.0

    def test_ac_passthrough(self):
        """Test that AC components pass through."""
        filt = HighPassFilter(alpha=0.3)

        # Feed oscillating signal
        for i in range(10):
            value = 10.0 + 5.0 * np.sin(i * 0.5)
            filt.update(value)

        # Feed another oscillation
        result = filt.update(10.0 + 5.0)

        # Should have non-zero high-pass output
        assert abs(result) > 0.1


class TestMovingAverageFilter:
    """Test moving average filter."""

    def test_initialization(self):
        """Test filter initialization."""
        filt = MovingAverageFilter(window_size=5)
        assert filt.window_size == 5

    def test_invalid_window(self):
        """Test that invalid window size raises error."""
        with pytest.raises(ValueError):
            MovingAverageFilter(window_size=0)

    def test_averaging(self):
        """Test averaging behavior."""
        filt = MovingAverageFilter(window_size=3)

        filt.update(1.0)
        filt.update(2.0)
        result = filt.update(3.0)

        # Average of [1, 2, 3] should be 2
        assert abs(result - 2.0) < 0.01

    def test_sliding_window(self):
        """Test that window slides correctly."""
        filt = MovingAverageFilter(window_size=3)

        for i in range(1, 6):
            result = filt.update(float(i))

        # Last 3 samples: [3, 4, 5], average = 4
        assert abs(result - 4.0) < 0.01

    def test_noise_reduction(self):
        """Test noise smoothing."""
        filt = MovingAverageFilter(window_size=10)

        # Generate noisy signal
        np.random.seed(42)
        signal = 10.0 + np.random.normal(0, 1, 20)

        results = [filt.update(x) for x in signal]

        # Filtered signal should have lower variance
        filtered_var = np.var(results[-10:])
        noise_var = 1.0  # Input noise variance

        assert filtered_var < noise_var


class TestFilterBank:
    """Test filter bank."""

    def test_add_filter(self):
        """Test adding filters to bank."""
        bank = FilterBank()
        bank.add_filter("ewma", EWMAFilter(0.3))
        bank.add_filter("ma", MovingAverageFilter(5))

        assert "ewma" in bank.filters
        assert "ma" in bank.filters

    def test_parallel_processing(self):
        """Test processing sample through multiple filters."""
        bank = FilterBank()
        bank.add_filter("ewma", EWMAFilter(0.5))
        bank.add_filter("ma", MovingAverageFilter(3))

        results = bank.update(10.0)

        assert "ewma" in results
        assert "ma" in results
        assert results["ewma"] == 10.0  # First sample
        assert results["ma"] == 10.0    # First sample

    def test_reset_all(self):
        """Test resetting all filters."""
        bank = FilterBank()
        ewma = EWMAFilter(0.3)
        bank.add_filter("ewma", ewma)

        bank.update(10.0)
        bank.reset()

        assert ewma.last_output is None
