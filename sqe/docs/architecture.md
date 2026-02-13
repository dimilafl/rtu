# Signal Quality Engine (SQE) Architecture

## Overview

The Signal Quality Engine (SQE) is a real-time digital signal processing system designed for SCADA telemetry analysis. It sits between RTU simulators and downstream control logic, providing signal conditioning, quality assessment, and anomaly detection.

## System Position

```
RTU Simulator → Comms Front-End → Signal Quality Engine → Downstream Logic/Alarms/HMI
```

## High-Level Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                   Signal Quality Engine                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Filters    │  │    Drift     │  │  Variance    │    │
│  │              │  │  Detection   │  │  Analysis    │    │
│  │  • EWMA      │  │              │  │              │    │
│  │  • High-Pass │  │  • Small     │  │  • Sliding   │    │
│  │  • Moving Avg│  │  • Large     │  │    Window    │    │
│  │              │  │  • Monotonic │  │  • Spike Det │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  Frequency   │  │     SQI      │  │    Engine    │    │
│  │  Detection   │  │  Calculator  │  │              │    │
│  │              │  │              │  │  • Signal    │    │
│  │  • Corr-     │  │  • Weighted  │  │    Registry  │    │
│  │    based     │  │    Composite │  │  • Scan      │    │
│  │  • FFT       │  │  • Trending  │  │    Control   │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Integration Layer

```
┌─────────────────────────────────────────────────────────────┐
│                   Integration Adapters                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐  ┌──────────────────┐               │
│  │   PointCore      │  │   PLC Scan       │               │
│  │   Adapter        │  │   Adapter        │               │
│  │                  │  │                  │               │
│  │  • Point         │  │  • Scan Timing   │               │
│  │    Registration  │  │  • Deterministic │               │
│  │  • Quality       │  │    Execution     │               │
│  │    Mapping       │  │  • Performance   │               │
│  │                  │  │    Metrics       │               │
│  └──────────────────┘  └──────────────────┘               │
│                                                             │
│  ┌──────────────────┐                                      │
│  │   Comms          │                                      │
│  │   Adapter        │                                      │
│  │                  │                                      │
│  │  • Jitter        │                                      │
│  │  • Dropouts      │                                      │
│  │  • Late Arrivals │                                      │
│  │  • Quality Track │                                      │
│  └──────────────────┘                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Component Descriptions

### 1. Signal Buffer (`signal_buffer.py`)

Circular buffer for efficient signal history storage.

**Features:**
- Fixed-capacity FIFO queue
- Missing sample tracking
- Efficient numpy array conversion

**Used by:** All window-based algorithms

### 2. Filters (`filters.py`)

Digital signal processing filters for noise reduction.

**Types:**
- **EWMA (Low-Pass):** Exponential smoothing for noise reduction
- **High-Pass:** DC removal and trend elimination
- **Moving Average:** Uniform window averaging

**Use Cases:**
- Noise reduction before analysis
- Trend removal
- Feature extraction

### 3. Drift Detection (`drift.py`)

Detects and classifies signal drift patterns.

**Capabilities:**
- Discrete derivative calculation
- Sustained drift detection
- Monotonic trend identification
- Transient anomaly detection

**Output:** DriftEvent with classification and severity

### 4. Variance Analysis (`variance.py`)

Statistical analysis of signal variability.

**Features:**
- Welford's algorithm for numerical stability
- Sliding-window variance
- Spike detection with configurable threshold
- Noise level quantification

**Metrics:**
- Mean, variance, standard deviation
- Coefficient of variation
- Spike frequency

### 5. Frequency Detection (`freq_detect.py`)

Detects periodic oscillations in signals.

**Methods:**
- **Correlation-based:** Fast, targeted frequency detection
- **FFT-based:** Full spectrum analysis

**Applications:**
- Equipment vibration detection
- Periodic disturbance identification
- System instability indicators

### 6. Signal Quality Index (`sqi.py`)

Composite quality metric combining multiple factors.

**Components (Weighted):**
- Noise level (25%)
- Drift rate (25%)
- Spike frequency (20%)
- Oscillation energy (15%)
- Missing samples (15%)

**Output:** 0-100 score with quality classification

### 7. Main Engine (`engine.py`)

Orchestrates all components into unified processing pipeline.

**Responsibilities:**
- Signal registration and management
- Per-scan update coordination
- Statistics aggregation
- Result packaging

**Design Principles:**
- Deterministic execution
- No background threads
- Sequential processing
- PLC scan compatible

## Data Flow

See also: [`dataflow_per_scan.md`](./dataflow_per_scan.md) for the exact service/engine/incident per-scan call order and determinism notes.

### Per-Scan Processing

```
1. Raw Signal Input
   ↓
2. Apply Filters (EWMA, MA, HP)
   ↓
3. Drift Detection (discrete derivative)
   ↓
4. Variance Analysis (sliding window)
   ↓
5. Spike Detection (threshold-based)
   ↓
6. Frequency Analysis (correlation + FFT)
   ↓
7. SQI Calculation (weighted composite)
   ↓
8. Processed Signal Output
```

### ProcessedSignal Structure

```python
{
    "signal_id": str,
    "timestamp": float,
    "raw": float,
    "filtered_ewma": float,
    "filtered_ma": float,
    "highpass": float,
    "drift": float,
    "drift_type": str,
    "drift_severity": float,
    "monotonic_samples": int,
    "variance": float,
    "std_dev": float,
    "noise_level": float,
    "is_spike": bool,
    "spike_frequency": float,
    "oscillation_energy": float,
    "dominant_frequency": float,
    "sqi": float,
    "quality_class": str,
    "sqi_trend": str
}
```

## Real-Time Constraints

### Design for Determinism

1. **No Asynchronous Operations**
   - All processing is synchronous
   - No threading or multiprocessing
   - Predictable execution time

2. **Fixed Scan Interval**
   - Driven by PLC_Scan_Engine timing
   - Typically 100ms (10 Hz)
   - Must complete within scan period

3. **Memory Bounded**
   - Fixed-size buffers
   - No dynamic allocation in hot path
   - Predictable memory footprint

4. **Sequential Processing**
   - One signal at a time
   - Ordered execution
   - No race conditions

5. **Explicit Timestamps**
   - Scan timestamps must be provided (or an injected clock must be configured)
   - Sample timestamps default to the scan timestamp when omitted
   - Core logic avoids implicit wall-clock calls for deterministic outputs

## Integration Points

### PointCore-Simulator

```python
from sqe.integration import PointCoreAdapter

adapter = PointCoreAdapter(engine)
adapter.register_point("AI_001")
result = adapter.process_point(point_signal)
```

### PLC_Scan_Engine

```python
from sqe.integration import PLCScanAdapter

adapter = PLCScanAdapter(engine, scan_interval=0.1)
result = adapter.execute_scan(signal_values)
```

### SCADA-Comms-Front-End-Processor

```python
from sqe.integration import CommsAdapter
from sqe.integration.comms_adapter import CommsTelemetry

adapter = CommsAdapter(engine)
telemetry = {
    "AI_001": CommsTelemetry(
        poll_success=True,
        rtt_ms=120.0,
        jitter_ms=12.0,
        dropout_streak=0,
    )
}
result = adapter.process_scan(signal_values, telemetry_by_signal=telemetry)
```

## Configuration

### Per-Signal Configuration

```python
config = SignalConfig(
    signal_id="AI_001",
    ewma_alpha=0.3,           # Filter smoothing
    ma_window=10,             # Moving average window
    small_drift_threshold=0.5,  # Drift sensitivity
    large_drift_threshold=5.0,
    variance_window=20,       # Variance window
    spike_k_sigma=3.0,        # Spike threshold
    reference_frequencies=[0.1, 0.5, 1.0],  # Freq detection
    sample_interval=0.1       # Scan interval
)
```

### Global Configuration

```yaml
# defaults.yaml
engine:
  scan_interval: 0.1

filters:
  default_ewma_alpha: 0.3
  default_ma_window: 10

drift:
  small_threshold: 0.5
  large_threshold: 5.0
  sustained_window: 10
  monotonic_window: 5

variance:
  default_window: 20
  spike_k_sigma: 3.0

frequency:
  default_references: []
  window_size: 50
  enable_fft: false

sqi:
  weights:
    noise: 0.25
    drift: 0.25
    spikes: 0.20
    oscillation: 0.15
    missing: 0.15
```

## Performance Characteristics

### Computational Complexity

- **EWMA Filter:** O(1) per sample
- **Moving Average:** O(1) amortized
- **Variance:** O(1) per sample (Welford)
- **Drift Detection:** O(1) per sample
- **Frequency Correlation:** O(N) per frequency
- **FFT:** O(N log N) per window
- **SQI:** O(1) per calculation

### Memory Usage

Per signal:
- Signal buffers: ~1KB per buffer
- Filter state: ~100 bytes
- History tracking: ~10KB
- Total: ~15-20KB per signal

For 100 signals: ~1.5-2MB

### Timing Estimates

For 100ms scan with 100 signals:
- Total processing: ~10-20ms
- Per signal: ~0.1-0.2ms
- CPU utilization: ~10-20%

Sufficient headroom for 100ms scan interval.

## Extension Points

### Adding Custom Filters

```python
from sqe.core.filters import FilterBase

class CustomFilter(FilterBase):
    def update(self, x: float) -> float:
        # Custom filter logic
        pass
```

### Adding Custom Quality Metrics

```python
from sqe.core.sqi import SQIWeights

custom_weights = SQIWeights(
    noise=0.3,
    drift=0.2,
    custom_metric=0.5
)
```

### Adding Custom Detectors

```python
from sqe.core.engine import SignalProcessor

class CustomProcessor(SignalProcessor):
    def update(self, x: float):
        result = super().update(x)
        # Add custom detection
        return result
```

## Testing Strategy

### Unit Tests
- Each component tested in isolation
- Known input/output validation
- Edge case coverage

### Integration Tests
- Complete pipeline validation
- Multi-signal scenarios
- Timing verification

### Performance Tests
- Scan timing validation
- Memory profiling
- Stress testing

See `sqe/tests/` for complete test suite.
