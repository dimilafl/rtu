"""Tests for Signal Quality Engine."""

import pytest
import numpy as np

from sqe.core.engine import (
    SignalQualityEngine,
    SignalProcessor,
    SignalConfig,
    ProcessedSignal
)


class TestSignalConfig:
    """Test signal configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SignalConfig(signal_id="test")
        assert config.signal_id == "test"
        assert config.ewma_alpha == 0.3
        assert config.reference_frequencies is not None

    def test_custom_config(self):
        """Test custom configuration."""
        config = SignalConfig(
            signal_id="custom",
            ewma_alpha=0.5,
            ma_window=20,
            reference_frequencies=[0.1, 1.0]
        )
        assert config.ewma_alpha == 0.5
        assert config.ma_window == 20
        assert len(config.reference_frequencies) == 2


class TestSignalProcessor:
    """Test signal processor."""

    def test_initialization(self):
        """Test processor initialization."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        assert processor.config.signal_id == "test"
        assert processor.sample_count == 0

    def test_process_valid_sample(self):
        """Test processing valid sample."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        result = processor.update(10.0)

        assert result is not None
        assert isinstance(result, ProcessedSignal)
        assert result.raw == 10.0
        assert result.signal_id == "test"
        assert "noise" in result.sqi_components
        assert "missing" in result.sqi_components
        assert "noise" in result.sqi_weights
        assert "missing" in result.sqi_weights

    def test_process_missing_sample(self):
        """Test processing missing sample."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        result = processor.update(None)

        assert result is None
        assert processor.missing_count == 1

    def test_complete_pipeline(self):
        """Test complete processing pipeline."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        # Process multiple samples
        for i in range(100):
            result = processor.update(10.0 + np.sin(i * 0.1))

        # Check all outputs are present
        assert result.filtered_ewma is not None
        assert result.filtered_ma is not None
        assert result.drift is not None
        assert result.variance >= 0
        assert result.sqi >= 0

    def test_drift_detection_in_pipeline(self):
        """Test that drift is detected in pipeline."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        # Create drift
        for i in range(20):
            result = processor.update(10.0 + i * 0.5)

        assert abs(result.drift) > 0

    def test_spike_detection_in_pipeline(self):
        """Test that spikes are detected in pipeline."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        # Normal samples
        for _ in range(30):
            processor.update(10.0)

        # Spike
        result = processor.update(50.0)

        # Should be detected as spike
        assert result.is_spike or result.spike_frequency > 0

    def test_reset(self):
        """Test processor reset."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        processor.update(10.0)
        processor.reset()

        assert processor.sample_count == 0
        assert processor.missing_count == 0


class TestSignalQualityEngine:
    """Test main engine."""

    def test_initialization(self):
        """Test engine initialization."""
        engine = SignalQualityEngine(scan_interval=0.1)
        assert engine.scan_interval == 0.1
        assert len(engine.processors) == 0

    def test_register_signal(self):
        """Test signal registration."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        assert "sig1" in engine.processors

    def test_register_duplicate_signal(self):
        """Test that duplicate registration raises error."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        with pytest.raises(ValueError):
            engine.register_signal("sig1")

    def test_unregister_signal(self):
        """Test signal unregistration."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.unregister_signal("sig1")

        assert "sig1" not in engine.processors

    def test_update_single_signal(self):
        """Test updating single signal."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        result = engine.update_single("sig1", 10.0)

        assert result is not None
        assert result.signal_id == "sig1"
        assert result.raw == 10.0

    def test_update_multiple_signals(self):
        """Test updating multiple signals."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.register_signal("sig2")

        results = engine.update({
            "sig1": 10.0,
            "sig2": 20.0
        })

        assert len(results) == 2
        assert "sig1" in results
        assert "sig2" in results

    def test_auto_registration(self):
        """Test automatic signal registration."""
        engine = SignalQualityEngine()

        # Update unregistered signal
        result = engine.update_single("new_sig", 10.0)

        # Should auto-register
        assert "new_sig" in engine.processors
        assert result.signal_id == "new_sig"

    def test_get_signal_stats(self):
        """Test getting signal statistics."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        # Process some samples
        for i in range(10):
            engine.update_single("sig1", 10.0 + i)

        stats = engine.get_signal_stats("sig1")

        assert stats["signal_id"] == "sig1"
        assert stats["sample_count"] == 10
        assert "sqi_stats" in stats

    def test_get_all_stats(self):
        """Test getting all signal statistics."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.register_signal("sig2")

        engine.update({"sig1": 10.0, "sig2": 20.0})

        all_stats = engine.get_all_stats()

        assert len(all_stats) == 2
        assert "sig1" in all_stats
        assert "sig2" in all_stats

    def test_reset_signal(self):
        """Test resetting single signal."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        engine.update_single("sig1", 10.0)
        engine.reset_signal("sig1")

        stats = engine.get_signal_stats("sig1")
        assert stats["sample_count"] == 0

    def test_reset_all(self):
        """Test resetting all signals."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.register_signal("sig2")

        engine.update({"sig1": 10.0, "sig2": 20.0})
        engine.reset_all()

        assert engine.scan_count == 0
        stats1 = engine.get_signal_stats("sig1")
        stats2 = engine.get_signal_stats("sig2")

        assert stats1["sample_count"] == 0
        assert stats2["sample_count"] == 0

    def test_get_registered_signals(self):
        """Test getting list of registered signals."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.register_signal("sig2")
        engine.register_signal("sig3")

        signals = engine.get_registered_signals()

        assert len(signals) == 3
        assert "sig1" in signals
        assert "sig2" in signals
        assert "sig3" in signals

    def test_scan_counting(self):
        """Test scan counting."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        for _ in range(5):
            engine.update({"sig1": 10.0})

        assert engine.scan_count == 5

    def test_missing_sample_tracking(self):
        """Test tracking of missing samples."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        # Send some valid and some missing
        engine.update({"sig1": 10.0})
        engine.update({"sig1": None})
        engine.update({"sig1": 10.0})
        engine.update({"sig1": None})

        stats = engine.get_signal_stats("sig1")
        assert stats["missing_count"] == 2
        assert stats["missing_ratio"] == 0.5
