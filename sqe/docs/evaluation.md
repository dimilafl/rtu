# SQE Evaluation Harness

This guide describes how to label incidents and evaluate replay outputs with
precision/recall, time-to-detect, and spam metrics.

## Label format

Labels are provided as YAML (preferred) or JSON lists. Each label describes one
expected incident interval for a signal.

```yaml
- signal_id: STATION_01_AI_001
  start_scan_index: 10
  end_scan_index: 25
  cause: missing
  severity: warning
```

Fields:

- `signal_id` (required): Signal identifier.
- `start_scan_index` (required): First scan index of the labeled incident.
- `end_scan_index` (required): Last scan index of the labeled incident (inclusive).
- `cause` (optional): Expected dominant cause.
- `severity` (optional): Expected severity.

## Running replay then evaluation

1. Run replay to generate deterministic JSONL outputs:

```
sqe replay --in scans.jsonl --config cfg.yaml --groups-config groups.yaml --out out_dir
```

2. Evaluate the replay outputs against labels:

```
sqe eval --replay-out out_dir --labels labels.yaml
```

To persist the metrics as JSON:

```
sqe eval --replay-out out_dir --labels labels.yaml --out-json metrics.json
```

## Metrics definitions

- **Detection precision/recall/F1**: matched predicted starts vs labeled intervals.
- **Mean time-to-detect (scans)**: average delay between label start and predicted
  start (clipped at 0).
- **Cause accuracy / severity accuracy**: exact match rate for labeled fields among
  matched incidents.
- **Spam metrics**:
  - `total_signal_started`: count of signal-level started incidents.
  - `total_group_started`: count of group-level started incidents.
  - `starts_ratio`: signal starts divided by `max(1, total_group_started)`.

## Event suppression impact

When station-level group incidents are active (e.g., comms dropouts), member
incident start/update events may be suppressed based on the event filter policy.
This reduces operator-facing spam while still preserving group incidents and
resolved member events. Suppressed member events are deferred and replayed in a
deterministic order once the group incident resolves, so audits can reconcile
missed events without losing the suppression benefits. The spam metrics
(`starts_ratio`) highlight this change in the ratio of signal starts to group
starts.
