"""Tests for innovation-mode drift scoring and hold semantics."""

from __future__ import annotations

import pytest

from sqe.core.engine import SignalConfig, SignalProcessor


def _processor(*, beta: float = 0.2, drift_alert_threshold: float = 0.05) -> SignalProcessor:
    return SignalProcessor(
        SignalConfig(
            signal_id="sig_drift",
            innovation_enabled=True,
            innovation_beta=beta,
            innovation_z_spike=6.0,
            innovation_r=1.0,
            innovation_q=0.05,
            innovation_p0_var=1.0e6,
            innovation_v0_var=1.0e4,
            sample_interval=1.0,
            drift_alert_threshold=drift_alert_threshold,
        )
    )


def _run_sequence(processor: SignalProcessor):
    outputs = []
    for k in range(40):
        outputs.append(processor.update(float(k), timestamp=float(k)))
    return outputs


def test_innovation_drift_is_deterministic() -> None:
    a = _processor(beta=0.15, drift_alert_threshold=0.03)
    b = _processor(beta=0.15, drift_alert_threshold=0.03)

    outputs_a = _run_sequence(a)
    outputs_b = _run_sequence(b)

    assert outputs_a == outputs_b

    drift_ema_a = [o.innovation_drift_ema for o in outputs_a if o is not None]
    drift_ema_b = [o.innovation_drift_ema for o in outputs_b if o is not None]
    assert drift_ema_a == pytest.approx(drift_ema_b)

    drift_components_a = [o.sqi_components["drift"] for o in outputs_a if o is not None]
    drift_components_b = [o.sqi_components["drift"] for o in outputs_b if o is not None]
    assert drift_components_a == pytest.approx(drift_components_b)

    alerts_a = [o.drift_alert for o in outputs_a if o is not None]
    alerts_b = [o.drift_alert for o in outputs_b if o is not None]
    assert alerts_a == alerts_b


def test_innovation_drift_ema_holds_on_missing_and_timestamp_regression() -> None:
    processor = _processor(beta=0.2)

    for k in range(20):
        processor.update(float(k), timestamp=float(k))

    baseline = processor.update(20.0, timestamp=20.0)
    assert baseline is not None
    assert baseline.innovation_drift_ema is not None
    held_value = baseline.innovation_drift_ema

    missing = processor.update(None, timestamp=21.0)
    assert missing is None
    assert processor._innovation_drift_ema == pytest.approx(held_value)

    regressed = processor.update(
        21.0,
        timestamp=22.0,
        source_timestamp=19.0,
    )
    assert regressed is not None
    assert regressed.innovation_drift_ema == pytest.approx(held_value)


def test_innovation_spike_does_not_update_drift_ema() -> None:
    processor = _processor(beta=0.2)

    for ts in range(10):
        processor.update(0.0, timestamp=float(ts))

    before = processor.update(1.0, timestamp=10.0)
    assert before is not None
    held_value = before.innovation_drift_ema

    spike = processor.update(100.0, timestamp=11.0)
    assert spike is not None
    assert spike.is_spike is True
    assert spike.innovation_drift_ema == pytest.approx(held_value)
    assert spike.sqi_components["spikes"] < before.sqi_components["spikes"]
    assert spike.sqi_components["drift"] == pytest.approx(before.sqi_components["drift"])


def test_innovation_drift_delta_and_ema_track_ramp() -> None:
    processor = _processor(beta=0.2, drift_alert_threshold=0.5)

    outputs = []
    slope = 0.5
    for k in range(80):
        outputs.append(processor.update(slope * k, timestamp=float(k)))

    tail = [o for o in outputs[-20:] if o is not None and o.innovation_drift_delta is not None]
    assert tail

    mean_delta = sum(o.innovation_drift_delta for o in tail) / len(tail)
    mean_ema = sum(o.innovation_drift_ema for o in tail) / len(tail)

    expected = abs(slope) * 1.0
    assert mean_delta == pytest.approx(expected, rel=0.3, abs=0.1)
    assert mean_ema == pytest.approx(expected, rel=0.3, abs=0.1)
