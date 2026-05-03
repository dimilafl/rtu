# Module Reference

## `sqe.core` — DSP and Signal Processing

### `engine.py`
**157,000 bytes | Classes: 4**

The main entry point. Contains `SignalQualityEngine`, `SignalProcessor`, `SignalConfig`, and `ProcessedSignal`.

| Class | Purpose |
|-------|---------|
| `SignalQualityEngine(scan_interval, auto_register, ...)` | Orchestrates all registered signals. Provides `register_signal()`, `update()`, `update_samples()`, `update_single()`, `get_signal_stats()`, `reset_all()`. |
| `SignalProcessor(config, required_causes)` | Per-signal pipeline. Executes filters → drift → spike → variance → oscillation → stale → step → plausibility → SQI. |
| `SignalConfig(signal_id, ewma_alpha, ...)` | ~40 configurable parameters for one signal pipeline. Validates itself in `__post_init__`. |
| `ProcessedSignal(signal_id, timestamp, raw, ...)` | Output dataclass with 33 fields covering all DSP results, SQI, and alerts. |

### `signal_buffer.py`
**210 lines | Class: 1**

| Class | Purpose |
|-------|---------|
| `SignalBuffer(capacity)` | Fixed-size NumPy circular buffer. O(1) `push()`, O(1) `get_samples()` returning array views where possible. Tracks missing samples via boolean mask. |

### `filters.py`
**193 lines | Classes: 3**

| Class | Purpose | Complexity |
|-------|---------|------------|
| `EWMAFilter(alpha)` | Exponentially weighted moving average low-pass: `y[n] = α·x[n] + (1-α)·y[n-1]` | O(1) |
| `HighPassFilter(alpha)` | Derived from EWMA low-pass: `hp[n] = x[n] - lp[n]` | O(1) |
| `MovingAverageFilter(window_size)` | Simple moving average with O(1) rolling sum | O(1) |
| `FilterBank()` | Container to apply multiple filters in parallel | O(k) |

### `drift.py`
**269 lines | Classes: 2**

| Class | Purpose |
|-------|---------|
| `DriftDetector(small_drift_threshold, large_drift_threshold, ...)` | Computes discrete derivative `dX = x[n] - x[n-1]` and classifies as `NONE`, `SUSTAINED_SMALL`, `TRANSIENT_LARGE`, or `MONOTONIC`. |
| `DriftAnalyzer(window_size)` | (Unused) Statistical analysis over drift event history. |

Key output: `DriftEvent(drift_rate, drift_type, severity, monotonic_samples, sustained)`

### `variance.py`
**389 lines | Classes: 3**

| Class | Purpose |
|-------|---------|
| `VarianceCalculator(window_size)` | O(1) sliding-window variance using rolling `sum` and `sumsq`. Returns `mean`, `variance` (sample, ddof=1), `std_dev`, `noise_level` (coefficient of variation). |
| `WelfordVariance()` | Welford's online algorithm for cumulative (non-windowed) variance. |
| `SpikeDetector(window_size, k_sigma, variance_calc)` | Detects spikes as values exceeding `mean + k·σ` from baseline stats. Supports external `VarianceCalculator` to share state. |

### `freq_detect.py`
**430 lines | Classes: 3**

| Class | Purpose |
|-------|---------|
| `FrequencyDetector(ref_freqs, dt, window_size)` | Correlates signal with pre-computed sin/cos reference waveforms. Returns `FrequencyComponent(freq, magnitude, phase, energy)`. |
| `FFTFrequencyAnalyzer(window_size, dt)` | Hann-windowed FFT with `np.fft.rfft`. Returns spectrum, peak frequency, peak magnitude. |
| `OscillationDetector(ref_freqs, dt, window_size, enable_fft)` | Combines correlation-based and FFT-based detection. Supports load-shedding cadence for performance. |

### `innovation.py`
**158 lines | Class: 1**

| Class | Purpose |
|-------|---------|
| `InnovationModel(q, r, beta, s_min, ...)` | Constant-velocity Kalman filter for residual normalization. Returns `(e, S, z, v_hat, eta)` per measurement. Deterministic for identical inputs. |

### `sqi.py`
**349 lines | Classes: 2**

| Class | Purpose |
|-------|---------|
| `SignalQualityIndex(weights, noise_threshold, ...)` | Computes 0-100 composite SQI from 8 component scores. Tracks history for trend analysis ("improving"/"degrading"/"stable"). |
| `SQIWeights(noise, drift, spikes, ...)` | Weight configuration dataclass with `normalize()` method enforcing sum-to-1. |

### `stale.py`
**89 lines | Class: 1**

| Class | Purpose |
|-------|---------|
| `StaleDetector(window_size, recovery_window)` | Detects frozen values (flatline) and non-advancing timestamps with O(1) run-length tracking and recovery hysteresis. |

### `step_change.py`
**124 lines | Class: 1**

| Class | Purpose |
|-------|---------|
| `StepChangeDetector(baseline_window, step_threshold, persistence_scans, recovery_scans)` | Detects persistent signal offsets using O(1) rolling baseline mean with confirmation and recovery windows. |

### `plausibility.py`
**91 lines | Class: 1**

| Class | Purpose |
|-------|---------|
| `PlausibilityChecker(min_value, max_value, max_rate, ...)` | Validates values against range limits and rate-of-change limits with persistence/recovery hysteresis. |

### `sample.py`
| Class | Purpose |
|-------|---------|
| `Sample(value, quality, source_timestamp)` | Sample with metadata. `SampleQuality` enum: `GOOD`, `UNCERTAIN`, `BAD`. |

### `incidents.py`
**497 lines | Classes: 4**

| Class | Purpose |
|-------|---------|
| `IncidentEngine(policy, run_id)` | Scan-driven incident lifecycle: started → updated → resolved. Uses persistence/debouncing via streak counters. |
| `IncidentPolicy(start_sqi_threshold, end_sqi_threshold, ...)` | Frozen policy dataclass controlling incident start/end thresholds, persistence spans, cause priorities. |
| `QualityIncident(incident_id, signal_id, cause, ...)` | Active incident state tracking min/max SQI, timestamps, scan indices. |
| `IncidentEvent(event_type, incident, message, ...)` | Frozen output event: STARTED, UPDATED, or RESOLVED. |

### `group_incidents.py`
**341 lines | Classes: 3**

| Class | Purpose |
|-------|---------|
| `GroupIncidentEngine(policy, run_id)` | Aggregates per-signal statuses into group-level incidents (e.g., station-wide comms failure). |
| `GroupIncidentPolicy(min_members, min_fraction, ...)` | Policy: minimum members, fraction thresholds, persistence. |
| `GroupIncident(group_incident_id, group_id, degraded_members, ...)` | Group incident state, cause classification (COMMS/DATA_QUALITY/MIXED). |

### `grouping.py`
**52 lines | Classes: 2**

| Class | Purpose |
|-------|---------|
| `GroupingConfig(mode, prefix_delimiter, ...)` | Config: "prefix" or "explicit" grouping mode. |
| `GroupResolver(cfg)` | Resolves `signal_id → group_id` via prefix parsing or explicit mapping. |

### `event_filter.py`
**136 lines | Classes: 2**

| Class | Purpose |
|-------|---------|
| `EventFilter(policy)` | Suppresses per-signal incident events when a parent group incident is active, with deferred re-emission on group resolution. |
| `EventFilterPolicy(suppress_member_events, ...)` | Configures which event types and group causes trigger suppression. |

---

## `sqe.ops` — Service Layer

### `service.py`
**289 lines | Class: 2**

| Class | Purpose |
|-------|---------|
| `RealtimeQualityService(engine, incident_engine, ...)` | Orchestrates one full scan cycle: engine update → incident evaluation → group incidents → event filtering → comms outputs. |
| `ProcessedScan(processed_signals, ...)` | Frozen scan output bundling processed signals, suppression stats, comms health, and utilization statuses. |

---

## `sqe.config` — Configuration

### `loader.py`
**597 lines | Functions: ~20**

Key functions:
- `load_config(user_path)` — loads `defaults.yaml`, deep-merges optional user override
- `build_signal_config(config, signal_id, sample_interval)` — constructs `SignalConfig` from merged config dict
- `get_incident_policy(config)` — constructs `IncidentPolicy`
- `get_group_incident_policy(config)` — constructs `GroupIncidentPolicy`
- `get_event_filter_policy(config)` — constructs `EventFilterPolicy`
- Various typed accessors: `get_engine_scan_interval()`, `get_performance_settings()`, etc.

### `defaults.yaml`
**288 lines** — Complete configuration inventory. See `config_map.md` for full key reference.

### `yaml_strict.py`
Strict YAML loading that rejects duplicate keys (standard `yaml.safe_load` silently overwrites duplicates).

---

## `sqe.comms` — Communications Health

| Module | Purpose |
|--------|---------|
| `health.py` | Aggregates comms metrics per signal, classifies health status (degraded/healthy) |
| `budget.py` | Comms capacity budgeting: utilization, headroom, oversubscription detection |
| `api.py` | Public `build_utilization_statuses()` entry point |
| `schema.py` | JSON schemas for comms metrics |
| `topology_index.py` | Topology-aware comms node lookup |

---

## `sqe.rca` — Root Cause Analysis

| Module | Purpose |
|--------|---------|
| `engine.py` | RCA orchestrator: collects evidence, scores candidates, selects root cause |
| `evidence.py` | Evidence collection from signal and comms data |
| `scoring.py` | Scoring algorithms (comms-aware terms: comms_boost, comms_counter) |
| `scenario.py` | RCA scenario modeling |
| `state.py` | RCA state management across scans |
| `suppression.py` | Priority and suppression rules for RCA candidates |
| `node_incidents.py` | Node-level incident lifecycle |
| `confidence.py` | Confidence scoring for RCA findings |

---

## `sqe.replay` — Deterministic Replay

| Module | Purpose |
|--------|---------|
| `runner.py` | `run_replay()` — reads scans.jsonl, processes through full pipeline, writes processed rows, incidents, group incidents, comms health, and budget files. |

---

## `sqe.topology` — Topology Management

| Module | Purpose |
|--------|---------|
| `model.py` | `TopologySnapshot`, `TopologyNode`, `TopologyEdge` dataclasses |
| `loader.py` | YAML topology file loader |
| `index.py` | Efficient topology lookup by node ID |

---

## `sqe.eval` — Evaluation

| Module | Purpose |
|--------|---------|
| `labels.py` | Loads incident label files (YAML/JSON) for ground truth |
| `metrics.py` | Computes precision, recall, F1, mean time to detect, cause accuracy, severity accuracy, spam ratio |

---

## `sqe.cli` — Command Line Interface

### `sqe_cli.py`
**857 lines**

Commands:

| Command | Purpose |
|---------|---------|
| `sqe analyze --signal-file FILE [--plot] [--config CFG]` | Load CSV, run pipeline, print stats |
| `sqe simulate --duration N --noise N [--plot] [--config CFG]` | Sinusoidal signal + noise, run pipeline |
| `sqe incidents --signal-file FILE --out FILE [--config CFG] [--groups-config CFG]` | Run pipeline, write incidents.jsonl |
| `sqe replay --in JSONL --config CFG --out DIR [--groups-config CFG]` | Deterministic replay |
| `sqe eval --replay-out DIR --labels FILE [--out-json FILE]` | Evaluate replay against labels |
| `sqe offline-tuning --replay-input JSONL --labels FILE --sweep-config CFG --out-dir DIR [--mode MODE]` | Parameter sweep for incident policy / SQI |
| `sqe version` | Print version |

---

## `sqe.tools` — Utilities

| Module | Purpose |
|--------|---------|
| `bench.py` | Performance benchmark: configurable signal count, scan count, missing rate |
| `offline_tuning.py` | Offline parameter tuning pipeline (grid search over thresholds) |
| `impact_report.py` | Generates impact reports from incident data |
| `export_vectors.py` | Exports portability test vectors |
| `dump_config_map.py` | Dumps effective config key inventory |

---

## `sqe.integration` — Adapters

| Module | Purpose |
|--------|---------|
| `pointcore_adapter.py` | Adapts SQE for PointCore-Simulator output |
| `plcscan_adapter.py` | Adapts SQE for PLC_Scan_Engine scan cycles |
| `comms_adapter.py` | Adapts SQE for SCADA-Comms-Front-End-Processor |
| `publisher.py` | JSONL publisher and OASyS telemetry stub |
