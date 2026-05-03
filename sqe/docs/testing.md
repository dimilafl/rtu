# Testing Guide

## Running Tests

```bash
# All tests (package-level + top-level)
pytest sqe/tests/ tests/ -q

# Package-level tests only
pytest sqe/tests/ -q

# Top-level tests only
pytest tests/ -q

# With coverage
pytest --cov=sqe sqe/tests/ tests/ -q

# Single test file
pytest sqe/tests/test_engine.py -v

# Single test function
pytest sqe/tests/test_engine.py::test_full_pipeline -v

# Skip performance tests
pytest sqe/tests/ tests/ -q --ignore=sqe/tests/test_perf_smoke.py
```

Current test count: **146 passing** (as of `STATUS_REPORT.md`).

## Test Layout

### Package-level tests: `sqe/tests/` (48 files)

| Category | Files | Covers |
|----------|-------|--------|
| **Core DSP** | `test_filters.py`, `test_drift.py`, `test_variance.py`, `test_freq.py`, `test_sqi.py` | EWMA, MA, HP filters; drift classification; variance/spike detection; frequency correlation + FFT; SQI scoring |
| **Engine** | `test_engine.py` | `SignalQualityEngine` registration, update pipeline, results correctness |
| **Incidents** | `test_incidents.py`, `test_group_incidents.py`, `test_grouping.py` | Incident lifecycle (start/update/resolve), group incidents, signal grouping |
| **Event Filtering** | `test_event_filter.py`, `test_suppression.py` | Member-event suppression, deferred re-emission |
| **Innovation** | `test_innovation.py`, `test_innovation_config_plumbing.py`, `test_innovation_drift_scoring.py`, `test_innovation_noise_scoring.py`, `test_innovation_explainability.py`, `test_innovation_runtime_spikes.py` | Kalman model, config plumbing, drift/noise scoring, runtime spike detection |
| **Signal Diagnostics** | `test_stale_detector.py`, `test_step_change.py`, `test_plausibility.py` | Stale detection, step-change detection, plausibility checks |
| **Replay** | `test_replay.py`, `test_replay_station_dropout.py` | Deterministic replay with fixtures |
| **Comms** | `test_comms_classification.py`, `test_comms_aggregation.py`, `test_comms_jsonl_determinism.py`, `test_comms_budget_jsonl_determinism.py` | Comms health, budget, determinism |
| **RCA** | `test_rca_evidence.py`, `test_rca_scoring.py` | RCA evidence collection, scoring |
| **Config** | `test_config_dump_determinism.py`, `test_yaml_duplicates.py` | Config serialization determinism, YAML duplicate key detection |
| **CLI** | `test_cli.py` | CLI argument parsing, command dispatch |
| **Integration** | `test_plcscan_adapter.py`, `test_service_comms_optional.py` | PLC adapter, service with optional comms |
| **Eval** | `test_eval.py`, `test_scenario_harness.py` | Evaluation metrics, scenario testing |
| **Metadata** | `test_metadata_samples.py` | Sample quality enum handling |
| **Reports** | `test_impact_report.py`, `test_troubleshoot_report.py` | Report generation |
| **Vectors** | `test_vectors.py` | Cross-language portability vectors |
| **Performance** | `test_perf_smoke.py` | Hot-path allocation checks, throughput fences |
| **Regression** | `test_regression_fences.py` | Numerical regression guards |

### Top-level tests: `tests/` (4 files)

| File | Covers |
|------|--------|
| `test_comms_budget_determinism.py` | Budget calculation determinism across runs |
| `test_comms_budget_math.py` | Budget arithmetic correctness |
| `test_comms_budget_reason_order.py` | Budget reason-ordering determinism |
| `test_comms_topology_index.py` | Topology-based comms node lookup |

### Test Fixtures: `sqe/tests/fixtures/`

```
fixtures/
├── replay/                     # Standard replay inputs + expected outputs
│   ├── scans.jsonl
│   ├── cfg.yaml
│   ├── groups.yaml
│   ├── expected_incidents.jsonl
│   ├── expected_group_incidents.jsonl
│   └── expected_scans.jsonl
├── replay_metadata/            # Replay with metadata fields
│   ├── scans.jsonl
│   ├── cfg.yaml
│   ├── groups.yaml
│   ├── expected_incidents.jsonl
│   ├── expected_group_incidents.jsonl
│   └── expected_scans.jsonl
├── replay_station_dropout/     # Station dropout scenario
│   ├── scans.jsonl
│   ├── cfg.yaml
│   ├── groups.yaml
│   ├── expected_incidents.jsonl
│   └── expected_group_incidents.jsonl
└── eval/
    └── labels.yaml             # Labeled incidents for evaluation
```

## Writing New Tests

### Place tests in the right location

- Core DSP logic → `sqe/tests/test_<component>.py`
- Engine integration → `sqe/tests/test_engine.py`
- Replay determinism → `sqe/tests/test_replay.py`
- CLI → `sqe/tests/test_cli.py`
- Comms-specific determinism → `tests/`

### Test conventions

```python
def test_detector_returns_expected_result():
    """Short docstring explaining what this tests."""
    detector = StaleDetector(window_size=3, recovery_window=2)
    
    # Feed initial values
    detector.update(42.0, 1.0)
    detector.update(42.0, 2.0)
    result = detector.update(42.0, 3.0)
    
    # Assert the result
    assert result.is_stale, "Flatline should be detected after window_size samples"
    assert result.flatline
    assert not result.timestamp_stale


def test_detector_recovers_after_hysteresis():
    """Verify recovery behavior."""
    ...
```

### Testing determinism

Replay determinism is verified by running replay twice with the same inputs and diffing outputs:

```python
import tempfile
from sqe.replay.runner import run_replay

def test_replay_determinism():
    with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
        run_replay("fixtures/scans.jsonl", "fixtures/cfg.yaml", None, dir_a)
        run_replay("fixtures/scans.jsonl", "fixtures/cfg.yaml", None, dir_b)
        
        incidents_a = (Path(dir_a) / "incidents.jsonl").read_text()
        incidents_b = (Path(dir_b) / "incidents.jsonl").read_text()
        assert incidents_a == incidents_b
```

### Adding test fixtures

1. Create a directory under `sqe/tests/fixtures/` named after the scenario
2. Include `scans.jsonl` (input), `cfg.yaml` (config), and `expected_incidents.jsonl` (expected output)
3. Write a test in `sqe/tests/test_replay.py` that replays the fixture and compares against expected output

## Performance Testing

Performance smoke tests in `sqe/tests/test_perf_smoke.py` ensure the hot path remains allocation-free and within throughput budgets:

```bash
# Run performance tests (requires CI environment)
pytest sqe/tests/test_perf_smoke.py -v
```

The CI `perf` job runs these on Python 3.11.

## Coverage

Target: >80% line coverage across `sqe/core/`. Critical paths (engine update, SQI calculation, incident lifecycle) should be near 100%.

```bash
pytest --cov=sqe --cov-report=term --cov-report=html sqe/tests/ tests/
open htmlcov/index.html
```

## Troubleshooting

### Tests pass locally but fail in CI

- Check Python version: CI runs 3.11 and 3.12
- Check for system-specific assumptions (file paths, RNG seeds)
- Check that test fixtures are committed and paths are relative

### Determinism failures

- Ensure all inputs (config, scans, groups) are identical across runs
- Check that `run_id` is fixed (not random) in test fixtures
- Verify no external state (system clock, file timestamps) affects output
- Check that `sorted()` calls are stable (sort keys are deterministic)
