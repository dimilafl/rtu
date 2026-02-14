"""Integration tests for innovation-mode runtime spike scoring in SignalProcessor."""

from __future__ import annotations

import pytest

from sqe.core.engine import SignalConfig, SignalProcessor


def _build_processor() -> SignalProcessor:
    config = SignalConfig(
        signal_id="sig_1",
        innovation_enabled=True,
        innovation_beta=0.05,
        innovation_z_spike=6.0,
        innovation_r=1.0,
        innovation_q=0.0,
        innovation_p0_var=1.0e6,
        innovation_v0_var=1.0e4,
        sample_interval=1.0,
    )
    return SignalProcessor(config)


def test_innovation_mode_spike_threshold_and_ewma_are_deterministic():
    processor_a = _build_processor()

    outputs_a = []
    for ts in range(10):
        outputs_a.append(processor_a.update(0.0, timestamp=float(ts)))
    spike_a = processor_a.update(10.0, timestamp=10.0)

    assert spike_a is not None
    assert spike_a.is_spike is True
    assert spike_a.spike_frequency == pytest.approx(0.05)

    processor_b = _build_processor()
    outputs_b = []
    for ts in range(10):
        outputs_b.append(processor_b.update(0.0, timestamp=float(ts)))
    spike_b = processor_b.update(10.0, timestamp=10.0)

    assert outputs_a == outputs_b
    assert spike_b is not None
    assert spike_a == spike_b


def test_missing_sample_does_not_decay_innovation_spike_ema():
    processor = _build_processor()

    for ts in range(10):
        processor.update(0.0, timestamp=float(ts))
    spike = processor.update(10.0, timestamp=10.0)
    assert spike is not None
    assert spike.spike_frequency == pytest.approx(0.05)

    missing = processor.update(None, timestamp=11.0)
    assert missing is None
    assert processor._innovation_spike_ema == pytest.approx(0.05)

    after = processor.update(0.0, timestamp=12.0)
    assert after is not None
    assert after.spike_frequency == pytest.approx((1.0 - 0.05) * 0.05)


def test_timestamp_regression_uses_zero_dt_without_rewinding_internal_time():
    processor = _build_processor()

    processor.update(0.0, timestamp=0.0)
    processor.update(0.0, timestamp=1.0)
    last_t_before_regression = processor._innovation_last_t

    regressed = processor.update(0.0, timestamp=0.5)
    assert regressed is not None
    assert processor._innovation_last_t == last_t_before_regression

    advanced = processor.update(0.0, timestamp=2.0)
    assert advanced is not None
    assert processor._innovation_last_t == pytest.approx(2.0)
