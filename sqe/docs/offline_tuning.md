# Offline tuning pipeline

This pipeline runs replay-based sweeps to tune incident policy and SQI
configuration using quantitative metrics instead of manual inspection.

## Metrics gates

The offline tuning workflow uses the existing `compute_metrics` output as
hard gates:

- `detection_f1` (minimum allowed F1 score)
- `mean_time_to_detect_scans` (maximum allowed time to detect)
- `spam_metrics.starts_ratio` (maximum allowed spam ratio)

Gates are configured in the sweep YAML so that runs that fail a gate are
marked `passes_gates: false` and excluded from best-run selection.

## Parameter sweep: incident policy

Default incident policy values live in `sqe/config/defaults.yaml`:

- `start_sqi_threshold`: 50
- `end_sqi_threshold`: 60
- `start_persistence_scans`: 5
- `end_persistence_scans`: 10
- `critical_sqi_threshold`: 25

Use the sweep config to enumerate candidate values and run the replay +
eval loop with each variant. The sweep produces per-run configs and metrics
in `out-dir/incident_policy`.

## Component weighting sweep

SQI weights and thresholds are defined in `sqe/config/defaults.yaml` under
`sqi.weights` and `sqi.thresholds`. The sweep config lets you vary weights
and thresholds independently, with an optional normalization step to keep the
weight sum at 1.0 for explainability.

## Signal churn assumptions

Replay tuning should lock down missing-signal semantics so results are
repeatable across runs:

- `engine.treat_missing_signals_as_none`: whether missing registered signals
  count as missing samples or are skipped.
- `engine.unknown_signal_policy`: whether unknown signals are ignored or cause
  errors when `auto_register` is disabled.
- `engine.max_signals_policy`: how to handle caps if the replay includes more
  signals than `performance.max_signals`.

Set these explicitly in the base config so sweep results are deterministic.

## Running the pipeline

Use the CLI command to run offline tuning:

```bash
python -m sqe.cli.sqe_cli offline-tuning \
  --replay-input /path/to/replay.jsonl \
  --labels /path/to/labels.yaml \
  --sweep-config sqe/config/tuning_defaults.yaml \
  --out-dir /tmp/sqe-tuning
```

Optional flags:

- `--base-config`: path to a config overlay on top of defaults
- `--groups-config`: path to group incident config
- `--mode`: `incident_policy`, `sqi`, or `all`

## Outputs

Each sweep writes:

- `summary.json`: high-level best-run and gate summary
- `results.jsonl`: per-run metrics with overrides
- `config.yaml`: the exact config used per run
- `incidents.jsonl` / `group_incidents.jsonl`: replay outputs for auditing

Use `summary.json` to compare the best run's metrics against the gates and
verify that detection improves without increasing spam ratio.
