# Comms Digital Twin v2 – Track A Budgeting

This document describes the deterministic capacity budgeting and utilization evidence for comms nodes (RTU, poll group, comms domain).

## Inputs

- **TopologySnapshot**: Provides the topology structure and node ordering.
- **CommsAggregate**: Provides per-scan comms byte counts.
- **BudgetConfig**: Configuration for scan interval, byte estimates, capacity, and thresholds.

## Formulas

- **Descendant signal count**: Precomputed once per `TopologySnapshot` as the number of descendant `SIGNAL` nodes.
- **Expected bytes**:
  - `expected_bytes = protocol_overhead_bytes + bytes_per_signal_estimate * descendant_signal_count`
- **Observed bytes**:
  - `observed_bytes = bytes_tx_total + bytes_rx_total`
- **Observed bitrate**:
  - `observed_bps = observed_bytes * 8 / (scan_interval_ms / 1000)`
- **Utilization**:
  - `utilization = observed_bps / capacity_bps`
- **Headroom**:
  - `headroom = 1.0 - utilization`

## Determinism

- All calculations use `scan_timestamp` from inputs and `scan_interval_ms` from configuration.
- Node iteration order is stable and explicit: comms domain → poll group → RTU, with node IDs sorted ascending.
- Reason ordering is fixed and deterministic in the emitted status objects.

## Limitations

- **Protocol variability**: The expected bytes model is a deterministic estimate and does not capture protocol-specific overheads.
- **Burstiness**: Short bursts can momentarily exceed expected rates without indicating sustained saturation.
- **Non-poll traffic**: Out-of-band traffic is included in observed bytes and may skew utilization.

## Capacity overrides

- Use `default_capacity_bps_by_type` to define the baseline capacity for each node type.
- Use `per_node_capacity_bps` to override capacity for specific nodes by ID.
- Thresholds for degraded/critical utilization and low headroom are in `budget.thresholds`.
