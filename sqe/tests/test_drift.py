"""Tests for drift detection."""

import pytest
import numpy as np

from sqe.core.drift import DriftDetector, DriftType, DriftAnalyzer


class TestDriftDetector:
    """Test drift detector."""

    def test_initialization(self):
        """Test detector initialization."""
        detector = DriftDetector(
            small_drift_threshold=0.5,
            large_drift_threshold=5.0
        )
        assert detector.small_threshold == 0.5
        assert detector.large_threshold == 5.0

    def test_first_sample_no_drift(self):
        """Test that first sample shows no drift."""
        detector = DriftDetector()
        event = detector.update(10.0)

        assert event.drift_rate == 0.0
        assert event.drift_type == DriftType.NONE
        assert event.severity == 0.0

    def test_small_drift_detection(self):
        """Test detection of small drift."""
        detector = DriftDetector(small_drift_threshold=0.5)

        # Create small sustained drift
        for i in range(15):
            event = detector.update(10.0 + i * 0.8)

        assert event.drift_type in [DriftType.SUSTAINED_SMALL, DriftType.MONOTONIC]
        assert event.severity > 0

    def test_large_drift_detection(self):
        """Test detection of large transient drift."""
        detector = DriftDetector(large_drift_threshold=5.0)

        detector.update(10.0)
        event = detector.update(20.0)  # Large jump

        assert event.drift_type == DriftType.TRANSIENT_LARGE
        assert event.severity > 0.5

    def test_monotonic_detection(self):
        """Test monotonic drift detection."""
        detector = DriftDetector(monotonic_window=5)

        # Create monotonic increasing trend
        for i in range(10):
            event = detector.update(10.0 + i * 0.5)

        assert event.monotonic_samples >= 5
        assert event.drift_type == DriftType.MONOTONIC

    def test_drift_rate_calculation(self):
        """Test drift rate calculation."""
        detector = DriftDetector()

        detector.update(10.0)
        event = detector.update(15.0)

        assert event.drift_rate == 5.0

    def test_zero_drift(self):
        """Test constant signal produces no drift."""
        detector = DriftDetector()

        for _ in range(10):
            event = detector.update(10.0)

        assert event.drift_rate == 0.0
        assert event.drift_type == DriftType.NONE

    def test_reset(self):
        """Test detector reset."""
        detector = DriftDetector()
        detector.update(10.0)
        detector.reset()

        assert detector.last_value is None
        assert detector.monotonic_count == 0


class TestDriftAnalyzer:
    """Test drift analyzer."""

    def test_initialization(self):
        """Test analyzer initialization."""
        analyzer = DriftAnalyzer(window_size=50)
        assert len(analyzer.event_history) == 0

    def test_add_event(self):
        """Test adding drift events."""
        analyzer = DriftAnalyzer()
        detector = DriftDetector()

        event = detector.update(10.0)
        analyzer.add_event(event)

        assert len(analyzer.event_history) == 1

    def test_statistics_empty(self):
        """Test statistics with no data."""
        analyzer = DriftAnalyzer()
        stats = analyzer.get_statistics()

        assert stats["mean_drift"] == 0.0
        assert stats["max_drift"] == 0.0

    def test_statistics_with_data(self):
        """Test statistics calculation."""
        analyzer = DriftAnalyzer()
        detector = DriftDetector()

        # Generate drift events
        for i in range(10):
            event = detector.update(10.0 + i * 0.5)
            analyzer.add_event(event)

        stats = analyzer.get_statistics()

        assert stats["mean_drift"] > 0
        assert stats["max_drift"] > 0
        assert "drift_variance" in stats
        assert "drift_rate_stability" in stats

    def test_event_history_limit(self):
        """Test that event history is limited."""
        analyzer = DriftAnalyzer()
        detector = DriftDetector()

        # Add more than 100 events
        for i in range(150):
            event = detector.update(float(i))
            analyzer.add_event(event)

        # Should keep only last 100
        assert len(analyzer.event_history) == 100
