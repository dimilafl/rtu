# Root Cause Analysis (RCA) Notes

## Comms-aware scoring terms

RCA scoring includes comms-aware terms that activate only when leaf evidence
looks comms-like (missing-heavy with coherent onsets) **and** comms budget/health
metrics are available. The terms are reported in `score_components` for each
candidate:

- `comms_boost`: Increases the score for comms-domain, poll-group, or RTU nodes
  when the leaf comms-likeness gate is met and comms budget evidence (utilization,
  timeout rate, jitter) is elevated.
- `comms_counter`: Decreases the score when leaf comms-likeness is high but
  comms budget evidence is not elevated, helping avoid over-attribution.

These terms are bounded, deterministic, and only applied for comms-relevant node
types. They do not change per-signal scoring semantics.
