# Integration Guide

## Integrating SQE with Existing SCADA Components

This guide explains how to integrate the Signal Quality Engine with your existing repositories:
- PointCore-Simulator
- PLC_Scan_Engine
- SCADA-Comms-Front-End-Processor

## Prerequisites

```bash
pip install numpy
pip install pyyaml
pip install pytest  # For running tests
```

Optional for CLI plotting:
```bash
pip install matplotlib
```

## Integration 1: PointCore-Simulator

### Overview

PointCore-Simulator generates analog RTU points. The SQE processes these points to provide quality metrics.

### Integration Steps

#### 1. Import SQE Components

```python
from sqe.core.engine import SignalQualityEngine, SignalConfig
from sqe.integration.pointcore_adapter import PointCoreAdapter, PointCoreSignal
```

#### 2. Initialize Engine and Adapter

```python
# Initialize SQE
engine = SignalQualityEngine(scan_interval=0.1)

# Create adapter
adapter = PointCoreAdapter(engine)
```

#### 3. Register Points

```python
# Register analog input points
adapter.register_point("AI_001")
adapter.register_point("AI_002")

# Or with custom configuration
from sqe.core.engine import SignalConfig

config = SignalConfig(
    signal_id="AI_CRITICAL",
    ewma_alpha=0.2,  # More smoothing
    variance_window=30,
    spike_k_sigma=2.5  # More sensitive
)
adapter.register_point("AI_CRITICAL", config)
```

#### 4. Process Point Data

**Option A: Process Individual Points**

```python
from sqe.integration.pointcore_adapter import PointCoreSignal

# Create point from simulator
point = PointCoreSignal(
    point_id="AI_001",
    point_type="AI",
    value=42.5,
    timestamp=time.time(),
    quality="GOOD",
    address="0x1000"
)

# Process through SQE
result = adapter.process_point(point)

if result:
    print(f"SQI: {result['sqi']}")
    print(f"Filtered: {result['filtered_ewma']}")
    print(f"Quality: {result['quality_class']}")
    if result.get("sqi_components"):
        print(f"Components: {result['sqi_components']}")
```

**Option B: Process Scan Batch**

```python
# Collect points from simulator scan
points = [
    PointCoreSignal("AI_001", "AI", 42.5, ts, "GOOD", "0x1000"),
    PointCoreSignal("AI_002", "AI", 100.2, ts, "GOOD", "0x1001"),
    PointCoreSignal("AI_003", "AI", None, ts, "BAD", "0x1002")  # Bad quality
]

# Process entire scan
results = adapter.process_scan(points)

for point_id, result in results.items():
    print(f"{point_id}: SQI={result['sqi']:.1f}")
    if result.get("sqi_components"):
        print(f"  Components: {result['sqi_components']}")
```

#### 5. Convert Simulator Data Format

If your PointCore-Simulator uses dictionary format:

```python
# Simulator output format
simulator_data = {
    "AI_001": {"value": 42.5, "quality": "GOOD", "timestamp": 1234567890.0},
    "AI_002": {"value": 100.2, "quality": "GOOD", "timestamp": 1234567890.0}
}

# Convert to PointCoreSignal objects
signals = adapter.from_simulator_data(simulator_data)

# Process
results = adapter.process_scan(signals)
```

### Complete Example

```python
# pointcore_integration.py

import time
from sqe.core.engine import SignalQualityEngine
from sqe.integration.pointcore_adapter import PointCoreAdapter, PointCoreSignal

# Initialize
engine = SignalQualityEngine(scan_interval=0.1)
adapter = PointCoreAdapter(engine)

# Register points
for i in range(1, 11):
    adapter.register_point(f"AI_{i:03d}")

# Simulation loop
for scan in range(100):
    # Generate point data (from your PointCore-Simulator)
    points = generate_points_from_simulator()  # Your function

    # Process through SQE
    results = adapter.process_scan(points)

    # Use results
    for point_id, result in results.items():
        if result['sqi'] < 50:
            print(f"Warning: {point_id} has poor quality (SQI={result['sqi']:.1f})")
            if result.get("sqi_components"):
                print(f"  Components: {result['sqi_components']}")

    time.sleep(0.1)  # 100ms scan interval
```

## Integration 2: PLC_Scan_Engine

### Overview

PLC_Scan_Engine provides deterministic scan timing. SQE operates synchronously within the scan cycle.

### Integration Steps

#### 1. Import Components

```python
from sqe.core.engine import SignalQualityEngine
from sqe.integration.plcscan_adapter import PLCScanAdapter
```

#### 2. Initialize with Scan Timing

```python
# Initialize SQE
engine = SignalQualityEngine(scan_interval=0.1)

# Create PLC scan adapter
plc_adapter = PLCScanAdapter(engine, scan_interval=0.1)
```

#### 3. Register Callbacks (Optional)

```python
def pre_scan(scan_number):
    print(f"Starting scan {scan_number}")

def post_scan(scan_number, duration, results):
    print(f"Scan {scan_number} completed in {duration*1000:.2f}ms")
    if duration > 0.1:
        print("WARNING: Scan overrun!")

plc_adapter.set_pre_scan_callback(pre_scan)
plc_adapter.set_post_scan_callback(post_scan)
```

#### 4. Execute Scans

```python
# In your PLC scan loop
while running:
    # Collect signal values from your PLC logic
    signal_values = {
        "AI_001": read_analog_input(1),
        "AI_002": read_analog_input(2),
        "DO_001": read_digital_output(1)
    }

    # Execute SQE processing within scan
    scan_result = plc_adapter.execute_scan(signal_values)

    # Access processed signals
    for sig_id, processed in scan_result["processed_signals"].items():
        # Use processed data in your control logic
        filtered_value = processed["filtered_ewma"]
        quality = processed["sqi"]

    # Check timing
    if scan_result["timing_error"] > 0.01:  # 10ms tolerance
        log_timing_warning(scan_result)
```

#### 5. Monitor Performance

```python
# Get scan performance metrics
perf = plc_adapter.get_scan_performance()

print(f"Scans Executed: {perf['scans_executed']}")
print(f"Mean Duration: {perf['mean_duration']*1000:.2f}ms")
print(f"Max Duration: {perf['max_duration']*1000:.2f}ms")
print(f"CPU Utilization: {perf['utilization']*100:.1f}%")
print(f"Scan Overruns: {perf['overruns']}")
```

### Complete Example

```python
# plc_integration.py

from sqe.core.engine import SignalQualityEngine
from sqe.integration.plcscan_adapter import PLCScanAdapter, ScanCycleController

# Initialize
engine = SignalQualityEngine(scan_interval=0.1)
plc_adapter = PLCScanAdapter(engine, scan_interval=0.1)

# Register signals (auto-registration also works)
for i in range(1, 21):
    engine.register_signal(f"AI_{i:03d}")

# Data source function
def get_scan_data(scan_number):
    # Your PLC logic to collect signal values
    return {
        f"AI_{i:03d}": read_input(i)
        for i in range(1, 21)
    }

# Create scan controller
controller = ScanCycleController(plc_adapter, get_scan_data)

# Run for 1000 scans
controller.start(max_scans=1000)

# Check performance
perf = plc_adapter.get_scan_performance()
print(f"Average scan time: {perf['mean_duration']*1000:.2f}ms")
```

## Integration 3: SCADA-Comms-Front-End-Processor

### Overview

The Comms Front-End introduces communication artifacts. SQE tracks these and adjusts quality metrics.

### Integration Steps

#### 1. Import Components

```python
from sqe.core.engine import SignalQualityEngine
from sqe.integration.comms_adapter import CommsAdapter, CommsArtifact
```

#### 2. Configure Communication Artifacts

```python
# Define communication characteristics
artifact_config = CommsArtifact(
    jitter_ms=5.0,              # 5ms timing jitter
    dropout_probability=0.02,    # 2% packet loss
    late_probability=0.01,       # 1% late arrivals
    late_delay_ms=50.0          # 50ms delay when late
)

# Initialize
engine = SignalQualityEngine(scan_interval=0.1)
comms_adapter = CommsAdapter(engine, artifact_config)
```

#### 3. Process with Communication Effects

```python
# In your communication receive loop
def process_received_data(raw_signals):
    # Inject communication artifacts
    result = comms_adapter.process_scan(raw_signals)

    # Get processed signals
    processed_signals = result["processed_signals"]

    # Get communication statistics
    comms_stats = result["comms_stats"]

    # Check communication quality
    if comms_stats["dropout_rate"] > 0.05:  # >5% dropout
        print("WARNING: High packet loss")

    return processed_signals, comms_stats
```

#### 4. Monitor Communication Quality

```python
# Get cumulative statistics
stats = comms_adapter.get_stats()

print(f"Total Samples: {stats['total_samples']}")
print(f"Dropped: {stats['dropped_samples']} ({stats['dropout_rate']:.1%})")
print(f"Late: {stats['late_samples']} ({stats['late_rate']:.1%})")
print(f"Avg Jitter: {stats['average_jitter_ms']:.2f}ms")
```

#### 5. Use Communication Quality Monitor

```python
from sqe.integration.comms_adapter import CommsQualityMonitor

# Initialize monitor
monitor = CommsQualityMonitor(window_size=100)

# Update periodically
while running:
    # Process data
    result = comms_adapter.process_scan(signals)
    comms_stats = result["comms_stats"]

    # Update monitor
    quality = monitor.update(comms_stats)

    print(f"Comms Quality Score: {quality['quality_score']:.1f}")
    print(f"Quality Class: {quality['quality_class']}")
    print(f"Dropout Trend: {quality['dropout_trend']}")
    print(f"Latency Trend: {quality['latency_trend']}")
```

### Complete Example

```python
# comms_integration.py

from sqe.core.engine import SignalQualityEngine
from sqe.integration.comms_adapter import (
    CommsAdapter,
    CommsArtifact,
    CommsQualityMonitor
)

# Initialize
engine = SignalQualityEngine(scan_interval=0.1)

# Configure realistic comms artifacts
artifact_config = CommsArtifact(
    jitter_ms=3.0,
    dropout_probability=0.01,
    late_probability=0.005,
    late_delay_ms=30.0
)

comms_adapter = CommsAdapter(engine, artifact_config)
monitor = CommsQualityMonitor()

# Simulation loop
for scan in range(1000):
    # Get clean signal data from RTU
    clean_signals = get_rtu_data()

    # Process through comms adapter (with artifacts)
    result = comms_adapter.process_scan(clean_signals)

    # Monitor communication quality
    quality = monitor.update(result["comms_stats"])

    # Alert on degraded communication
    if quality["quality_class"] in ["poor", "critical"]:
        print(f"Comms degraded: {quality['quality_class']}")

    # Use processed signals
    for sig_id, processed in result["processed_signals"].items():
        # Downstream processing
        handle_signal(sig_id, processed)
```

## Combined Integration Example

### All Three Systems Together

```python
# complete_integration.py

from sqe.core.engine import SignalQualityEngine, SignalConfig
from sqe.integration.pointcore_adapter import PointCoreAdapter
from sqe.integration.plcscan_adapter import PLCScanAdapter
from sqe.integration.comms_adapter import CommsAdapter, CommsArtifact

# Initialize SQE
engine = SignalQualityEngine(scan_interval=0.1)

# Setup PointCore adapter
pointcore = PointCoreAdapter(engine)

# Setup PLC scan adapter
plc_scan = PLCScanAdapter(engine, scan_interval=0.1)

# Setup Comms adapter
comms_config = CommsArtifact(jitter_ms=2.0, dropout_probability=0.01)
comms = CommsAdapter(engine, comms_config)

# Complete processing pipeline
def process_scan_cycle():
    # 1. PointCore generates signals
    simulator_data = pointcore_simulator.get_current_values()
    point_signals = pointcore.from_simulator_data(simulator_data)

    # 2. Convert to signal dictionary
    clean_signals = {
        p.point_id: p.value for p in point_signals
    }

    # 3. Apply communication artifacts
    comms_result = comms.process_scan(clean_signals)

    # 4. Execute PLC scan with SQE processing
    scan_result = plc_scan.execute_scan(
        {sig_id: proc["raw"]
         for sig_id, proc in comms_result["processed_signals"].items()}
    )

    # 5. Access final processed signals
    processed_signals = scan_result["processed_signals"]

    # 6. Use in control logic
    for sig_id, signal in processed_signals.items():
        update_control_logic(sig_id, signal)

    return scan_result

# Main loop
while running:
    scan_result = process_scan_cycle()

    # Monitor performance
    if scan_result["scan_duration"] > 0.09:  # 90% of scan interval
        print("WARNING: High CPU utilization")
```

## Configuration Management

### YAML Configuration

```yaml
# sqe_config.yaml

engine:
  scan_interval: 0.1

signals:
  AI_001:
    ewma_alpha: 0.3
    ma_window: 10
    small_drift_threshold: 0.5
    large_drift_threshold: 5.0

  AI_CRITICAL:
    ewma_alpha: 0.2
    variance_window: 30
    spike_k_sigma: 2.5
    reference_frequencies: [0.1, 0.5, 1.0]

defaults:
  ewma_alpha: 0.3
  ma_window: 10
  variance_window: 20
  spike_k_sigma: 3.0
```

### Load Configuration

```python
import yaml
from sqe.core.engine import SignalQualityEngine, SignalConfig

# Load configuration
with open('sqe_config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Initialize engine
engine = SignalQualityEngine(
    scan_interval=config['engine']['scan_interval']
)

# Register signals with configs
for sig_id, sig_config in config['signals'].items():
    config_obj = SignalConfig(
        signal_id=sig_id,
        **sig_config
    )
    engine.register_signal(sig_id, config_obj)
```

For standard defaults plus overrides, you can use the built-in loader to merge
`sqe/config/defaults.yaml` with a custom config file:

```python
from sqe.config.loader import build_engine_settings, load_config
from sqe.core.engine import SignalQualityEngine

config = load_config("sqe_config.yaml")
engine_settings = build_engine_settings(config, ["AI_001", "AI_CRITICAL"])

engine = SignalQualityEngine(
    scan_interval=engine_settings["scan_interval"],
    auto_register=engine_settings["auto_register"],
    signal_defaults=engine_settings["signal_defaults"]
)

for signal_id, signal_config in engine_settings["signal_configs"].items():
    engine.register_signal(signal_id, signal_config)
```

## Troubleshooting

### High Scan Duration

If scans are taking too long:

```python
perf = plc_adapter.get_scan_performance()
if perf['mean_duration'] > 0.08:  # 80% of scan interval
    # Reduce number of signals
    # Increase scan interval
    # Reduce window sizes
    # Disable FFT analysis if not needed
```

### Memory Usage

Monitor memory per signal:

```python
import sys

# Approximate memory per signal
buffer_memory = window_size * 8  # bytes per float
total_per_signal = buffer_memory * 5  # ~5 buffers per signal

print(f"Estimated memory per signal: {total_per_signal / 1024:.1f} KB")
print(f"Total for 100 signals: {total_per_signal * 100 / 1024 / 1024:.1f} MB")
```

### Signal Quality Issues

Debug low SQI scores:

```python
result = engine.update_single("AI_001", value)

# Examine SQI components
print(f"SQI: {result.sqi}")
if result.sqi_components:
    print(f"  Components: {result.sqi_components}")
print(f"  Noise level: {result.noise_level}")
print(f"  Drift: {result.drift}")
print(f"  Spike freq: {result.spike_frequency}")
print(f"  Oscillation: {result.oscillation_energy}")
```

## Next Steps

1. Run the examples in `sqe/examples/`
2. Review test suite in `sqe/tests/`
3. Experiment with configuration parameters
4. Integrate with your existing systems
5. Monitor performance and tune as needed

For questions or issues, refer to the API documentation or create an issue on GitHub.
