# Configuration Map and Loader Contract

This document is the Phase 0 baseline inventory for configuration behavior.

## 1) Two configuration spaces

### Main config space
- Source of defaults: `sqe/config/defaults.yaml`.
- Load path: `load_config(user_path)` in `sqe/config/loader.py`.
- Optional user override is:
  1. Parsed with `_load_yaml` (`yaml.safe_load`).
  2. Schema-checked against defaults with `_validate_override_keys`.
  3. Deep-merged with `_deep_merge`.

### Groups config space
- Separate optional YAML loaded via `load_groups_config(user_path)`.
- Parsed independently from main config (no `_validate_override_keys` contract).
- Consumed via `get_grouping_config` and `get_group_incident_policy`.
- Runtime usage in replay: `sqe/replay/runner.py` loads `groups_config_path` separately and wires group resolver / group incident engine.

---

## 2) Deterministic merge semantics

Let:
- `D` = defaults mapping
- `U` = user override mapping
- `M` = merged mapping

Validation for main config only:
- For every dotted key `k` in `U`, `k` must exist in `D` and preserve mapping/scalar container shape.
- Violations raise `ConfigError`.

Merge operator:

- `M = D ⊕ U` where for each key:
  - if both sides are mappings: recurse
  - otherwise: replace `D[key]` with `U[key]`

Notes:
- Loader contract is deterministic for identical files.
- Tooling output should be sorted lexicographically by dotted keys.

---

## 3) Full key map from `defaults.yaml` (effective keys)

> Effective means “post-YAML parse (`safe_load`) mapping keys.”

### `engine.*`
- `engine.scan_interval = 0.1`
- `engine.auto_register = true`
- `engine.treat_missing_signals_as_none = true`
- `engine.unknown_signal_policy = "error"`
- `engine.max_signals_policy = "error"`

### `filters.*`
- `filters.default_ewma_alpha = 0.3`
- `filters.default_ma_window = 10`

### `drift.*`
- `drift.small_threshold = 0.5`
- `drift.large_threshold = 5.0`
- `drift.sustained_window = 10`
- `drift.monotonic_window = 5`

### `variance.*`
- `variance.default_window = 20`
- `variance.spike_k_sigma = 3.0`
- `variance.debounce_samples = 2`

### `innovation.*`
- `innovation.enabled = false`
- `innovation.q = 0.01`
- `innovation.r = 1.0`
- `innovation.beta = 0.05`
- `innovation.s_min = 1.0e-12`
- `innovation.p0_var = 1.0e6`
- `innovation.v0_var = 1.0e4`
- `innovation.z_spike = 6.0`
- `innovation.noise_threshold = 1.0`
- Status: active runtime path when enabled; innovation residuals (`|z| >= innovation.z_spike`) drive spike events and EWMA spike frequency used by SQI and spike alerts. Innovation noise for SQI uses `noise_excess = max(0, sqrt(eta) - 1)` with robust `eta` updates based on `min(z^2, z_spike^2)`, scaled by `innovation.noise_threshold`.

### `stale.*`
- `stale.window = 5`
- `stale.recovery_window = 3`

### `step_change.*`
- `step_change.baseline_window = 10`
- `step_change.threshold = 5.0`
- `step_change.persistence_scans = 3`
- `step_change.recovery_scans = 5`

### `plausibility.*`
- `plausibility.default.min = null`
- `plausibility.default.max = null`
- `plausibility.default.max_rate = null`
- `plausibility.default.persistence_scans = 1`
- `plausibility.default.recovery_scans = 1`
- `plausibility.by_signal = {}`
- `plausibility.by_prefix = {}`

### `frequency.*`
- `frequency.default_references = []`
- `frequency.window_size = 50`
- `frequency.threshold = 0.5`
- `frequency.enable_fft = false`

### `sqi.*`
- `sqi.weights.noise = 0.25`
- `sqi.weights.drift = 0.25`
- `sqi.weights.spikes = 0.20`
- `sqi.weights.oscillation = 0.15`
- `sqi.weights.missing = 0.15`
- `sqi.weights.stale = 0.0`
- `sqi.weights.step = 0.0`
- `sqi.weights.plausibility = 0.0`
- `sqi.thresholds.noise = 0.1`
- `sqi.thresholds.drift = 1.0`
- `sqi.thresholds.spike_frequency = 0.05`
- `sqi.thresholds.oscillation = 0.3`
- `sqi.classification.excellent = 90`
- `sqi.classification.good = 75`
- `sqi.classification.fair = 50`
- `sqi.classification.poor = 25`

### `integration.*`
- `integration.pointcore.auto_register_points = true`
- `integration.pointcore.default_point_type = "AI"`
- `integration.plcscan.enable_callbacks = true`
- `integration.plcscan.track_performance = true`
- `integration.plcscan.warn_on_overrun = true`
- `integration.plcscan.max_scan_history = 100`
- `integration.comms.track_jitter = true`
- `integration.comms.track_dropouts = true`
- `integration.comms.track_late_arrivals = true`
- `integration.comms.quality_monitor_window = 100`
- `integration.comms.max_rtt_ms = 500.0`
- `integration.comms.max_jitter_ms = 200.0`
- `integration.comms.max_dropout_streak = 3`

### `comms.*`
- `comms.enabled = false`
- `comms.thresholds.timeout_rate_degraded = 0.02`
- `comms.thresholds.timeout_rate_critical = 0.10`
- `comms.thresholds.retry_rate_degraded = 0.05`
- `comms.thresholds.retry_rate_critical = 0.20`
- `comms.thresholds.crc_rate_degraded = 0.001`
- `comms.thresholds.crc_rate_critical = 0.01`
- `comms.thresholds.jitter_ms_degraded = 250`
- `comms.thresholds.jitter_ms_critical = 750`
- `comms.thresholds.poll_cycle_ms_degraded = 2000`
- `comms.thresholds.poll_cycle_ms_critical = 5000`
- `comms.report.top_n = 10`
- `comms.budget.enabled = false`
- `comms.budget.scan_interval_ms = 1000`
- `comms.budget.bytes_per_signal_estimate = 18`
- `comms.budget.protocol_overhead_bytes = 200`
- `comms.budget.default_capacity_bps_by_type.comms_domain = 9600`
- `comms.budget.default_capacity_bps_by_type.poll_group = 9600`
- `comms.budget.default_capacity_bps_by_type.rtu = 9600`
- `comms.budget.per_node_capacity_bps = {}`
- `comms.budget.thresholds.utilization_degraded = 0.70`
- `comms.budget.thresholds.utilization_critical = 0.90`
- `comms.budget.thresholds.low_headroom = 0.10`

### `logging.*`
- `logging.level = "INFO"`
- `logging.log_scan_timing = false`
- `logging.log_quality_changes = true`
- `logging.log_anomalies = true`

### `performance.*`
- `performance.max_signals = 1000`
- `performance.buffer_preallocation = true`
- `performance.use_numpy = true`
- `performance.compute_budget_ms = null`
- `performance.load_shed_p95_window = 50`
- `performance.load_shed_oscillation_cadence = 3`
- `performance.load_shed_skip_fft = true`

### `alerts.*`
- `alerts.enable = true`
- `alerts.sqi_critical_threshold = 25`
- `alerts.sqi_warning_threshold = 50`
- `alerts.drift_alert_threshold = 5.0`
- `alerts.spike_alert_threshold = 0.1`

### `incidents.*`
- `incidents.start_sqi_threshold = 50`
- `incidents.end_sqi_threshold = 60`
- `incidents.start_persistence_scans = 5`
- `incidents.end_persistence_scans = 10`
- `incidents.critical_sqi_threshold = 25`
- `incidents.component_score_floor = 70`
- `incidents.state_retention_scans = 100000`
- `incidents.hard_fault_causes = ["missing"]`
- `incidents.emit_update_on_cause_change = true`
- `incidents.emit_update_on_severity_change = true`

### `event_filter.*`
- `event_filter.suppress_member_events = true`
- `event_filter.suppress_when_group_event_active = true`
- `event_filter.suppress_group_causes = ["comms"]`
- `event_filter.suppress_event_types = ["started", "updated"]`
- `event_filter.allow_resolved_passthrough = true`
- `event_filter.include_suppression_stats = true`

### `topology.*`
- `topology.enabled = false`
- `topology.path = ""`
- `topology.allow_orphan_signals = false`
- `topology.node_type_priority = ["comms_domain", "poll_group", "rtu", "signal"]`

### `rca.*`
- `rca.enabled = false`
- `rca.affected_policy.use_active_incidents = true`
- `rca.affected_policy.use_quality_class = true`
- `rca.affected_policy.affected_classes = ["POOR", "BAD"]`
- `rca.affected_policy.missing_ratio_threshold = 0.2`
- `rca.representative_signals_max = 12`
- `rca.supporting_incidents_max = 30`
- `rca.retention_scans = 2000`
- `rca.scoring.weights.coverage = 0.45`
- `rca.scoring.weights.concentration = 0.25`
- `rca.scoring.weights.coherence = 0.20`
- `rca.scoring.weights.signature = 0.10`
- `rca.scoring.coherence_k_scans = 5`
- `rca.scoring.min_fraction_by_type.comms_domain = 0.25`
- `rca.scoring.min_fraction_by_type.poll_group = 0.25`
- `rca.scoring.min_fraction_by_type.rtu = 0.50`
- `rca.scoring.min_fraction_by_type.signal = 1.00`
- `rca.scoring.type_score_norm.comms_domain.floor = 0.0`
- `rca.scoring.type_score_norm.comms_domain.ceiling = 1.2`
- `rca.scoring.type_score_norm.poll_group.floor = 0.0`
- `rca.scoring.type_score_norm.poll_group.ceiling = 1.2`
- `rca.scoring.type_score_norm.rtu.floor = 0.0`
- `rca.scoring.type_score_norm.rtu.ceiling = 1.2`
- `rca.scoring.type_score_norm.signal.floor = 0.0`
- `rca.scoring.type_score_norm.signal.ceiling = 1.2`
- `rca.comms_scoring.enabled = true`
- `rca.comms_scoring.leaf_comms_gate = 0.35`
- `rca.comms_scoring.coherence_k_scans = 4`
- `rca.comms_scoring.weights.comms_boost = 0.35`
- `rca.comms_scoring.weights.comms_counter = 0.25`
- `rca.comms_scoring.node_type_multiplier.comms_domain = 1.0`
- `rca.comms_scoring.node_type_multiplier.poll_group = 1.0`
- `rca.comms_scoring.node_type_multiplier.rtu = 0.5`
- `rca.comms_scoring.node_type_multiplier.signal = 0.0`
- `rca.comms_scoring.leaf_likeness_weights.missing_fraction = 0.6`
- `rca.comms_scoring.leaf_likeness_weights.coherence = 0.5`
- `rca.comms_scoring.leaf_likeness_weights.non_missing_fraction = 0.9`
- `rca.comms_scoring.normalization.utilization_degraded = 0.70`
- `rca.comms_scoring.normalization.utilization_critical = 0.90`
- `rca.comms_scoring.normalization.timeout_rate_degraded = 0.02`
- `rca.comms_scoring.normalization.timeout_rate_critical = 0.10`
- `rca.comms_scoring.normalization.jitter_ms_degraded = 250`
- `rca.comms_scoring.normalization.jitter_ms_critical = 750`
- `rca.confidence.required_scans = 2`
- `rca.confidence.margin_scale = 0.2`
- `rca.node_incidents.enabled = true`
- `rca.node_incidents.start_persistence_scans = 2`
- `rca.node_incidents.resolve_persistence_scans = 2`
- `rca.node_incidents.cooldown_scans = 5`
- `rca.node_incidents.min_confidence_to_start = 0.75`
- `rca.node_incidents.emit_updates = true`

---

## 4) Wired vs unwired runtime usage

| Key(s) in defaults | Status in runtime path | Evidence |
|---|---|---|
| `drift.sustained_window`, `drift.monotonic_window` | **Unwired** to `SignalProcessor` detector construction | `SignalProcessor` builds `DriftDetector` with only small/large thresholds; detector supports additional args internally. |
| `variance.debounce_samples` | **Unwired** to runtime detector construction | `SignalProcessor` builds `SpikeDetector` with `window_size`, `k_sigma`, `variance_calc` only. |
| `frequency.threshold` | **Unwired** in engine path | `SignalProcessor` constructs `OscillationDetector` without a threshold parameter from config. |
| `sqi.classification.*` | **Unwired** | `SignalQualityIndex._classify_quality` uses hardcoded cutoffs (90/75/50/25). |
| `performance.buffer_preallocation`, `performance.use_numpy` | **Unwired** in loader+engine hot path | `get_performance_settings` does not expose these fields and engine constructor path does not branch on them. |
| `alerts.enable` | **Unwired** | Alert level is always computed from SQI and component thresholds; no `alerts.enable` gate. |

---

## 5) Known hazards

1. **Duplicate top-level `engine:` blocks in `defaults.yaml`.**
   - YAML duplicate-key behavior means effective mapping is parser-dependent; in the current loader path (`yaml.safe_load`) later values are what survive in practice.
   - This is a determinism and maintainability risk for humans/tools.

2. **Override-key validation asymmetry.**
   - Main config override is shape/key validated via `_validate_override_keys`.
   - Groups config uses `load_groups_config` directly and does not pass through the same override schema validation contract.

---

## 6) Deterministic dump helper

Use:

```bash
python -m sqe.tools.dump_config_map [--config <main_override.yaml>] [--groups-config <groups.yaml>]
```

Behavior:
- Loads main config using `load_config`.
- Optionally loads groups config with `load_groups_config`.
- Prints flattened dotted keys in lexicographic order, with JSON-stable value formatting.
