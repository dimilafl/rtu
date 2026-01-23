"""Tests for stale detector."""

from sqe.core.stale import StaleDetector


def test_repeated_identical_values_trigger_stale():
    detector = StaleDetector(window_size=3, recovery_window=2)
    detector.update(10.0, 1.0)
    detector.update(10.0, 2.0)
    result = detector.update(10.0, 3.0)

    assert result.is_stale is True
    assert result.reason == "flatline"


def test_timestamp_not_advancing_triggers_stale():
    detector = StaleDetector(window_size=3, recovery_window=2)
    detector.update(10.0, 1.0)
    result = detector.update(10.5, 1.0)

    assert result.is_stale is True
    assert result.reason == "timestamp"


def test_recovery_with_persistence_hysteresis():
    detector = StaleDetector(window_size=3, recovery_window=2)
    detector.update(10.0, 1.0)
    detector.update(10.0, 2.0)
    result = detector.update(10.0, 3.0)
    assert result.is_stale is True

    result = detector.update(11.0, 4.0)
    assert result.is_stale is True

    result = detector.update(12.0, 5.0)
    assert result.is_stale is False
