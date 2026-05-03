# PRD: SQE Core Refactoring — Structural Remediation

## Problem

The `sqe/core/` module has accumulated structural debt: three classes cohabitate a 1257-line `engine.py`, the innovation-model toggle creates 8 separate branching points in the hot path, two pairs of methods (`update`/`update_samples` in both engine and service) duplicate ~280 lines of orchestration logic, and four detectors return untyped dicts while four return typed dataclasses. These issues slow onboarding, make bugs harder to catch statically, and complicate future feature work like adding new anomaly detectors.

## Stakeholder Need

Engineering team needs the codebase to be modular, statically analyzable (mypy), and free of duplicated logic so that: (a) new engineers understand the data flow in under an hour, (b) adding a new detector or SQI component is a single-file change, and (c) the CI pipeline can type-check the entire hot path.

## Scope

### In Scope

- Split `engine.py` into `signal_config.py`, `processed_signal.py`, `signal_processor.py`, and a slimmed `engine.py`
- Eliminate duplication between `update()` and `update_samples()` in engine and service
- Extract innovation-model path into a single private method
- Replace untyped dict returns with frozen dataclasses/NamedTuples
- Replace SQI history list with `deque(maxlen=100)`
- Group innovation fields into `InnovationSnapshot`
- Fix stale detector state machine bug
- Remove unused `DriftAnalyzer` class
- Add type hints to `FilterBank`

### Out of Scope

- Changing any DSP algorithm or numerical behavior
- Refactoring `sqe/comms/`, `sqe/rca/`, `sqe/integration/`
- Changing YAML config schema or loader contract
- Adding new features (e.g., new detectors, new CLI commands)
- Performance optimization beyond the history trim fix

## Requirements

1. **Split engine.py** — `SignalConfig` lives in `sqe/core/signal_config.py`, `ProcessedSignal` and `InnovationSnapshot` live in `sqe/core/processed_signal.py`, `SignalProcessor` lives in `sqe/core/signal_processor.py`. `SignalQualityEngine` remains in `engine.py`.
2. **Eliminate `update()`/`update_samples()` duplication** — both `SignalQualityEngine.update()` and `update_samples()` delegate to a single private `_process_scans()` method. Same for `RealtimeQualityService.process_scan()` and `process_scan_samples()`.
3. **Extract innovation computation** — `SignalProcessor.update()` calls a private `_compute_spike_and_innovation()` that handles both paths and returns a unified `(spike_result, innovation_result, noise_level)` triple.
4. **Typed return values** — `VarianceCalculator.update()` returns `VarianceStats` (NamedTuple), `SpikeDetector.update()` returns `SpikeResult` (NamedTuple), `OscillationDetector.update()` returns `OscillationStats` (NamedTuple), `SignalQualityIndex.calculate()` returns `SQIResult` (NamedTuple).
5. **Group innovation fields** — `ProcessedSignal` gets a single `innovation: InnovationSnapshot` field instead of 8 flat Optional fields. `to_dict()` preserves backward-compatible flat keys.
6. **SQI history as deque** — `SignalQualityIndex.sqi_history` becomes `deque(maxlen=100)`. Remove manual trim.
7. **Fix stale detector** — `StaleDetector.update()` atomically sets `_stale_reason` and `_stale_active` on raw transitions, no stale reason leakage during recovery.
8. **Remove dead code** — Delete `DriftAnalyzer` class and `SignalBuffer.get_previous()` method.
9. **Type hints** — `FilterBank.add_filter()` parameter gets proper type annotation.
10. **Determinism preserved** — All 146 existing tests pass identically. Replay output bit-for-bit identical.

## Constraints

- Python >= 3.8 compatibility (no `match`/`case`, no `|` unions in types)
- Zero performance regression on the hot path (no extra allocations per scan)
- Existing public API signatures unchanged (all callers in `sqe/cli/`, `sqe/ops/`, `sqe/replay/`, `sqe/tools/` continue to work)
- NamedTuples/dataclasses on the hot path must be `frozen=True` to match current dict read-only semantics

## Success Criteria

- `python -m pytest sqe/tests/ tests/ -q` passes 146 tests with zero delta
- `python -m mypy sqe/core/ --strict` passes with zero errors on the refactored files
- `sqe replay --in vectors/scans.jsonl --config vectors/cfg.yaml --out /tmp/replay_test` produces `expected_incidents.jsonl` and `expected_group_incidents.jsonl` byte-for-byte identical to `vectors/`
- `engine.py` under 600 lines, `update()` method under 15 lines (delegates to `_process_scans`)

---

## Implementation Tasks

Dependencies are marked with `→`. Tasks without dependencies can run in parallel.

### T1. [SPIKE] Verify current test baseline

Run `pytest sqe/tests/ tests/ -q --tb=short` and record the exact passing count and any skips/xfails. Confirm vector replay determinism: `sqe replay --in sqe/vectors/scans.jsonl --config sqe/vectors/cfg.yaml --groups-config sqe/vectors/groups.yaml --out /tmp/rtu_vectors_test && diff /tmp/rtu_vectors_test/incidents.jsonl sqe/vectors/expected_incidents.jsonl && diff /tmp/rtu_vectors_test/group_incidents.jsonl sqe/vectors/expected_group_incidents.jsonl`. Capture golden hashes.

**Owner:** one person, 15 min.

### T2. Split `engine.py` — extract `SignalConfig` and `ProcessedSignal`

Create `sqe/core/signal_config.py` (move `SignalConfig` class, imports unchanged), create `sqe/core/processed_signal.py` (move `ProcessedSignal` + add `InnovationSnapshot` frozen dataclass). Update all imports in `engine.py`, `incidents.py`, `event_filter.py`, `service.py`, `loader.py`, `cli/sqe_cli.py`.

**Depends:** T1. **Parallel with:** T3.

### T3. Split `engine.py` — extract `SignalProcessor`

Create `sqe/core/signal_processor.py`. Move the `SignalProcessor` class. The `_innovation_dt` and `_compute_spike_and_innovation` methods go here during T5. Update imports.

**Depends:** T1. **Parallel with:** T2.

### T4. Eliminate `update()`/`update_samples()` duplication in engine

Refactor `SignalQualityEngine.update()` and `update_samples()` to delegate to a new private `_process_scans(input_signals, prepare_kwargs_fn, timestamp)`. Extract shared logging into `_log_anomalies_if_needed()`. Extract per-signal processing into `_process_single_signal()`. Target: `update()` becomes ~12 lines, `update_samples()` ~14 lines.

**Depends:** T3 (needs SignalProcessor in its own module).

### T5. Extract innovation computation path

Create `SignalProcessor._compute_spike_and_innovation()` private method that handles both innovation-model and classical paths, returning `(spike_result: dict, innovation_result: dict, noise_level: float)`. The `update()` method calls this once and assigns results. Removes ~40 lines from `update()` and consolidates 8 branching ternaries into 1 call site.

**Depends:** T3.

### T6. Typed return values for detectors

Create four NamedTuples: `VarianceStats`, `SpikeResult` in `variance.py`, `OscillationStats` in `freq_detect.py`, `SQIResult` in `sqi.py`. Update return statements in each detector. Update callers in `SignalProcessor.update()` (and `_compute_spike_and_innovation()`) to use attribute access instead of dict key access. This is type-safe: mypy catches missed key-to-attribute conversions.

**Depends:** T3. **Parallel with:** T5, T7, T8, T9.

### T7. Replace SQI history list with deque

Change `self.sqi_history: list` to `self.sqi_history: deque` with `maxlen=100` in `SignalQualityIndex.__init__()`. Remove the `if len > 100: trim` block from `calculate()`. `append()` now handles trimming implicitly.

**Depends:** T1. **Parallel with:** T5, T6, T8, T9, T10.

### T8. Fix stale detector state machine

In `StaleDetector.update()`, set `self._stale_reason` inside the `raw_stale` branch only. Remove the separate `if timestamp_stale: ... elif flatline: ...` that currently lives outside the raw_stale guard. This ensures `reason` and `is_stale` stay consistent during recovery.

**Depends:** T1. **Parallel with:** T5, T6, T7, T9, T10.

### T9. Remove dead code

Delete `DriftAnalyzer` class from `drift.py`. Delete `SignalBuffer.get_previous()` method. Run grep across entire codebase to confirm zero references. Remove any test fixtures or imports referencing them.

**Depends:** T1. **Parallel with:** T5, T6, T7, T8, T10.

### T10. Eliminate service-layer scan duplication

Refactor `RealtimeQualityService.process_scan()` and `process_scan_samples()` to delegate to a private `_run_scan_lifecycle(scan_values_or_samples, timestamp, is_samples, ...)`. Both public methods become thin wrappers. Extracts ~80 lines of shared orchestration.

**Depends:** T4 (must match engine's new contract). **Parallel with:** T5, T6, T7, T8, T9.

### T11. Add type hints to FilterBank

Change `FilterBank` to use a protocol or base class for the filter parameter. Update `add_filter(name, filter_obj)` signature.

**Depends:** T1. **Parallel with:** T5-T10.

### T12. [INTEGRATION] Re-run full test + determinism suite

Run `pytest sqe/tests/ tests/ -q --tb=short`. Confirm 146 passing. Run vector replay determinism check from T1. Run `mypy sqe/core/ --strict` and fix any remaining type errors. Run `python -m sqe.cli.sqe_cli replay --in sqe/vectors/scans.jsonl --config sqe/vectors/cfg.yaml --out /tmp/final_test` and diff against golden files.

**Depends:** T2-T11 all complete.

### T13. Update `sqe/__init__.py` and `STATUS_REPORT.md`

Verify `__init__.py` exports still work (import paths may need updating if re-exports are used). Update `STATUS_REPORT.md` with new commit hash and refactoring notes.

**Depends:** T12.

---

## Dependency Graph

```
T1 (baseline)
 ├── T2 (split config + signal) ──────────────────────────────────┐
 ├── T3 (split processor) ──────┬── T4 (dedup engine) ── T10 (dedup service) ──┐
 │                              └── T5 (extract innovation) ────────────────────┤
 ├── T6 (typed returns) ────────────────────────────────────────────────────────┤
 ├── T7 (deque history) ────────────────────────────────────────────────────────┤
 ├── T8 (stale fix) ────────────────────────────────────────────────────────────┤
 ├── T9 (dead code) ────────────────────────────────────────────────────────────┤
 └── T11 (type hints) ──────────────────────────────────────────────────────────┤
                                                                                │
                                          T12 (integration) <──────────────────┘
                                           └── T13 (docs)
```

**Parallelizable:** T2, T3, T6, T7, T8, T9, T11 can all start after T1.  
**Sequential:** T4 depends on T3. T10 depends on T4. T12 gates all. T13 gates on T12.
