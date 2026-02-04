# Quality Incidents

## Overview
Quality Incidents turn per scan SQI results into stable, scan driven events with
start, update, and resolution. The incident engine is deterministic and uses
only the data passed into each scan update.

## Incident lifecycle
Incidents move through three event types:

1. Started when degradation persists for a configured number of scans.
2. Updated when the dominant cause or severity changes while degraded.
3. Resolved after recovery persists for a configured number of scans.

Persistence and hysteresis prevent rapid start and stop flapping near
thresholds.

## Event schema
Each event includes:

- `event_type`: started, updated, resolved
- `message`: short actionable message
- `recommended_action`: operator guidance by cause
- `incident`: incident state
  - `incident_id`: deterministic id `signal_id:start_scan_index`
  - `signal_id`
  - `cause`: missing, noise, drift, spikes, oscillation, unknown
  - `severity`: warning, critical
  - `start_timestamp`, `last_timestamp`, `end_timestamp`
  - `min_sqi`, `last_sqi`
  - `start_scan_index`, `last_scan_index`
  - `details`: latest components, missing ratio, and alert flags

## Policy parameters
Policy controls persistence, thresholds, and updates:

- `start_sqi_threshold`: SQI at or below this is degraded.
- `end_sqi_threshold`: SQI at or above this is recovered.
- `start_persistence_scans`: scans required to start an incident.
- `end_persistence_scans`: scans required to resolve an incident.
- `critical_sqi_threshold`: SQI at or below this is critical severity.
- `component_score_floor`: component scores below this are degraded causes.
- `emit_update_on_cause_change`: emit updated event on cause change.
- `emit_update_on_severity_change`: emit updated event on severity change.

## Determinism guarantees
The incident engine is scan driven with explicit timestamps. Given identical
scan inputs, timestamps, and missing ratios, it produces identical events and
incident ids.

## OASyS integration mapping concept
Quality incidents are designed to map to derived points and events in AVEVA
OASyS Enterprise:

- Derived points: SQI score, dominant cause code, severity code.
- Event stream: incident started and incident resolved events.

The OASyS publisher now emits derived-point and event payloads through a
transport interface (for example, the JSONL transport included in the
integration module).
