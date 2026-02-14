"""Tests for innovation-mode noise scoring from normalized residual energy."""

from __future__ import annotations

import math

from sqe.core.engine import SignalConfig, SignalProcessor


def _processor() -> SignalProcessor:
    return SignalProcessor(
        SignalConfig(
            signal_id="sig_1",
            innovation_enabled=True,
            innovation_r=1.0,
            innovation_beta=0.05,
            innovation_q=0.0,
            innovation_p0_var=1.0e6,
            innovation_v0_var=1.0e4,
            innovation_z_spike=6.0,
            innovation_noise_threshold=1.0,
            sample_interval=1.0,
        )
    )


def test_innovation_noise_metric_is_well_behaved_near_zero_mean() -> None:
    processor = _processor()

    last = None
    for ts in range(60):
        value = 0.01 if ts % 2 == 0 else -0.01
        last = processor.update(value, timestamp=float(ts))

    assert last is not None
    assert last.noise_level == 0.0
    assert last.sqi_components["noise"] > 90.0


def test_innovation_noise_metric_drops_on_sustained_residual_energy() -> None:
    processor = _processor()

    for ts in range(20):
        processor.update(0.0, timestamp=float(ts))

    last = None
    for idx in range(30):
        value = 5.0 if idx % 2 == 0 else -5.0
        last = processor.update(value, timestamp=float(20 + idx))

    assert last is not None
    assert last.noise_level > 0.0
    assert last.sqi_components["noise"] < 50.0


def test_eta_clipping_bounds_single_spike_contamination() -> None:
    processor = _processor()

    for ts in range(20):
        processor.update(0.0, timestamp=float(ts))

    spike = processor.update(100.0, timestamp=20.0)
    assert spike is not None

    eta_bound = processor.config.innovation_beta * (processor.config.innovation_z_spike ** 2)
    assert spike.innovation_eta is not None
    assert spike.innovation_eta <= eta_bound + 1.0e-12

    assert spike.noise_level < 0.4

    post = processor.update(0.0, timestamp=21.0)
    assert post is not None
    assert post.noise_level < 1.0
    assert math.isfinite(post.noise_level)
