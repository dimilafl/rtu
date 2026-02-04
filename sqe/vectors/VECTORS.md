# SQE Portability Vectors

These vectors define the cross-language replay contract. A non-Python port
must produce byte-for-byte identical outputs for the inputs in this folder.

## Files
- `scans.jsonl`: replay scan inputs (order preserved).
- `cfg.yaml`: SQE configuration.
- `groups.yaml`: grouping configuration.
- `expected_incidents.jsonl`: expected signal incident events.
- `expected_group_incidents.jsonl`: expected group incident events.
- `golden_metrics.json`: SQI and performance fence thresholds.
- `schema_snapshot.json`: schema hash for versioning fences.

## Deterministic rules
1. **Input scan order is preserved.** Process scans in the exact order provided
   in `scans.jsonl`.
2. **Timestamp usage is literal.** Use the provided `timestamp` (and
   `source_timestamp` when present) without modification.
3. **Per-scan event ordering** in outputs:
   - Signal events sorted by `(signal_id, event_type)`.
   - Group events sorted by `(group_id, event_type)`.
4. **JSON canonicalization**:
   - Sort keys (`sort_keys=True`).
   - Emit newline-terminated JSONL (one JSON object per line, ending in `\n`).
5. **Schema stability**: do not add or remove fields without updating these
   vectors and their tests (bump `schema_version` when schema changes).
