"""Tests for innovation config plumbing into SignalConfig."""

from __future__ import annotations

import textwrap

import pytest

from sqe.config.loader import build_signal_config, load_config


def test_innovation_overrides_flow_into_signal_config(tmp_path):
    override_path = tmp_path / "override.yaml"
    override_path.write_text(
        textwrap.dedent(
            """
            innovation:
              enabled: true
              q: 0.2
              r: 0.8
              beta: 0.2
              s_min: 1.0e-9
              p0_var: 1234.0
              v0_var: 567.0
              z_spike: 9.5
              noise_threshold: 1.7
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(str(override_path))
    signal_config = build_signal_config(config, signal_id="sig_1", sample_interval=0.1)

    assert signal_config.innovation_enabled is True
    assert signal_config.innovation_q == pytest.approx(0.2)
    assert signal_config.innovation_r == pytest.approx(0.8)
    assert signal_config.innovation_beta == pytest.approx(0.2)
    assert signal_config.innovation_s_min == pytest.approx(1.0e-9)
    assert signal_config.innovation_p0_var == pytest.approx(1234.0)
    assert signal_config.innovation_v0_var == pytest.approx(567.0)
    assert signal_config.innovation_z_spike == pytest.approx(9.5)
    assert signal_config.innovation_noise_threshold == pytest.approx(1.7)


@pytest.mark.parametrize(
    "override_body,error_message",
    [
        ("r: 0", "innovation.r must be > 0"),
        ("beta: 0", "innovation.beta must be > 0 and <= 1"),
        ("beta: 2", "innovation.beta must be > 0 and <= 1"),
        ("q: -0.1", "innovation.q must be >= 0"),
        ("s_min: 0", "innovation.s_min must be > 0"),
        ("p0_var: 0", "innovation.p0_var must be > 0"),
        ("v0_var: 0", "innovation.v0_var must be > 0"),
        ("z_spike: 0", "innovation.z_spike must be > 0"),
        ("noise_threshold: 0", "innovation.noise_threshold must be > 0"),
    ],
)
def test_innovation_invalid_values_raise_deterministically(
    tmp_path, override_body, error_message
):
    override_path = tmp_path / "invalid.yaml"
    override_path.write_text(
        "innovation:\n  " + override_body + "\n",
        encoding="utf-8",
    )

    config = load_config(str(override_path))

    with pytest.raises(ValueError, match=error_message):
        build_signal_config(config, signal_id="sig_1", sample_interval=0.1)
