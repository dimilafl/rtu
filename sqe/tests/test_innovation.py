"""Unit tests for the innovation estimator module."""

from __future__ import annotations

import math

from sqe.core.innovation import InnovationModel


def _run_sequence(sequence):
    model = InnovationModel(q=0.05, r=0.2, beta=0.2, s_min=1e-12, p0_var=1.0, v0_var=1.0)
    return [model.update(y, dt) for y, dt in sequence]


def test_innovation_determinism_repeatability():
    sequence = [
        (1.0, 0.1),
        (1.1, 0.1),
        (1.2, 0.1),
        (None, 0.1),
        (1.3, 0.0),
        (1.4, -0.1),
        (1.45, 0.1),
    ]

    out_a = _run_sequence(sequence)
    out_b = _run_sequence(sequence)

    assert out_a == out_b


def test_innovation_constant_signal_converges():
    model = InnovationModel(q=0.001, r=0.2, beta=0.1, s_min=1e-12, p0_var=4.0, v0_var=4.0)

    # Initialize with a transient so velocity estimate has something to decay from.
    model.update(10.0, 0.1)
    model.update(11.0, 0.1)

    velocities = []
    etas = []
    for _ in range(80):
        _, _, _, v_hat, eta = model.update(10.0, 0.1)
        velocities.append(abs(v_hat))
        etas.append(eta)

    assert velocities[-1] < velocities[0]
    assert etas[-1] < 0.5


def test_innovation_spike_produces_large_z():
    model = InnovationModel(q=0.01, r=0.1, beta=0.2, s_min=1e-12, p0_var=1.0, v0_var=1.0)

    zs = []
    for y in [0.0] * 20 + [20.0] + [0.0] * 10:
        _, _, z, _, _ = model.update(y, 0.1)
        zs.append(0.0 if z is None else abs(z))

    spike_idx = 20
    assert zs[spike_idx] > 8.0
    assert zs[spike_idx] == max(zs)
    assert zs[21] < zs[20]
    assert all(z < 1e-9 for z in zs[:20])


def test_innovation_dt_nonpositive_is_safe():
    model = InnovationModel(q=0.05, r=0.1, beta=0.2, s_min=1e-9, p0_var=1.0, v0_var=1.0)

    results = [
        model.update(1.0, 0.1),
        model.update(1.1, 0.0),
        model.update(1.2, -0.5),
        model.update(1.1, 0.2),
    ]

    for _, S, _, _, _ in results:
        assert math.isfinite(S)
        assert S >= 0.0


def test_innovation_missing_predict_only():
    model = InnovationModel(q=0.1, r=0.1, beta=0.3, s_min=1e-12, p0_var=1.0, v0_var=1.0)

    model.update(2.0, 0.1)
    _, _, _, v_before, eta_before = model.update(2.3, 0.1)

    missing_1 = model.update(None, 0.0)
    missing_2 = model.update(None, -0.1)
    missing_3 = model.update(None, 0.2)

    for e, _, z, _, eta in (missing_1, missing_2, missing_3):
        assert e is None
        assert z is None
        assert eta == eta_before

    _, _, _, v_after, _ = missing_3
    assert v_after == v_before
