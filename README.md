# Signal Quality Engine (SQE)

**DSP-style signal conditioning and diagnostics for SCADA telemetry systems**

## Overview

The Signal Quality Engine (SQE) is a real-time digital signal processing system designed for SCADA environments. It sits between RTU simulators and downstream control logic, providing:

- **Signal Conditioning:** Low-pass, high-pass, and moving average filters
- **Drift Detection:** Identification of sensor degradation and trending
- **Spike Detection:** Statistical outlier detection with adaptive thresholds
- **Frequency Analysis:** Correlation-based and FFT-based oscillation detection
- **Quality Metrics:** Composite Signal Quality Index (SQI) scoring 0-100
- **Real-Time Processing:** Deterministic execution within PLC scan cycles
- **Quality Incidents:** Stable incident lifecycle events driven by SQI scans

## Key Features

### Core Capabilities

✅ **Multiple DSP Filters**
- Exponentially Weighted Moving Average (EWMA)
- High-pass filtering for trend removal
- Simple moving average

✅ **Advanced Diagnostics**
- Drift classification (sustained, transient, monotonic)
- Spike detection with configurable σ thresholds
- Low-frequency oscillation detection
- Missing sample tracking

✅ **Signal Quality Index (SQI)**
- Weighted composite metric (0-100)
- Component breakdown (noise, drift, spikes, oscillation, missing)
- Trend analysis (improving/degrading/stable)
- Quality classification (excellent/good/fair/poor/critical)

✅ **Quality Incidents**
- Incident lifecycle events: started, updated, resolved
- Persistence and hysteresis to avoid flapping
- Deterministic incident ids and timestamps

✅ **Integration Adapters**
- PointCore-Simulator adapter
- PLC_Scan_Engine adapter
- SCADA-Comms-Front-End-Processor adapter
 - Comms health aggregation and reporting

✅ **Performance**
- Deterministic, real-time execution
- No background threads or async operations
- ~0.1-0.2ms per signal per scan
- Typical scan utilization: 10-20%

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/rtu.git
cd rtu

# Install
pip install -e .

# Or with optional dependencies
pip install -e ".[all]"
```

### Basic Usage

```python
from sqe.core.engine import SignalQualityEngine

# Initialize engine
engine = SignalQualityEngine(scan_interval=0.1)

# Register signals
engine.register_signal("AI_001")
engine.register_signal("AI_002")

# Process scan
results = engine.update({
    "AI_001": 42.5,
    "AI_002": 100.2
})

# Access results
for sig_id, result in results.items():
    print(f"{sig_id}: SQI={result.sqi:.1f} ({result.quality_class})")
    if result.sqi_components:
        components = ", ".join(
            f"{name}={score:.1f}" for name, score in result.sqi_components.items()
        )
        print(f"  Components: {components}")
```

### CLI Usage

```bash
# Analyze signal from CSV file
sqe analyze --signal-file data.csv --plot

# Simulate signal processing
sqe simulate --duration 1000 --noise 1.5 --plot

# Generate incident events
sqe incidents --signal-file data.csv --out incidents.jsonl

# Deterministic replay (writes scans.jsonl + incidents.jsonl)
sqe replay --in scans.jsonl --config cfg.yaml --out out_dir

# Show version
sqe version
```

### Comms Health MVP

Enable comms health in configuration to emit deterministic comms evidence and
the `comms_health.jsonl` output during replay runs.

```yaml
comms:
  enabled: true
```

The comms health report is written to `comms_health.jsonl` in the replay output
directory. See `sqe/docs/comms_health_mvp.md` for fields and interpretation.

## Project Structure

```
sqe/
├── __init__.py
├── config/
│   └── defaults.yaml          # Default configuration
├── core/
│   ├── signal_buffer.py       # Circular buffer
│   ├── filters.py             # DSP filters (EWMA, MA, HP)
│   ├── drift.py               # Drift detection
│   ├── variance.py            # Variance & spike detection
│   ├── freq_detect.py         # Frequency analysis
│   ├── sqi.py                 # Signal Quality Index
│   ├── incidents.py           # Quality incident engine
│   └── engine.py              # Main engine
├── integration/
│   ├── pointcore_adapter.py   # PointCore integration
│   ├── plcscan_adapter.py     # PLC scan integration
│   ├── comms_adapter.py       # Comms front-end integration
│   └── publisher.py           # JSONL publisher and OASyS stub
├── ops/
│   └── service.py             # Realtime scan service wrapper
├── tests/
│   ├── test_filters.py
│   ├── test_drift.py
│   ├── test_variance.py
│   ├── test_freq.py
│   ├── test_sqi.py
│   └── test_engine.py
├── examples/
│   ├── demo_pipeline.py       # Complete pipeline demo
│   └── noisy_signal_demo.py   # Filter comparison demo
├── cli/
│   └── sqe_cli.py             # Command-line interface
└── docs/
    ├── architecture.md        # System architecture
    ├── dsp_principles.md      # DSP mathematics
    ├── integration_guide.md   # Integration instructions
    ├── incidents.md           # Incident lifecycle and schema
    └── sqi_definition.md      # SQI formula & interpretation
```

## Documentation

### Core Concepts

- **[Architecture](sqe/docs/architecture.md)** - System design and component overview
- **[DSP Principles](sqe/docs/dsp_principles.md)** - Mathematical foundations
- **[Integration Guide](sqe/docs/integration_guide.md)** - How to integrate with existing systems
- **[Quality Incidents](sqe/docs/incidents.md)** - Incident lifecycle and policy
- **[Offline tuning pipeline](sqe/docs/offline_tuning.md)** - Replay-based tuning workflow
- **[SQI Definition](sqe/docs/sqi_definition.md)** - Signal Quality Index explained

### Examples

Run the included examples to see SQE in action:

```bash
# Complete pipeline demonstration
python sqe/examples/demo_pipeline.py

# Noisy signal analysis
python sqe/examples/noisy_signal_demo.py
```

## Integration with Existing Repos

### PointCore-Simulator

```python
from sqe.integration.pointcore_adapter import PointCoreAdapter

adapter = PointCoreAdapter(engine)
adapter.register_point("AI_001")
result = adapter.process_point(point_signal)
```

### PLC_Scan_Engine

```python
from sqe.integration.plcscan_adapter import PLCScanAdapter

plc_adapter = PLCScanAdapter(engine, scan_interval=0.1)
result = plc_adapter.execute_scan(signal_values)
```

### SCADA-Comms-Front-End-Processor

```python
from sqe.integration.comms_adapter import CommsAdapter, CommsArtifact

comms_adapter = CommsAdapter(engine, artifact_config)
result = comms_adapter.process_scan(signal_values)
```

See [Integration Guide](sqe/docs/integration_guide.md) for complete details.

## Testing

Run the comprehensive test suite:

```bash
# Run all tests
pytest sqe/tests/

# Run with coverage
pytest --cov=sqe sqe/tests/

# Run specific test module
pytest sqe/tests/test_engine.py

# Run with verbose output
pytest -v sqe/tests/
```

All tests include:
- Unit tests for each component
- Integration tests for complete pipeline
- Known input/output validation
- Edge case coverage

## Configuration

### YAML Configuration

Create `sqe_config.yaml`:

```yaml
engine:
  scan_interval: 0.1

filters:
  default_ewma_alpha: 0.3
  default_ma_window: 10

drift:
  small_threshold: 0.5
  large_threshold: 5.0

sqi:
  weights:
    noise: 0.25
    drift: 0.25
    spikes: 0.20
    oscillation: 0.15
    missing: 0.15
```

### Programmatic Configuration

```python
from sqe.core.engine import SignalConfig

config = SignalConfig(
    signal_id="AI_CRITICAL",
    ewma_alpha=0.2,
    variance_window=30,
    spike_k_sigma=2.5,
    reference_frequencies=[0.1, 0.5, 1.0]
)

engine.register_signal("AI_CRITICAL", config)
```

## Performance

### Computational Complexity

- **EWMA Filter:** O(1) per sample
- **Moving Average:** O(1) amortized
- **Variance:** O(1) per sample (Welford's algorithm)
- **Drift Detection:** O(1) per sample
- **Frequency Correlation:** O(N) per frequency
- **FFT:** O(N log N) per window
- **Overall per signal:** ~0.1-0.2ms

### Memory Usage

- Per signal: ~15-20 KB
- For 100 signals: ~1.5-2 MB
- Fixed allocation, no dynamic growth

### Real-Time Constraints

Designed for deterministic execution:
- No async operations
- No threading
- Sequential processing
- Predictable timing
- PLC scan compatible

## Signal Quality Index (SQI)

The SQI is a composite metric (0-100) combining:

| Component | Weight | Meaning |
|-----------|--------|---------|
| Noise | 25% | Signal variability (coefficient of variation) |
| Drift | 25% | Signal trending and instability |
| Spikes | 20% | Frequency of outliers |
| Oscillation | 15% | Unwanted periodic components |
| Missing | 15% | Communication reliability |

**Quality Classes:**
- **90-100:** Excellent (green)
- **75-89:** Good (blue)
- **50-74:** Fair (yellow)
- **25-49:** Poor (orange)
- **0-24:** Critical (red)

See [SQI Definition](sqe/docs/sqi_definition.md) for complete formula and examples.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`pytest sqe/tests/`)
4. Commit changes (`git commit -m 'Add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## License

This project is part of a SCADA simulation stack for industrial control systems.

## Contact

For questions or support, please open an issue on GitHub.

## Acknowledgments

Built for integration with:
- [PointCore-Simulator](https://github.com/yourusername/PointCore-Simulator)
- [PLC_Scan_Engine](https://github.com/yourusername/PLC_Scan_Engine)
- [SCADA-Comms-Front-End-Processor](https://github.com/yourusername/SCADA-Comms-Front-End-Processor)

## Version History

- **1.0.0** (2025) - Initial release
  - Complete DSP pipeline
  - Integration adapters
  - Comprehensive test suite
  - Full documentation
  - CLI tool
