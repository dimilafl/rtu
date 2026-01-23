## Performance benchmark

Run the deterministic benchmark harness:

```bash
python -m sqe.tools.bench --signals 500 --scans 2000 --scan-interval 0.1 --missing-rate 0.02
```

### Interpreting results

- Total time reflects the full replay run for the configured scan count.
- Mean scan time is the average time per scan.
- P95 scan time captures tail latency for scans.
- Events per 1000 scans provides a normalized incident volume.

### What drives CPU usage

- More signals increases per scan work and memory access.
- More scans increases total runtime linearly.
- Higher missing rate can increase incident evaluations.
- Smaller scan interval increases the total scans processed for a given time span.
