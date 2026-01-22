"""Tests for Signal Quality Index."""

import pytest
import numpy as np

from sqe.core.sqi import SignalQualityIndex, SQIWeights, SQIComponents


class TestSQIWeights:
    """Test SQI weights configuration."""

    def test_default_weights(self):
        """Test default weight values."""
        weights = SQIWeights()
        assert weights.noise == 0.25
        assert weights.drift == 0.25

    def test_normalize(self):
        """Test weight normalization."""
        weights = SQIWeights(
            noise=1.0,
            drift=1.0,
            spikes=1.0,
            oscillation=1.0,
            missing=1.0
        )
        normalized = weights.normalize()

        # Sum should be 1.0
        total = (normalized.noise + normalized.drift +
                normalized.spikes + normalized.oscillation +
                normalized.missing)
        assert abs(total - 1.0) < 0.01

    def test_normalize_zero_total_raises(self):
        """Test that zero-total weights raise an error."""
        weights = SQIWeights(
            noise=0.0,
            drift=0.0,
            spikes=0.0,
            oscillation=0.0,
            missing=0.0
        )

        with pytest.raises(ValueError, match="weights must sum to a positive value"):
            weights.normalize()


class TestSignalQualityIndex:
    """Test SQI calculator."""

    def test_initialization(self):
        """Test SQI initialization."""
        sqi = SignalQualityIndex()
        assert sqi.sample_count == 0
        assert len(sqi.sqi_history) == 0

    @pytest.mark.parametrize(
        ("kwargs", "expected_message"),
        [
            ({"noise_threshold": 0}, "noise_threshold=0"),
            ({"drift_threshold": -1.0}, "drift_threshold=-1.0"),
        ],
    )
    def test_invalid_thresholds_raise(self, kwargs, expected_message):
        """Test invalid thresholds raise with details."""
        with pytest.raises(ValueError, match=expected_message):
            SignalQualityIndex(**kwargs)

    def test_multiple_invalid_thresholds_reported(self):
        """Test multiple invalid thresholds are listed."""
        with pytest.raises(
            ValueError,
            match=r"noise_threshold=0.*spike_threshold=-0.1",
        ):
            SignalQualityIndex(noise_threshold=0, spike_threshold=-0.1)

    def test_perfect_quality(self):
        """Test perfect signal quality (all zeros)."""
        sqi = SignalQualityIndex()

        result = sqi.calculate(
            noise_level=0.0,
            drift_rate=0.0,
            spike_frequency=0.0,
            oscillation_energy=0.0,
            missing_ratio=0.0
        )

        # Perfect signal should score 100
        assert result["sqi"] == 100.0
        assert result["quality_class"] == "excellent"

    def test_poor_quality(self):
        """Test poor signal quality."""
        sqi = SignalQualityIndex()

        result = sqi.calculate(
            noise_level=1.0,      # High noise
            drift_rate=5.0,       # High drift
            spike_frequency=0.5,  # Many spikes
            oscillation_energy=1.0,  # High oscillation
            missing_ratio=0.5     # 50% missing
        )

        # Poor signal should score low
        assert result["sqi"] < 50.0
        assert result["quality_class"] in ["poor", "critical"]

    def test_component_breakdown(self):
        """Test that components are returned."""
        sqi = SignalQualityIndex()

        result = sqi.calculate(
            noise_level=0.1,
            drift_rate=0.5,
            spike_frequency=0.01,
            oscillation_energy=0.1,
            missing_ratio=0.0
        )

        assert "components" in result
        assert "noise" in result["components"]
        assert "drift" in result["components"]
        assert "spikes" in result["components"]

    def test_quality_classification(self):
        """Test quality classification thresholds."""
        sqi = SignalQualityIndex()

        # Test excellent (>= 90)
        result = sqi.calculate(0.0, 0.0, 0.0, 0.0, 0.0)
        assert result["quality_class"] == "excellent"

        # Test good (>= 75)
        result = sqi.calculate(0.05, 0.2, 0.01, 0.1, 0.0)
        assert result["quality_class"] in ["excellent", "good"]

        # Test poor/critical (< 50)
        result = sqi.calculate(1.0, 5.0, 0.5, 1.0, 0.5)
        assert result["quality_class"] in ["poor", "critical"]

    def test_trend_calculation(self):
        """Test SQI trend detection."""
        sqi = SignalQualityIndex()

        # Generate improving trend
        for i in range(15):
            quality = 50 + i * 3  # Improving from 50 to ~90
            # Convert quality back to approximate inputs
            sqi.calculate(
                noise_level=0.1 * (1 - i/15),
                drift_rate=0.5 * (1 - i/15),
                spike_frequency=0.01,
                oscillation_energy=0.1,
                missing_ratio=0.0
            )

        result = sqi.calculate(0.01, 0.01, 0.0, 0.0, 0.0)
        assert result["trend"] == "improving"

    def test_statistics(self):
        """Test SQI statistics."""
        sqi = SignalQualityIndex()

        # Generate some scores
        for _ in range(10):
            sqi.calculate(0.1, 0.5, 0.01, 0.1, 0.0)

        stats = sqi.get_statistics()

        assert "mean_sqi" in stats
        assert "min_sqi" in stats
        assert "max_sqi" in stats
        assert "current_sqi" in stats
        assert stats["mean_sqi"] > 0

    def test_history_limit(self):
        """Test that history is limited."""
        sqi = SignalQualityIndex()

        # Generate more than 100 scores
        for _ in range(150):
            sqi.calculate(0.1, 0.5, 0.01, 0.1, 0.0)

        # Should keep only last 100
        assert len(sqi.sqi_history) == 100

    def test_reset(self):
        """Test SQI reset."""
        sqi = SignalQualityIndex()
        sqi.calculate(0.1, 0.5, 0.01, 0.1, 0.0)
        sqi.reset()

        assert sqi.sample_count == 0
        assert len(sqi.sqi_history) == 0

    def test_custom_weights(self):
        """Test custom weight configuration."""
        weights = SQIWeights(
            noise=0.5,
            drift=0.3,
            spikes=0.1,
            oscillation=0.05,
            missing=0.05
        )
        sqi = SignalQualityIndex(weights=weights)

        result = sqi.calculate(
            noise_level=1.0,  # Should have high impact
            drift_rate=0.0,
            spike_frequency=0.0,
            oscillation_energy=0.0,
            missing_ratio=0.0
        )

        # Noise should dominate the score
        assert result["sqi"] < 80.0

    def test_sqi_range(self):
        """Test that SQI is always in [0, 100] range."""
        sqi = SignalQualityIndex()

        # Test extreme values
        result = sqi.calculate(
            noise_level=1000.0,
            drift_rate=1000.0,
            spike_frequency=1.0,
            oscillation_energy=1000.0,
            missing_ratio=1.0
        )

        assert 0 <= result["sqi"] <= 100
