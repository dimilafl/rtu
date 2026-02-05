# Comms Health MVP

The Comms Digital Twin MVP introduces deterministic comms health evidence at RTU,
poll group, and comms domain levels. It aggregates per-scan comms telemetry into
node summaries and classifies health for reporting and troubleshooting.

## Inputs

Comms health uses per-scan `CommsMetrics` records. Each record describes a
signal's transport behavior for a scan and includes the scan timestamp provided
by the caller (no wall-clock time is used):

- `scan_index` / `scan_timestamp`
- `signal_id` (optional)
- `rtu_id`, `poll_group_id` (optional), `comms_domain_id` (optional)
- `poll_cycle_ms`, `poll_jitter_ms` (optional)
- `timeout_count`, `retry_count`, `crc_error_count`
- `bytes_tx`, `bytes_rx`

## Aggregation

Metrics are aggregated per node type:

- **RTU** (always)
- **POLL_GROUP** (when `poll_group_id` is present)
- **COMMS_DOMAIN** (when `comms_domain_id` is present)

For each node and scan, the aggregate includes:

- Sample count and rate metrics (`timeout_rate`, `retry_rate`, `crc_error_rate`)
- Average poll cycle and jitter (when provided)
- Total bytes transmitted and received

## Classification

Each aggregate is classified into one of three health classes:

- `OK`
- `DEGRADED`
- `CRITICAL`

Classification uses deterministic threshold checks in a fixed order:

1. timeouts
2. retries
3. CRC errors
4. jitter
5. poll cycle

Matching thresholds add human-readable reasons (e.g. `timeout_rate_critical`) to
support troubleshooting and auditing.

## Outputs

- **comms_health.jsonl**: JSONL output containing only `DEGRADED` and
  `CRITICAL` nodes to bound volume.
- **TroubleshootReport**: When comms health is enabled and provided, the report
  includes `comms_summary` with bounded, deterministically sorted lists of
  degraded and critical nodes.

## Interpretation

- **Timeout and retry rates** indicate poll reliability issues.
- **CRC error rate** indicates link-level data corruption.
- **Jitter and poll cycle** highlight timing instability and slow cycles.

These indicators are intended for deterministic root-cause evidence and should
be interpreted alongside signal-quality outcomes.
