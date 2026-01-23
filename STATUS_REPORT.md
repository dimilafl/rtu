# Status Report

Commit tested: `6651b23ac1c3c428eeff14c733f0c9841d8d9f5e`

## Build / Tests
- `pytest -q`: **PASS** (146 passed)

## Replay Determinism
- Replay runs: `/tmp/replay_run_1` vs `/tmp/replay_run_2`
- `diff -u` incidents/group incidents: **clean (no diffs)**

## Fixture Incident Counts
From `sqe/tests/fixtures/replay/scans.jsonl` replay:
- incidents.jsonl: started=2, updated=0, resolved=0
- group_incidents.jsonl: started=1, updated=0, resolved=0

## Grouping Smoke Check (CSV -> incidents CLI)
- Created minimal CSV with two station_1 signals missing together.
- incidents.jsonl: started=2, updated=0, resolved=0
- group_incidents.jsonl: started=1, updated=0, resolved=0

## Benchmark Baseline
- Command: `python sqe/tools/bench.py --signals 200 --scans 2000 --scan-interval 0.1 --missing-rate 0.02`
- **Result:** Unable to complete within reasonable time in this environment (manually interrupted after prolonged runtime). No baseline numbers captured.

## TODOs (next iteration)
1. Optimize `bench.py` path (frequency detection + step detection hot spots) to complete under reasonable runtime for 200x2000 scans.
2. Add optional `--config` or `--fast` flags to bench to disable FFT-heavy paths and expose deterministic performance profiles.
3. Consider caching per-signal baseline stats to reduce per-scan numpy mean calls.
4. Add benchmark progress logging (every N scans) to make long runs observable.
5. Add a replay determinism CI check that diffs outputs against golden fixture outputs.
6. Expand grouping tests to assert stable member ordering and group incident IDs across runs.
7. Add a lightweight CLI fixture for incidents to validate schema shape in CI.
