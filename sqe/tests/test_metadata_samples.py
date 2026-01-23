"""Tests for metadata-aware samples."""

from sqe.core.engine import SignalConfig, SignalProcessor, SignalQualityEngine
from sqe.core.incidents import IncidentCause, IncidentEngine, IncidentPolicy
from sqe.core.sample import Sample, SampleQuality
from sqe.ops.service import RealtimeQualityService


def build_policy() -> IncidentPolicy:
    return IncidentPolicy(
        start_sqi_threshold=50,
        end_sqi_threshold=60,
        start_persistence_scans=1,
        end_persistence_scans=1,
        critical_sqi_threshold=25,
        component_score_floor=70,
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


def test_bad_quality_treated_as_missing():
    engine = SignalQualityEngine()
    engine.register_signal("sig", SignalConfig(signal_id="sig"))
    service = RealtimeQualityService(engine, IncidentEngine(build_policy()))

    _, events, _ = service.process_scan_samples(
        {"sig": Sample(value=12.0, quality=SampleQuality.BAD)},
        timestamp=1.0,
    )

    assert events
    assert events[0].incident.cause == IncidentCause.MISSING


def test_uncertain_quality_affects_missing_ratio():
    processor = SignalProcessor(SignalConfig(signal_id="sig", missing_window=1))

    processed = processor.update(10.0, quality=SampleQuality.UNCERTAIN)

    assert processed is not None
    assert processor.get_effective_missing_ratio() == 0.5


def test_source_timestamp_drives_stale_reason():
    processor = SignalProcessor(SignalConfig(signal_id="sig", stale_window=2))

    processor.update(10.0, timestamp=1.0, source_timestamp=1.0)
    processed = processor.update(12.0, timestamp=2.0, source_timestamp=1.0)

    assert processed.stale is True
    assert processed.stale_reason == "timestamp"
