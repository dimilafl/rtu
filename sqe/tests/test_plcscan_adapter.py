"""Tests for PLC scan adapter timing metrics."""

import pytest

from sqe.core import engine as engine_module
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
    monkeypatch.setattr(plcscan_adapter.time, "time", lambda: next(times))

    engine = SignalQualityEngine(scan_interval=0.1)
    engine.register_signal("sig1")
    adapter = PLCScanAdapter(engine, scan_interval=0.1)

    for _ in range(3):
        result = adapter.execute_scan({"sig1": 1.0})
        assert result["scan_duration"] == pytest.approx(0.02)
        assert result["actual_interval"] == pytest.approx(0.1)
        assert result["utilization"] == pytest.approx(0.2)
        assert result["overrun"] is False
        assert result["overruns"] == 0
        assert result["status"] == "ok"

    performance = adapter.get_scan_performance()
    assert performance["overruns"] == 0
    assert performance["errors"] == 0


def test_plcscan_adapter_handles_unknown_signal(monkeypatch):
    times = iter(i * 0.01 for i in range(20))
    monkeypatch.setattr(plcscan_adapter.time, "time", lambda: next(times))
    monkeypatch.setattr(engine_module.time, "time", lambda: next(times))

    engine = SignalQualityEngine(auto_register=False)
    adapter = PLCScanAdapter(engine, scan_interval=0.1)

    result = adapter.execute_scan({"sig1": 1.0})

    assert result["status"] == "error"
    assert "not registered" in result["error"]
    assert result["processed_signals"] == {}
    assert adapter.error_count == 1


def test_plcscan_adapter_handles_max_signals(monkeypatch):
    times = iter(i * 0.01 for i in range(20))
    monkeypatch.setattr(plcscan_adapter.time, "time", lambda: next(times))
    monkeypatch.setattr(engine_module.time, "time", lambda: next(times))

    engine = SignalQualityEngine(max_signals=1)
    engine.register_signal("sig1")
    adapter = PLCScanAdapter(engine, scan_interval=0.1)

    result = adapter.execute_scan({"sig1": 1.0, "sig2": 2.0})

    assert result["status"] == "error"
    assert "Maximum number of registered signals" in result["error"]
    assert result["processed_signals"] == {}
    assert adapter.error_count == 1
