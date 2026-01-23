"""Tests for step-change detector."""

from sqe.core.step_change import StepChangeDetector


def test_single_outlier_does_not_trigger_step():
    detector = StepChangeDetector(
        baseline_window=4,
        step_threshold=5.0,
        persistence_scans=2,
        recovery_scans=3,
    )

    for i in range(4):
        detector.update(10.0 + (i * 0.1))

    result = detector.update(20.0)
    assert result.is_step is False

    result = detector.update(10.0)
    assert result.is_step is False


def test_persistent_offset_classifies_step():
    detector = StepChangeDetector(
        baseline_window=4,
        step_threshold=5.0,
        persistence_scans=2,
        recovery_scans=3,
    )

    for i in range(4):
        detector.update(10.0 + (i * 0.1))

    detector.update(20.0)
    result = detector.update(20.0)
    assert result.is_step is True
    assert result.offset is not None
    assert result.offset >= 5.0


def test_step_resolves_when_baseline_stabilizes():
    detector = StepChangeDetector(
        baseline_window=4,
        step_threshold=5.0,
        persistence_scans=2,
        recovery_scans=2,
    )

    for i in range(4):
        detector.update(10.0 + (i * 0.1))

    detector.update(20.0)
    result = detector.update(20.0)
    assert result.is_step is True

    result = detector.update(20.0)
    assert result.is_step is True

    result = detector.update(20.0)
    assert result.is_step is False
