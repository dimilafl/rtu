"""Tests for Signal Quality Engine."""

import pytest
import numpy as np

from sqe.core.engine import (
    SignalQualityEngine,
    SignalProcessor,
    SignalConfig,
    ProcessedSignal,
)
from sqe.core.sample import Sample


class TestSignalConfig:
    """Test signal configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SignalConfig(signal_id="test")
        assert config.signal_id == "test"
        assert config.ewma_alpha == 0.3
        assert config.reference_frequencies == []
        assert config.enable_fft is False

    def test_custom_config(self):
        """Test custom configuration."""
        config = SignalConfig(
            signal_id="custom",
            ewma_alpha=0.5,
            ma_window=20,
            reference_frequencies=[0.1, 1.0],
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

        result = processor.update(10.0, timestamp=1.0)

        assert result is not None
        assert isinstance(result, ProcessedSignal)
        assert result.raw == 10.0
        assert result.signal_id == "test"
        assert "noise" in result.sqi_components
        assert "missing" in result.sqi_components
        assert "noise" in result.sqi_weights
        assert "missing" in result.sqi_weights

    def test_timestamp_passthrough(self):
        """Test passing explicit timestamp into processor."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        result = processor.update(10.0, timestamp=123.45)

        assert result.timestamp == 123.45

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
            result = processor.update(
                10.0 + np.sin(i * 0.1),
                timestamp=float(i),
            )

        # Check all outputs are present
        assert result.filtered_ewma is not None
        assert result.filtered_ma is not None
        assert result.drift is not None
        assert result.variance >= 0
        assert result.sqi >= 0

    def test_alert_thresholds(self):
        """Test alert threshold evaluation."""
        config = SignalConfig(
            signal_id="test",
            sqi_critical_threshold=100.0,
            sqi_warning_threshold=100.0,
            drift_alert_threshold=0.0,
            spike_alert_threshold=0.0,
        )
        processor = SignalProcessor(config)

        result = processor.update(10.0, timestamp=1.0)

        assert result.alert_level == "critical"
        assert result.drift_alert is True
        assert result.spike_alert is True

    def test_drift_detection_in_pipeline(self):
        """Test that drift is detected in pipeline."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        # Create drift
        for i in range(20):
            result = processor.update(10.0 + i * 0.5, timestamp=float(i))

        assert abs(result.drift) > 0

    def test_spike_detection_in_pipeline(self):
        """Test that spikes are detected in pipeline."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        # Normal samples
        for index in range(30):
            processor.update(10.0, timestamp=float(index))

        # Spike
        result = processor.update(50.0, timestamp=30.0)

        # Should be detected as spike
        assert result.is_spike or result.spike_frequency > 0

    def test_reset(self):
        """Test processor reset."""
        config = SignalConfig(signal_id="test")
        processor = SignalProcessor(config)

        processor.update(10.0, timestamp=1.0)
        processor.reset()

        assert processor.sample_count == 0
        assert processor.missing_count == 0


class TestSignalQualityEngine:
    """Test main engine."""

    def test_initialization(self):
        """Test engine initialization."""
        engine = SignalQualityEngine(scan_interval=0.1)
        assert engine.scan_interval == 0.1
        assert engine.auto_register is True
        assert engine.max_signals is None
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

    def test_register_signal_id_mismatch(self):
        """Test mismatched signal IDs raise error."""
        engine = SignalQualityEngine()
        config = SignalConfig(signal_id="sig2")

        with pytest.raises(ValueError):
            engine.register_signal("sig1", config)

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

        result = engine.update_single("sig1", 10.0, timestamp=1.0)

        assert result is not None
        assert result.signal_id == "sig1"
        assert result.raw == 10.0

    def test_update_multiple_signals(self):
        """Test updating multiple signals."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.register_signal("sig2")

        results = engine.update({"sig1": 10.0, "sig2": 20.0}, timestamp=1.0)

        assert len(results) == 2
        assert "sig1" in results
        assert "sig2" in results

    def test_update_samples_scan_count_and_baseline_cache(self):
        """Ensure update_samples increments scan_count and resets cache per scan."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.register_signal("sig2")

        cache_ids = []
        for processor in engine.processors.values():
            original_update = processor.spike_detector.update

            def wrapped_update(
                x,
                *,
                signal_id=None,
                baseline_stats_cache=None,
                _orig=original_update,
            ):
                cache_ids.append(id(baseline_stats_cache))
                return _orig(
                    x,
                    signal_id=signal_id,
                    baseline_stats_cache=baseline_stats_cache,
                )

            processor.spike_detector.update = wrapped_update

        samples = {
            "sig1": Sample(value=10.0),
            "sig2": Sample(value=12.0),
        }

        engine.update_samples(samples, timestamp=1.0)
        assert engine.scan_count == 1
        assert len(cache_ids) == 2
        first_scan_ids = set(cache_ids)
        assert len(first_scan_ids) == 1

        engine.update_samples(samples, timestamp=2.0)
        assert engine.scan_count == 2
        assert len(cache_ids) == 4
        second_scan_ids = set(cache_ids[2:])
        assert len(second_scan_ids) == 1
        assert first_scan_ids.isdisjoint(second_scan_ids)

    def test_auto_registration(self):
        """Test automatic signal registration."""
        engine = SignalQualityEngine()

        # Update unregistered signal
        result = engine.update_single("new_sig", 10.0, timestamp=1.0)

        # Should auto-register
        assert "new_sig" in engine.processors
        assert result.signal_id == "new_sig"

    def test_auto_registration_disabled(self):
        """Test that auto-registration can be disabled."""
        engine = SignalQualityEngine(auto_register=False)

        with pytest.raises(ValueError):
            engine.update_single("new_sig", 10.0, timestamp=1.0)

    def test_max_signal_limit(self):
        """Test that max signal limit is enforced."""
        engine = SignalQualityEngine(max_signals=1)
        engine.register_signal("sig1")

        with pytest.raises(ValueError):
            engine.register_signal("sig2")

        with pytest.raises(ValueError):
            engine.update_single("sig2", 10.0, timestamp=1.0)

    def test_get_signal_stats(self):
        """Test getting signal statistics."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        # Process some samples
        for i in range(10):
            engine.update_single("sig1", 10.0 + i, timestamp=float(i))

        stats = engine.get_signal_stats("sig1")

        assert stats["signal_id"] == "sig1"
        assert stats["sample_count"] == 10
        assert "sqi_stats" in stats

    def test_get_all_stats(self):
        """Test getting all signal statistics."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.register_signal("sig2")

        engine.update({"sig1": 10.0, "sig2": 20.0}, timestamp=1.0)

        all_stats = engine.get_all_stats()

        assert len(all_stats) == 2
        assert "sig1" in all_stats
        assert "sig2" in all_stats

    def test_reset_signal(self):
        """Test resetting single signal."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        engine.update_single("sig1", 10.0, timestamp=1.0)
        engine.reset_signal("sig1")

        stats = engine.get_signal_stats("sig1")
        assert stats["sample_count"] == 0

    def test_reset_all(self):
        """Test resetting all signals."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.register_signal("sig2")

        engine.update({"sig1": 10.0, "sig2": 20.0}, timestamp=1.0)
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

        for index in range(5):
            engine.update({"sig1": 10.0}, timestamp=float(index))

        assert engine.scan_count == 5

    def test_update_single_increments_scan_count(self):
        """Test update_single increments scan count."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        for index in range(3):
            engine.update_single("sig1", 10.0, timestamp=float(index))

        assert engine.scan_count == 3

    def test_missing_sample_tracking(self):
        """Test tracking of missing samples."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        # Send some valid and some missing
        engine.update({"sig1": 10.0}, timestamp=1.0)
        engine.update({"sig1": None}, timestamp=2.0)
        engine.update({"sig1": 10.0}, timestamp=3.0)
        engine.update({"sig1": None}, timestamp=4.0)

        stats = engine.get_signal_stats("sig1")
        assert stats["missing_count"] == 2
        assert stats["missing_ratio"] == 0.5

    def test_missing_registered_signal_in_scan(self):
        """Test missing registered signals are tracked when omitted."""
        engine = SignalQualityEngine()
        engine.register_signal("sig1")
        engine.register_signal("sig2")

        engine.update({"sig1": 10.0}, timestamp=1.0)

        stats1 = engine.get_signal_stats("sig1")
        stats2 = engine.get_signal_stats("sig2")

        assert stats1["missing_count"] == 0
        assert stats1["missing_ratio"] == 0.0
        assert stats2["missing_count"] == 1
        assert stats2["missing_ratio"] == 1.0

    def test_deterministic_output_with_explicit_timestamps(self):
        """Ensure repeated runs with same timestamps are deterministic."""

        def run_sequence():
            engine = SignalQualityEngine()
            engine.register_signal("sig1")
            outputs = []
            values = [1.0, 2.0, 1.5, 2.5]
            for index, value in enumerate(values, start=1):
                result = engine.update(
                    {"sig1": value},
                    timestamp=float(index),
                )
                outputs.append(result["sig1"].to_dict())
            return outputs

        assert run_sequence() == run_sequence()

    def test_injected_clock_used_when_timestamp_missing(self):
        """Ensure engine clock is used when scan timestamp is omitted."""
        timestamps = iter([10.0, 20.0])
        engine = SignalQualityEngine(clock=lambda: next(timestamps))
        engine.register_signal("sig1")

        first = engine.update({"sig1": 1.0})["sig1"]
        second = engine.update({"sig1": 2.0})["sig1"]

        assert first.timestamp == 10.0
        assert second.timestamp == 20.0

    def test_registration_order_is_preserved(self):
        """Ensure processing order follows registration order."""
        engine = SignalQualityEngine()
        for signal_id in ["b", "a", "c"]:
            engine.register_signal(signal_id)

        results = engine.update(
            {"a": 1.0, "b": 2.0, "c": 3.0},
            timestamp=1.0,
        )

        assert list(results.keys()) == ["b", "a", "c"]

    def test_unknown_id_policy_does_not_reorder_registered(self):
        """Ensure unknown IDs are handled without reordering registered signals."""
        engine = SignalQualityEngine()
        engine.register_signal("b")
        engine.register_signal("a")

        results = engine.update(
            {"a": 1.0, "b": 2.0, "c": 3.0},
            timestamp=1.0,
        )

        assert list(results.keys()) == ["b", "a", "c"]
        assert "c" in engine.processors

        engine = SignalQualityEngine(
            auto_register=False,
            unknown_signal_policy="ignore",
        )
        engine.register_signal("b")
        engine.register_signal("a")

        results = engine.update(
            {"a": 1.0, "b": 2.0, "c": 3.0},
            timestamp=1.0,
        )

        assert list(results.keys()) == ["b", "a"]
        assert "c" not in engine.processors

    def test_fft_disabled_by_default(self, monkeypatch):
        """Ensure FFT is not invoked with default configuration."""

        def _raise_fft(*_args, **_kwargs):
            raise RuntimeError("FFT should be disabled by default")

        monkeypatch.setattr(np.fft, "rfft", _raise_fft)

        engine = SignalQualityEngine()
        engine.register_signal("sig1")

        for index in range(60):
            engine.update({"sig1": 1.0}, timestamp=float(index))

        last = engine.processors["sig1"].osc_detector._last_result
        assert last["fft_peak_frequency"] is None
        assert last["fft_peak_magnitude"] == 0.0
