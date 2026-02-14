"""Tests for innovation diagnostics wiring and incident explainability payload."""

from __future__ import annotations

import pytest

from sqe.core.engine import SignalConfig, SignalProcessor
from sqe.core.incidents import IncidentCause, IncidentEngine, IncidentPolicy


def _innovation_processor() -> SignalProcessor:
    return SignalProcessor(
        SignalConfig(
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
    )


def _legacy_processor() -> SignalProcessor:
    return SignalProcessor(
        SignalConfig(
            signal_id="sig_legacy",
            innovation_enabled=False,
            sample_interval=1.0,
        )
    )


def _policy() -> IncidentPolicy:
    return IncidentPolicy(
        start_sqi_threshold=50.0,
        end_sqi_threshold=60.0,
        start_persistence_scans=1,
        end_persistence_scans=1,
        critical_sqi_threshold=25.0,
        component_score_floor=70.0,
        cause_priority=[
            IncidentCause.MISSING,
            IncidentCause.STALE,
            IncidentCause.STEP,
            IncidentCause.PLAUSIBILITY,
            IncidentCause.DRIFT,
            IncidentCause.SPIKES,
            IncidentCause.NOISE,
            IncidentCause.OSCILLATION,
            IncidentCause.UNKNOWN,
        ],
    )


def test_innovation_diagnostics_fields_are_populated_for_spike_sample() -> None:
    processor = _innovation_processor()

    for ts in range(10):
        processor.update(0.0, timestamp=float(ts))
    spike = processor.update(10.0, timestamp=10.0)

    assert spike is not None
    assert spike.innovation_z is not None
    assert spike.innovation_z_spike is not None
    assert abs(spike.innovation_z) >= spike.innovation_z_spike
    assert spike.innovation_residual is not None
    assert spike.innovation_S is not None
    assert spike.innovation_v_hat is not None
    assert spike.innovation_eta is not None


def test_incident_details_include_innovation_spike_only_when_enabled() -> None:
    engine = IncidentEngine(_policy(), run_id="run-innovation")

    innovation_processor = _innovation_processor()
    for ts in range(10):
        innovation_processor.update(0.0, timestamp=float(ts))
    innovation_processed = innovation_processor.update(10.0, timestamp=10.0)
    assert innovation_processed is not None

    evals = engine.evaluate_signal_statuses(
        processed_signals={"sig_1": innovation_processed},
        missing_ratio_by_signal={"sig_1": 0.0},
        include_details=True,
    )
    details = evals["sig_1"]["details"]
    assert "innovation_spike" in details
    assert details["innovation_spike"]["z"] == pytest.approx(
        innovation_processed.innovation_z
    )
    assert details["innovation_spike"]["z_spike"] == pytest.approx(
        innovation_processed.innovation_z_spike
    )
    assert details["innovation_spike"]["is_spike"] is innovation_processed.is_spike
    assert "innovation_drift" in details
    assert details["innovation_drift"]["drift_ema"] == pytest.approx(
        innovation_processed.innovation_drift_ema
    )

    legacy_processor = _legacy_processor()
    for ts in range(10):
        legacy_processor.update(0.0, timestamp=float(ts))
    legacy_processed = legacy_processor.update(10.0, timestamp=10.0)
    assert legacy_processed is not None

    legacy_evals = engine.evaluate_signal_statuses(
        processed_signals={"sig_legacy": legacy_processed},
        missing_ratio_by_signal={"sig_legacy": 0.0},
        include_details=True,
    )
    legacy_details = legacy_evals["sig_legacy"]["details"]
    assert "innovation_spike" not in legacy_details
