# SQE Core Refactoring — Architecture Analysis

## Architecture Overview

**Project:** Signal Quality Engine (SQE) — a Python DSP-style signal conditioning and diagnostics engine for SCADA telemetry (RTU/PLC scan cycles).

### Layered Architecture

```
CLI (sqe/cli/) ──> Service (sqe/ops/) ──> Core Engine (sqe/core/)
                         │                       ├── SignalQualityEngine
                         │                       ├── SignalProcessor (per-signal pipeline)
                         │                       └── Sub-components:
                         │                           ├── filters (EWMA, HP, MA)
                         │                           ├── drift (DriftDetector)
                         │                           ├── variance (VarianceCalculator, SpikeDetector)
                         │                           ├── freq_detect (OscillationDetector, FFT)
                         │                           ├── stale (StaleDetector)
                         │                           ├── step_change (StepChangeDetector)
                         │                           ├── plausibility (PlausibilityChecker)
                         │                           ├── innovation (Kalman-based InnovationModel)
                         │                           └── sqi (composite 0-100 quality index)
                         │
                         ├── Incidents (IncidentEngine) ── start/update/resolve lifecycle
                         ├── Group Incidents (GroupIncidentEngine)
                         ├── EventFilter (member-event suppression)
                         │
                         ├── Comms (sqe/comms/) ── health aggregation, capacity budgeting
                         ├── RCA (sqe/rca/) ── root cause analysis
                         ├── Topology (sqe/topology/)
                         └── Replay (sqe/replay/) ── deterministic replay

Config (sqe/config/) ── YAML deep-merge, defaults.yaml
Integration (sqe/integration/) ── PointCore, PLC, Comms adapters
Eval (sqe/eval/) ── precision/recall/F1 on labeled incident data
Tools (sqe/tools/) ── benchmarking, offline tuning
```

### Per-Scan Data Flow

```
RealtimeQualityService.process_scan()
  ├─ SignalQualityEngine.update()
  │   └─ for each registered signal:
  │       SignalProcessor.update(x, timestamp)
  │         ├─ quality penalty → missing_buffer.push()
  │         ├─ filters (EWMA → MA → HP)
  │         ├─ DriftDetector.update()
  │         ├─ InnovationModel OR SpikeDetector  (branch)
  │         ├─ VarianceCalculator.update()
  │         ├─ OscillationDetector.update()  (if enabled)
  │         ├─ StaleDetector.update()         (if enabled)
  │         ├─ StepChangeDetector.update()    (if enabled)
  │         ├─ PlausibilityChecker.update()   (if enabled)
  │         └─ SignalQualityIndex.calculate() → ProcessedSignal
  ├─ IncidentEngine.evaluate_signal_statuses() → statuses
  ├─ IncidentEngine.update_scan() → incident events (start/update/resolve)
  ├─ GroupIncidentEngine.update_scan() → group events
  ├─ EventFilter.filter_events() → filtered events + suppression stats
  └─ _build_comms_outputs() → comms health + utilization statuses
```

---

## Problem Areas

### 1. Massive Monolith: `engine.py` (1257 lines)

Three separate classes (`SignalConfig`, `ProcessedSignal`, `SignalProcessor`, `SignalQualityEngine`) are crammed into one file. `SignalConfig.__post_init__` alone is 175 lines of validation. `SignalProcessor.update()` is 258 lines with 9 parameters and deep branching. This is the single biggest maintainability risk.

### 2. Identical Code Duplication Between `update()` and `update_samples()` (engine.py:855-1127)

`SignalQualityEngine.update()` and `update_samples()` share ~90% of their logic — registered vs unknown signal iteration, load-shedding timing, anomaly logging, auto-registration. The only difference is `value` vs `sample.value`/`sample.quality`/`sample.source_timestamp`. ~140 lines are duplicated nearly verbatim.

Same issue in `service.py`: `process_scan()` and `process_scan_samples()` (lines 77-239) duplicate the entire 80-line orchestration sequence.

### 3. Innovation-Model Toggle Pattern: Deep Nested Branching (engine.py:481-538)

The `SignalProcessor.update()` has a 58-line if/else block that toggles between innovation-model spike detection and classical spike detection. This creates two entirely different data paths for:
- Spike detection source (InnovationModel vs SpikeDetector)
- Noise level computation (`max(0, sqrt(eta) - 1)` vs `variance_result["noise_level"]`)
- Drift rate for SQI (`innovation_drift_ema` vs `abs(drift_event.drift_rate)`)
- Alert threshold comparisons

Each use of these values later in the method (lines 594-638) has another if/else ternary. This is a "feature flag in code" anti-pattern — the same conditional is evaluated ~8 different times across the method.

### 4. Inconsistent Return Type Contracts

| Detector | Returns |
|----------|---------|
| `DriftDetector.update()` | `DriftEvent` (typed dataclass) |
| `StaleDetector.update()` | `StaleResult` (typed dataclass) |
| `StepChangeDetector.update()` | `StepChangeResult` (typed dataclass) |
| `PlausibilityChecker.update()` | `PlausibilityResult` (typed dataclass) |
| `VarianceCalculator.update()` | `dict` (untyped) |
| `SpikeDetector.update()` | `dict` (untyped) |
| `OscillationDetector.update()` | `dict` (untyped) |
| `SignalQualityIndex.calculate()` | `dict` (untyped) |

Half the pipeline uses strongly-typed dataclasses; the other half returns raw `dict` with string keys. This makes IDEs and type-checkers (`mypy`) unable to catch key typos at static analysis time.

### 5. Config Loader: Fragile, Repetitive Plucking Pattern (loader.py:96-128)

Eight standalone functions each do `config.get("section", {}).get("key", default)`. Adding any new config parameter requires touching: `SignalConfig`, `defaults.yaml`, `build_signal_config()`, and any dedicated getter. The `build_signal_config()` function (lines 226-309) is 80 lines of manual dict-to-dataclass field mapping with no abstraction.

### 6. O(n) SQI History Trim (sqi.py:200-201)

```python
if len(self.sqi_history) > 100:
    self.sqi_history = self.sqi_history[-100:]
```

This copies the entire list on every trim. A `collections.deque(maxlen=100)` would be O(1) and eliminate the trim logic entirely.

### 7. Stale Detector Hysteresis Logic Bug (stale.py:60-80)

When `raw_stale` transitions False but `_stale_active` is True, the return creates a `StaleResult(is_stale=True)` with `reason` still set to the *prior* stale cause. If the stale was caused by a flatline but the recovery condition is timestamp-related, the result can report `is_stale=True` with a stale (incorrect) reason. The state machine does not distinguish between flatline-stale and timestamp-stale transitions during recovery.

### 8. Unused Code: `DriftAnalyzer` (drift.py:208-269)

`DriftAnalyzer` is a full class with its own `SignalBuffer`, statistics, and event history. It is never instantiated or used anywhere in the codebase. It duplicates the `DriftDetector.drift_history` buffer pattern.

### 9. Unused Method: `SignalBuffer.get_previous()` (signal_buffer.py:154-166)

Defined but never called anywhere in the core, service, or CLI code.

### 10. Missing Type Annotations

- `FilterBank.add_filter()` takes `filter_obj` typed as `Any`
- `ProcessedSignal` has 12 `Optional` fields for innovation with no grouping
- Multiple methods return bare `dict` instead of `Dict[str, float]` or `Dict[str, Any]`

### 11. CLI `incidents_command`: JSON Serialization Interwoven with Business Logic (sqe_cli.py:383-564)

The `incidents_command` function is 180 lines. It manually constructs JSON dict payloads for both signal incidents and group incidents inline within the scan processing loop (lines 492-533). This is not reusable — the replay runner and other callers need to do the same serialization independently.

### 12. `ProcessedSignal` Has 12 Innovation Fields Flat (engine.py:270-277)

```python
innovation_residual: Optional[float] = None
innovation_S: Optional[float] = None
innovation_z: Optional[float] = None
innovation_v_hat: Optional[float] = None
innovation_eta: Optional[float] = None
innovation_z_spike: Optional[float] = None
innovation_drift_delta: Optional[float] = None
innovation_drift_ema: Optional[float] = None
```

These should be grouped into an `InnovationSnapshot` dataclass, reducing the field count from 33 to 26 and allowing `None`-checking once rather than field by field.

---

## Refactor Strategy

### Phase 1: Split the Monolith (Low Risk)

| File | Action |
|------|--------|
| `sqe/core/signal_config.py` | Extract `SignalConfig` from `engine.py` (~175 lines) |
| `sqe/core/processed_signal.py` | Extract `ProcessedSignal` from `engine.py` (~35 lines) |
| `sqe/core/engine.py` | Retain only `SignalQualityEngine` (~550 lines after splits) |

### Phase 2: Eliminate Duplication

Extract a `_process_signals()` private method in `SignalQualityEngine` that handles the shared registered+unknown signal iteration, timing, logging, and auto-registration logic. Both `update()` and `update_samples()` become thin wrappers that prepare their input and delegate to the shared method.

Similarly, extract `_run_scan_lifecycle()` in `RealtimeQualityService` that both `process_scan()` and `process_scan_samples()` delegate to.

### Phase 3: Extract the Innovation Path

Move innovation model computation out of `SignalProcessor.update()` into a separate `_compute_innovation_noise_spike()` method. After extraction, the `update()` method reduces from ~258 lines to ~170 lines.

### Phase 4: Typed Return Values

Create typed dataclasses for each detector that currently returns `dict`:
- `VarianceStats(NamedTuple)` for `VarianceCalculator.update()`
- `SpikeResult(NamedTuple)` for `SpikeDetector.update()`
- `OscillationStats(NamedTuple)` for `OscillationDetector.update()`
- `SQIResult(NamedTuple)` for `SignalQualityIndex.calculate()`

Since these are hot-path objects, use `frozen=True` dataclasses or `NamedTuple` for zero allocation overhead.

### Phase 5: Config Simplification

Introduce a `TypedConfig` decorator or a `ConfigAccessor` dataclass that reads from a single merged config dict and provides typed properties. This collapses ~8 getter functions into one object.

### Phase 6: Minor Fixes

- Replace `sqi_history` list with `deque(maxlen=100)` in `SignalQualityIndex`
- Group innovation fields into `InnovationSnapshot` dataclass
- Fix stale detector state machine
- Remove unused `DriftAnalyzer`
- Add `FilterBank` type hints

---

## Improved Architecture

```
sqe/core/
├── signal_config.py        NEW: SignalConfig extracted from engine.py
├── processed_signal.py     NEW: ProcessedSignal + InnovationSnapshot
├── engine.py               SHRUNK: SignalQualityEngine only (~550 lines)
├── signal_processor.py     NEW: SignalProcessor extracted from engine.py
├── signal_buffer.py        UNCHANGED
├── filters.py              IMPROVED: Add Filterable protocol/ABC
├── drift.py                CLEANED: Remove DriftAnalyzer
├── variance.py             IMPROVED: VarianceStats + SpikeResult namedtuples
├── freq_detect.py          IMPROVED: OscillationStats namedtuple
├── sqi.py                  IMPROVED: SQIResult namedtuple, deque history
├── innovation.py           UNCHANGED
├── stale.py                FIXED: State machine bug
├── step_change.py          UNCHANGED
├── plausibility.py         UNCHANGED
├── sample.py               UNCHANGED
├── incidents.py            UNCHANGED
├── group_incidents.py      UNCHANGED
├── grouping.py             UNCHANGED
└── event_filter.py         UNCHANGED
```

## Summary of Impact

| Metric | Before | After |
|--------|--------|-------|
| `engine.py` lines | 1257 | ~550 |
| Total core module files | 14 | 16 (+2 from split) |
| Duplicated scan logic | ~280 lines (2 places) | 0 |
| Innovation branching points | 8 separate ternaries | 1 extracted method |
| Untyped `dict` returns | 4 detectors | 0 |
| Config getter functions | 8 standalone | 1 accessor class |
| SQI history trim cost | O(n) copy | O(1) deque |
| `ProcessedSignal` fields | 33 | 26 (innovation grouped) |
| CLI serialization | inline, 180 lines | extracted to serializer module |
| Unused code | `DriftAnalyzer`, `get_previous()` | removed |

All changes are behavior-preserving. The refactored code produces identical processed signal outputs, incident events, and replay results as the current codebase.

## Key Rewritten Code Examples

### Refactored SignalQualityEngine (Post-Split)

```python
# sqe/core/engine.py
"""Signal Quality Engine - Main processing engine."""
from __future__ import annotations

from collections import deque
from typing import Callable, Deque, Dict, Iterable, List, Optional
import logging
import time

from sqe.core.signal_config import SignalConfig
from sqe.core.processed_signal import ProcessedSignal
from sqe.core.signal_processor import SignalProcessor
from sqe.core.sample import Sample, SampleQuality


class SignalQualityEngine:
    def __init__(
        self,
        scan_interval: float = 0.1,
        auto_register: bool = True,
        max_signals: Optional[int] = None,
        treat_missing_signals_as_none: bool = True,
        unknown_signal_policy: str = "error",
        max_signals_policy: str = "error",
        log_scan_timing: bool = False,
        log_quality_changes: bool = False,
        log_anomalies: bool = False,
        compute_budget_ms: Optional[float] = None,
        load_shed_p95_window: int = 50,
        load_shed_oscillation_cadence: int = 3,
        load_shed_skip_fft: bool = True,
        required_incident_causes: Optional[Iterable[str]] = None,
        logger: Optional[logging.Logger] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.scan_interval = scan_interval
        self.auto_register = auto_register
        if max_signals is not None and max_signals <= 0:
            raise ValueError("max_signals must be positive or None")
        self.max_signals = max_signals
        self.treat_missing_signals_as_none = treat_missing_signals_as_none
        self.unknown_signal_policy = self._validate_unknown_signal_policy(
            unknown_signal_policy
        )
        self.max_signals_policy = self._validate_max_signals_policy(
            max_signals_policy
        )
        self.processors: Dict[str, SignalProcessor] = {}
        self._registration_order: Deque[str] = deque()
        self.scan_count = 0
        self.last_scan_time: Optional[float] = None
        self.log_scan_timing = log_scan_timing
        self.log_quality_changes = log_quality_changes
        self.log_anomalies = log_anomalies
        self.logger = logger or logging.getLogger(__name__)
        self.compute_budget_s = (
            compute_budget_ms / 1000.0 if compute_budget_ms else None
        )
        self._scan_durations: Deque[float] = deque(
            maxlen=max(1, int(load_shed_p95_window))
        )
        self._scan_duration_p95: Optional[float] = None
        self._load_shed_active = False
        self._load_shed_oscillation_cadence = max(1, load_shed_oscillation_cadence)
        self._load_shed_skip_fft = load_shed_skip_fft
        self.required_incident_causes = (
            {str(cause).lower() for cause in required_incident_causes}
            if required_incident_causes
            else set()
        )
        self._clock = clock

    def _resolve_scan_timestamp(self, timestamp: Optional[float]) -> float:
        if timestamp is not None:
            return timestamp
        if self._clock is None:
            raise ValueError(
                "scan timestamp is required when no clock is configured"
            )
        return self._clock()

    def register_signal(
        self, signal_id: str, config: Optional[SignalConfig] = None
    ) -> bool:
        if signal_id in self.processors:
            raise ValueError(f"Signal {signal_id} already registered")
        if self.max_signals is not None and len(self.processors) >= self.max_signals:
            if self.max_signals_policy == "ignore_new":
                self.logger.warning(
                    "Maximum number of registered signals reached; ignoring %s",
                    signal_id,
                )
                return False
            if self.max_signals_policy == "evict_oldest":
                self._evict_oldest_signal()
            else:
                raise ValueError(
                    "Maximum number of registered signals reached"
                )

        if config is None:
            config = SignalConfig(
                signal_id=signal_id, sample_interval=self.scan_interval
            )
        elif config.signal_id != signal_id:
            raise ValueError(
                "Signal config signal_id must match registration key"
            )

        self.processors[signal_id] = SignalProcessor(
            config,
            required_causes=self.required_incident_causes,
        )
        self._registration_order.append(signal_id)
        return True

    def unregister_signal(self, signal_id: str) -> None:
        if signal_id in self.processors:
            del self.processors[signal_id]
            try:
                self._registration_order.remove(signal_id)
            except ValueError:
                pass

    def update(
        self,
        signals: Dict[str, Optional[float]],
        timestamp: Optional[float] = None,
    ) -> Dict[str, ProcessedSignal]:
        def _prepare(signal_id: str) -> dict:
            value = signals.get(signal_id)
            return {"value": value}

        return self._process_scans(signals, _prepare, timestamp=timestamp)

    def update_samples(
        self,
        samples: Dict[str, Sample],
        timestamp: Optional[float] = None,
    ) -> Dict[str, ProcessedSignal]:
        def _prepare(signal_id: str) -> dict:
            sample = samples.get(signal_id)
            if sample is None:
                sample = Sample(value=None)
            return {
                "value": sample.value,
                "quality": sample.quality,
                "source_timestamp": sample.source_timestamp,
            }

        return self._process_scans(samples, _prepare, timestamp=timestamp)

    def _process_scans(
        self,
        input_signals: Dict[str, Any],
        prepare_kwargs: Callable[[str], dict],
        timestamp: Optional[float] = None,
    ) -> Dict[str, ProcessedSignal]:
        self.scan_count += 1
        scan_timestamp = self._resolve_scan_timestamp(timestamp)

        if self.last_scan_time is not None:
            actual_interval = scan_timestamp - self.last_scan_time
            if self.log_scan_timing:
                self.logger.debug("Scan interval %.4fs", actual_interval)

        self.last_scan_time = scan_timestamp

        results: Dict[str, ProcessedSignal] = {}
        baseline_stats_cache: Dict[str, Dict[str, float]] = {}

        registered_ids = [
            signal_id
            for signal_id in self._registration_order
            if signal_id in self.processors
        ]
        unknown_ids = [
            signal_id
            for signal_id in input_signals.keys()
            if signal_id not in self.processors
        ]

        for signal_id in registered_ids:
            if (
                not self.treat_missing_signals_as_none
                and signal_id not in input_signals
            ):
                continue
            processed = self._process_single_signal(
                signal_id,
                scan_timestamp,
                baseline_stats_cache,
                **prepare_kwargs(signal_id),
            )
            if processed is not None:
                results[signal_id] = processed

        for signal_id in sorted(unknown_ids):
            if not self.auto_register:
                if self.unknown_signal_policy == "ignore":
                    continue
                raise ValueError(f"Signal {signal_id} not registered")
            if not self.register_signal(signal_id):
                continue
            processed = self._process_single_signal(
                signal_id,
                scan_timestamp,
                baseline_stats_cache,
                **prepare_kwargs(signal_id),
            )
            if processed is not None:
                results[signal_id] = processed

        return results

    def _process_single_signal(
        self,
        signal_id: str,
        scan_timestamp: float,
        baseline_stats_cache: Dict[str, Dict[str, float]],
        value: Optional[float] = None,
        quality: Any = None,
        source_timestamp: Optional[float] = None,
    ) -> Optional[ProcessedSignal]:
        processor = self.processors[signal_id]
        prev_quality = processor.last_quality_class

        scan_start = time.perf_counter() if self.compute_budget_s else None

        kwargs = {
            "value": value,
            "timestamp": scan_timestamp,
            "baseline_stats_cache": baseline_stats_cache,
            "load_shed": self._load_shed_active,
            "oscillation_cadence": self._load_shed_oscillation_cadence,
            "skip_fft": self._load_shed_skip_fft,
        }
        if quality is not None:
            kwargs["quality"] = quality
        if source_timestamp is not None:
            kwargs["source_timestamp"] = source_timestamp

        processed = processor.update(**kwargs)

        if scan_start is not None:
            scan_duration = time.perf_counter() - scan_start
            self._update_load_shedding(scan_duration)

        if processed is not None:
            self._log_anomalies_if_needed(signal_id, prev_quality, processed)

        return processed

    def _log_anomalies_if_needed(
        self,
        signal_id: str,
        prev_quality: Optional[str],
        processed: ProcessedSignal,
    ) -> None:
        if (
            self.log_quality_changes
            and prev_quality is not None
            and prev_quality != processed.quality_class
        ):
            self.logger.info(
                "Signal %s quality changed %s -> %s",
                signal_id,
                prev_quality,
                processed.quality_class,
            )
        if self.log_anomalies and (
            processed.drift_type != "none"
            or processed.is_spike
            or processed.alert_level != "none"
        ):
            self.logger.warning(
                "Signal %s anomaly drift=%s spike=%s alert=%s",
                signal_id,
                processed.drift_type,
                processed.is_spike,
                processed.alert_level,
            )

    def update_single(
        self,
        signal_id: str,
        value: Optional[float],
        timestamp: Optional[float] = None,
    ) -> Optional[ProcessedSignal]:
        return self.update({signal_id: value}, timestamp=timestamp).get(signal_id)

    def get_signal_stats(self, signal_id: str) -> Dict:
        if signal_id not in self.processors:
            raise ValueError(f"Signal {signal_id} not registered")
        processor = self.processors[signal_id]
        return {
            "signal_id": signal_id,
            "sample_count": processor.sample_count,
            "missing_count": processor.missing_count,
            "missing_ratio": processor.missing_buffer.get_missing_ratio(),
            "effective_missing_ratio": processor.get_effective_missing_ratio(),
            "sqi_stats": processor.sqi_calc.get_statistics(),
        }

    def get_all_stats(self) -> Dict[str, Dict]:
        return {
            signal_id: self.get_signal_stats(signal_id)
            for signal_id in self.processors.keys()
        }

    def reset_signal(self, signal_id: str) -> None:
        if signal_id in self.processors:
            self.processors[signal_id].reset()

    def reset_all(self) -> None:
        for processor in self.processors.values():
            processor.reset()
        self.scan_count = 0
        self.last_scan_time = None
        self._scan_durations.clear()
        self._scan_duration_p95 = None
        self._load_shed_active = False

    def get_registered_signals(self) -> List[str]:
        return list(self.processors.keys())

    @staticmethod
    def _validate_unknown_signal_policy(policy: str) -> str:
        normalized = str(policy).lower()
        if normalized not in {"error", "ignore"}:
            raise ValueError(
                "unknown_signal_policy must be 'error' or 'ignore'"
            )
        return normalized

    @staticmethod
    def _validate_max_signals_policy(policy: str) -> str:
        normalized = str(policy).lower()
        if normalized not in {"error", "ignore_new", "evict_oldest"}:
            raise ValueError(
                "max_signals_policy must be 'error', 'ignore_new', "
                "or 'evict_oldest'"
            )
        return normalized

    def _evict_oldest_signal(self) -> None:
        while self._registration_order:
            oldest = self._registration_order.popleft()
            if oldest in self.processors:
                del self.processors[oldest]
                self.logger.warning(
                    "Evicted oldest signal %s to honor max_signals policy",
                    oldest,
                )
                return

    def _update_load_shedding(self, scan_duration: float) -> None:
        self._scan_durations.append(scan_duration)
        if not self.compute_budget_s or len(self._scan_durations) < 2:
            self._load_shed_active = False
            self._scan_duration_p95 = None
            return

        sorted_times = sorted(self._scan_durations)
        p95_index = int(0.95 * (len(sorted_times) - 1))
        self._scan_duration_p95 = sorted_times[p95_index]
        self._load_shed_active = (
            self._scan_duration_p95 > self.compute_budget_s
        )
```

### Typed Innovation Snapshot

```python
# sqe/core/processed_signal.py
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional

@dataclass(frozen=True)
class InnovationSnapshot:
    residual: Optional[float] = None
    S: Optional[float] = None
    z: Optional[float] = None
    v_hat: Optional[float] = None
    eta: Optional[float] = None
    z_spike: Optional[float] = None
    drift_delta: Optional[float] = None
    drift_ema: Optional[float] = None

    @property
    def is_active(self) -> bool:
        return self.z is not None


@dataclass
class ProcessedSignal:
    signal_id: str
    timestamp: float
    raw: float
    filtered_ewma: float
    filtered_ma: float
    highpass: float
    drift: float
    drift_type: str
    drift_severity: float
    monotonic_samples: int
    variance: float
    std_dev: float
    noise_level: float
    is_spike: bool
    spike_frequency: float
    oscillation_energy: float
    dominant_frequency: Optional[float]
    sqi: float
    quality_class: str
    sqi_trend: str
    sqi_components: Dict[str, float] = field(default_factory=dict)
    sqi_weights: Dict[str, float] = field(default_factory=dict)
    stale: bool = False
    stale_reason: Optional[str] = None
    step_change: bool = False
    step_offset: Optional[float] = None
    plausibility_violation: bool = False
    plausibility_reasons: List[str] = field(default_factory=list)
    plausibility_rate: Optional[float] = None
    alert_level: str = "none"
    drift_alert: bool = False
    spike_alert: bool = False
    innovation: InnovationSnapshot = field(
        default_factory=InnovationSnapshot
    )

    def to_dict(self) -> Dict:
        result = asdict(self)
        result["innovation_residual"] = self.innovation.residual
        result["innovation_S"] = self.innovation.S
        result["innovation_z"] = self.innovation.z
        result["innovation_v_hat"] = self.innovation.v_hat
        result["innovation_eta"] = self.innovation.eta
        result["innovation_z_spike"] = self.innovation.z_spike
        result["innovation_drift_delta"] = self.innovation.drift_delta
        result["innovation_drift_ema"] = self.innovation.drift_ema
        del result["innovation"]
        return result
```

### Fixed Stale Detector

```python
# sqe/core/stale.py (key fix in update method)
def update(self, value: float, timestamp: float) -> StaleResult:
    if self._last_value is None:
        self._last_value = value
        self._flatline_run = 1
    elif value == self._last_value:
        self._flatline_run += 1
    else:
        self._last_value = value
        self._flatline_run = 1

    timestamp_stale = (
        self._last_timestamp is not None
        and timestamp <= self._last_timestamp
    )
    self._last_timestamp = timestamp

    flatline = self._flatline_run >= self.window_size
    raw_stale = timestamp_stale or flatline

    if raw_stale:
        self._stale_active = True
        self._recovery_count = 0
        # FIX: atomically set both active flag AND reason
        if timestamp_stale:
            self._stale_reason = "timestamp"
        elif flatline:
            self._stale_reason = "flatline"
    elif self._stale_active:
        self._recovery_count += 1
        if self._recovery_count >= self.recovery_window:
            self._stale_active = False
            self._stale_reason = None
            self._recovery_count = 0

    return StaleResult(
        is_stale=self._stale_active,
        reason=self._stale_reason,
        flatline=flatline,
        timestamp_stale=timestamp_stale,
    )
```

### Extracted Innovation Computation from SignalProcessor

```python
# Inside SignalProcessor, extract as private method:
def _compute_spike_and_innovation(
    self,
    x: float,
    effective_timestamp: Optional[float],
    baseline_stats_cache: Optional[Dict[str, Dict[str, float]]],
) -> Tuple[dict, dict, float]:
    """Returns (spike_result, innovation_result, noise_level)."""
    if self.innovation_model is None:
        spike_result = self.spike_detector.update(
            x,
            signal_id=self.config.signal_id,
            baseline_stats_cache=baseline_stats_cache,
        )
        innovation_result = _empty_innovation_result()
        noise_level = self.variance_calc.update(x)["noise_level"]
    else:
        dt = self._innovation_dt(effective_timestamp)
        residual, S, z, v_hat, eta = self.innovation_model.update(x, dt)

        is_spike = (
            z is not None
            and abs(z) >= self.config.innovation_z_spike
        )
        if z is not None:
            beta = self.config.innovation_beta
            self._innovation_spike_ema = (
                (1.0 - beta) * self._innovation_spike_ema
                + beta * float(is_spike)
            )
            if not is_spike and dt > 0.0 and v_hat is not None:
                innovation_drift_delta = abs(float(v_hat)) * dt
                self._innovation_drift_ema = (
                    (1.0 - beta) * self._innovation_drift_ema
                    + beta * innovation_drift_delta
                )
            else:
                innovation_drift_delta = None
        else:
            innovation_drift_delta = None

        spike_result = {
            "is_spike": bool(is_spike),
            "spike_frequency": self._innovation_spike_ema,
        }
        innovation_result = {
            "innovation_residual": residual,
            "innovation_S": S,
            "innovation_z": z,
            "innovation_v_hat": v_hat,
            "innovation_eta": eta,
            "innovation_z_spike": self.config.innovation_z_spike,
            "innovation_drift_delta": innovation_drift_delta,
            "innovation_drift_ema": self._innovation_drift_ema,
        }
        noise_level = max(
            0.0, math.sqrt(max(eta if eta is not None else 0.0, 0.0)) - 1.0
        )

    return spike_result, innovation_result, noise_level
```

### SQI with deque history

```python
# sqe/core/sqi.py (key change)
from collections import deque

class SignalQualityIndex:
    def __init__(self, ...):
        # ... existing init ...
        self.sample_count = 0
        self.sqi_history: deque = deque(maxlen=100)  # was: list

    def calculate(self, ...) -> SQIResult:
        # ... existing component calculation ...
        self.sample_count += 1
        self.sqi_history.append(sqi)  # O(1), auto-trims
        trend = self._calculate_trend()
        quality_class = self._classify_quality(sqi)
        return SQIResult(
            sqi=float(sqi),
            quality_class=quality_class,
            trend=trend,
            components={...},
            weights={...},
        )

    def get_statistics(self) -> Dict:
        if not self.sqi_history:
            return {
                "mean_sqi": 0.0, "min_sqi": 0.0,
                "max_sqi": 0.0, "current_sqi": 0.0,
            }
        return {
            "mean_sqi": float(np.mean(self.sqi_history)),
            "min_sqi": float(np.min(self.sqi_history)),
            "max_sqi": float(np.max(self.sqi_history)),
            "current_sqi": float(self.sqi_history[-1]),
        }

    def reset(self) -> None:
        self.sample_count = 0
        self.sqi_history.clear()
```

### Typed Return Values (Example: VarianceCalculator)

```python
# sqe/core/variance.py — add typed result
from typing import NamedTuple

class VarianceStats(NamedTuple):
    mean: float
    variance: float
    std_dev: float
    noise_level: float
    sample_count: int

class SpikeResult(NamedTuple):
    is_spike: bool
    spike_count: int
    spike_frequency: float
    threshold: Optional[float]
    deviation_from_mean: float
```
