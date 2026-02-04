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


def test_hot_path_allocation_free():
    """Verify hot path operations don't allocate per-sample after warmup.

    This test ensures the deterministic real-time hot path optimizations
    are working: SignalBuffer.get_samples returns views/scratch, variance
    uses rolling sums, and filters avoid numpy allocation per update.
    """
    from sqe.core.signal_buffer import SignalBuffer
    from sqe.core.variance import VarianceCalculator
    from sqe.core.filters import MovingAverageFilter
    from sqe.core.stale import StaleDetector
    from sqe.core.step_change import StepChangeDetector

    # Create components
    buf = SignalBuffer(100)
    var_calc = VarianceCalculator(20)
    ma_filter = MovingAverageFilter(10)
    stale_det = StaleDetector(window_size=5, recovery_window=3)
    step_det = StepChangeDetector(
        baseline_window=10,
        step_threshold=5.0,
        persistence_scans=3,
        recovery_scans=5,
    )

    # Warmup phase - fill buffers
    for i in range(200):
        value = 10.0 + (i * 0.01)
        buf.push(value)
        var_calc.update(value)
        ma_filter.update(value)
        stale_det.update(value, float(i))
        step_det.update(value)

    # Measure allocations during steady-state
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    # Run 1000 iterations of hot path operations
    for i in range(1000):
        value = 10.0 + (i * 0.001)
        timestamp = 200.0 + i

        # Hot path operations
        buf.push(value)
        samples = buf.get_samples()  # Should return view or scratch
        _ = len(samples)

        var_calc.update(value)
        _ = var_calc.get_stats()

        ma_filter.update(value)

        stale_det.update(value, timestamp)

        step_det.update(value)

    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    # Calculate allocation growth
    stats_before = snapshot_before.statistics("filename")
    stats_after = snapshot_after.statistics("filename")
    total_before = sum(stat.size for stat in stats_before)
    total_after = sum(stat.size for stat in stats_after)
    growth = total_after - total_before

    # Allow small constant growth (dict results, etc.) but not O(n) growth
    # 1000 iterations should not cause more than 100KB growth
    # (before optimization this would be several MB from numpy arrays)
    assert growth < 100_000, f"Hot path allocation growth too high: {growth} bytes"


def test_signal_buffer_returns_views_when_contiguous():
    """Verify SignalBuffer.get_samples returns views for contiguous data."""
    from sqe.core.signal_buffer import SignalBuffer

    buf = SignalBuffer(10)

    # Push values without wrapping
    for i in range(5):
        buf.push(float(i))

    # Get samples twice - should return same underlying memory
    samples1 = buf.get_samples()
    samples2 = buf.get_samples()

    # Both should be views into the same _values array
    assert samples1.base is not None or len(samples1) == 0 or samples1.base is buf._values
    assert id(samples1.base) == id(samples2.base) if samples1.base is not None else True

    # Values should match
    assert list(samples1) == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert list(samples2) == [0.0, 1.0, 2.0, 3.0, 4.0]
