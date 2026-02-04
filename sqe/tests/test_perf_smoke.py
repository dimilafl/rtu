"""Performance smoke tests for SQE."""

from __future__ import annotations

import time
import tracemalloc

from sqe.core.engine import SignalConfig, SignalQualityEngine


def _build_engine(signal_count: int) -> SignalQualityEngine:
    engine = SignalQualityEngine(
        scan_interval=0.1,
        auto_register=False,
        required_incident_causes=set(),
    )
    weights = {
        "noise": 0.4,
        "drift": 0.3,
        "spikes": 0.2,
        "oscillation": 0.0,
        "missing": 0.1,
        "stale": 0.0,
        "step": 0.0,
        "plausibility": 0.0,
    }
    for index in range(signal_count):
        signal_id = f"SIG_{index:03d}"
        engine.register_signal(
            signal_id,
            SignalConfig(
                signal_id=signal_id,
                enable_fft=False,
                reference_frequencies=[0.1],
                sqi_weights=weights,
            ),
        )
    return engine


def test_perf_smoke_runtime():
    engine = _build_engine(200)
    signal_ids = list(engine.processors.keys())
    base_values = {signal_id: float(i) for i, signal_id in enumerate(signal_ids)}

    start = time.perf_counter()
    for scan in range(200):
        signals = {
            signal_id: base_values[signal_id] + (scan * 0.01)
            for signal_id in signal_ids
        }
        engine.update(signals, timestamp=scan * 0.1)
    elapsed = time.perf_counter() - start

    assert elapsed < 12.0


def test_perf_smoke_memory_growth():
    engine = _build_engine(100)
    signal_ids = list(engine.processors.keys())

    tracemalloc.start()
    for scan in range(50):
        engine.update(
            {signal_id: float(scan) for signal_id in signal_ids},
            timestamp=scan * 0.1,
        )
    snapshot_start = tracemalloc.take_snapshot()
    for scan in range(50, 100):
        engine.update(
            {signal_id: float(scan) for signal_id in signal_ids},
            timestamp=scan * 0.1,
        )
    snapshot_end = tracemalloc.take_snapshot()
    tracemalloc.stop()

    total_start = sum(stat.size for stat in snapshot_start.statistics("filename"))
    total_end = sum(stat.size for stat in snapshot_end.statistics("filename"))
    growth = total_end - total_start

    assert growth < 5_000_000
