"""Tests for plausibility checker."""

from sqe.core.plausibility import PlausibilityChecker


def test_range_violation_triggers_immediately():
    checker = PlausibilityChecker(
        min_value=0.0,
        max_value=10.0,
        max_rate=None,
        persistence_scans=1,
        recovery_scans=1,
    )

    result = checker.update(11.0, 1.0)
    assert result.is_violation is True
    assert "above_max" in result.reasons


def test_range_violation_with_persistence():
    checker = PlausibilityChecker(
        min_value=0.0,
        max_value=10.0,
        max_rate=None,
        persistence_scans=2,
        recovery_scans=1,
    )

    result = checker.update(11.0, 1.0)
    assert result.is_violation is False

    result = checker.update(11.5, 2.0)
    assert result.is_violation is True
