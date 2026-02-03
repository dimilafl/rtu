"""Tests for PLC scan adapter timing metrics."""

import pytest

from sqe.core.engine import SignalQualityEngine
from sqe.integration import plcscan_adapter
from sqe.integration.plcscan_adapter import PLCScanAdapter


def test_plcscan_adapter_timing_metrics(monkeypatch):
    times = iter(
        [
            0.0,
            0.005,
            0.01,
            0.02,
            0.1,
            0.105,
            0.11,
            0.12,
            0.2,
            0.205,
            0.21,
            0.22,
        ]
    )
    perf_times = iter([0.0, 0.02, 0.1, 0.12, 0.2, 0.22])
    monkeypatch.setattr(plcscan_adapter.time, "time", lambda: next(times))
    monkeypatch.setattr(
        plcscan_adapter.time, "perf_counter", lambda: next(perf_times)
    )

    engine = SignalQualityEngine(scan_interval=0.1)
    engine.register_signal("sig1")
    adapter = PLCScanAdapter(engine, scan_interval=0.1, warn_on_overrun=False)

    for _ in range(3):
        result = adapter.execute_scan({"sig1": 1.0})
        assert result["scan_duration"] == pytest.approx(0.02)
        assert result["actual_interval"] == pytest.approx(0.1)
        assert result["utilization"] == pytest.approx(0.2)
        assert result["overrun"] == pytest.approx(0.0)
        assert result["overruns"] == 0
        assert result["status"] == "ok"
        assert result["error"] is None

    performance = adapter.get_scan_performance()
    assert performance["overruns"] == 0
    assert performance["error_count"] == 0
    assert performance["last_error"] is None


def test_plcscan_adapter_scan_error(monkeypatch):
    times = iter([0.0, 0.02])
    perf_times = iter([0.0, 0.02])
    monkeypatch.setattr(plcscan_adapter.time, "time", lambda: next(times))
    monkeypatch.setattr(
        plcscan_adapter.time, "perf_counter", lambda: next(perf_times)
    )

    engine = SignalQualityEngine(scan_interval=0.1)
    adapter = PLCScanAdapter(engine, scan_interval=0.1, warn_on_overrun=False)

    def raise_error(_signals):
        raise RuntimeError("boom")

    engine.update = raise_error

    result = adapter.execute_scan({"sig1": 1.0})
    assert result["status"] == "error"
    assert result["error"] is not None
    assert adapter.error_count == 1
    assert adapter.last_error == "RuntimeError: boom"


def test_plcscan_adapter_reset_metrics(monkeypatch):
    times = iter([0.0, 0.05, 0.1, 0.2])
    perf_times = iter([0.0, 0.2])
    monkeypatch.setattr(plcscan_adapter.time, "time", lambda: next(times))
    monkeypatch.setattr(
        plcscan_adapter.time, "perf_counter", lambda: next(perf_times)
    )

    engine = SignalQualityEngine(scan_interval=0.1)
    engine.register_signal("sig1")
    adapter = PLCScanAdapter(engine, scan_interval=0.1, warn_on_overrun=False)

    adapter.execute_scan({"sig1": 1.0})
    assert adapter.overruns == 1

    adapter.error_count = 2
    adapter.last_error = "RuntimeError: boom"
    adapter.reset_metrics()

    assert adapter.error_count == 0
    assert adapter.last_error is None
    assert adapter.overruns == 0
