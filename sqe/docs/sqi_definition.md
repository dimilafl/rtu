## Signal Quality Index (SQI) - Complete Definition

## Overview

The Signal Quality Index (SQI) is a composite metric that quantifies the overall quality of a telemetry signal on a scale of 0-100, where 100 represents perfect signal quality.

## Purpose

SQI provides:
- **Single metric** for signal health assessment
- **Trend analysis** for proactive maintenance
- **Alarm thresholds** for quality degradation
- **Diagnostic tool** for troubleshooting
- **Performance benchmarking** across signals

## Mathematical Definition

### Component Scores

SQI is composed of five weighted components, each scored 0-100:

#### 1. Noise Score (Snoise)

Quantifies signal variability and random fluctuations.

**Formula:**
```
Snoise = 100 * exp(-CV / CV_threshold)

Where:
  CV = coefficient of variation = σ / |μ|
  σ = standard deviation
  μ = mean
  CV_threshold = noise tolerance (default: 0.1)
```

**Interpretation:**
- CV = 0 → Snoise = 100 (perfect, no noise)
- CV = 0.1 → Snoise ≈ 37 (moderate noise)
- CV = 0.5 → Snoise ≈ 1 (high noise)

**Default Weight:** 25%

**Physical Meaning:**
- Electrical noise
- Quantization error
- Environmental interference
- Sensor precision limits

---

#### 2. Drift Score (Sdrift)

Quantifies signal instability and trending behavior.

**Formula:**
```
Sdrift = 100 * exp(-|dX| / dX_threshold)

Where:
  dX = x[n] - x[n-1] (discrete derivative)
  dX_threshold = drift tolerance (default: 1.0)
```

**Interpretation:**
- |dX| = 0 → Sdrift = 100 (stable)
- |dX| = 1.0 → Sdrift ≈ 37 (moderate drift)
- |dX| = 5.0 → Sdrift ≈ 1 (high drift)

**Default Weight:** 25%

**Physical Meaning:**
- Sensor calibration drift
- Temperature effects
- Process trending
- Slow transients

---

#### 3. Spike Score (Sspike)

Quantifies frequency of outliers and transient anomalies.

**Formula:**
```
Sspike = 100 * (1 - min(spike_freq / freq_threshold, 1.0))

Where:
  spike_freq = (spike_count / total_samples)
  freq_threshold = acceptable spike frequency (default: 0.05)
```

**Interpretation:**
- spike_freq = 0 → Sspike = 100 (no spikes)
- spike_freq = 0.025 → Sspike = 50 (occasional spikes)
- spike_freq ≥ 0.05 → Sspike = 0 (frequent spikes)

**Default Weight:** 20%

**Physical Meaning:**
- Electrical transients
- Valve switching
- Equipment startup/shutdown
- Communication errors

---

#### 4. Oscillation Score (Sosc)

Quantifies presence of unwanted periodic components.

**Formula:**
```
Sosc = 100 * exp(-E / E_threshold)

Where:
  E = total oscillation energy
  E_threshold = energy tolerance (default: 0.3)
```

**Interpretation:**
- E = 0 → Sosc = 100 (no oscillation)
- E = 0.3 → Sosc ≈ 37 (moderate oscillation)
- E = 1.0 → Sosc ≈ 5 (strong oscillation)

**Default Weight:** 15%

**Physical Meaning:**
- Control loop instability
- Mechanical vibration
- Pump pulsation
- Electrical interference (50/60 Hz)

---

#### 5. Missing Sample Score (Smissing)

Quantifies communication reliability.

**Formula:**
```
Smissing = 100 * (1 - missing_ratio)

Where:
  missing_ratio = missing_count / total_samples
```

**Interpretation:**
- missing_ratio = 0 → Smissing = 100 (perfect comms)
- missing_ratio = 0.1 → Smissing = 90 (10% loss)
- missing_ratio = 0.5 → Smissing = 50 (50% loss)

**Default Weight:** 15%

**Physical Meaning:**
- Communication dropouts
- Network congestion
- Protocol errors
- Device failures

---

### Composite SQI Calculation

**Weighted Sum:**
```
SQI = Σ (wi * Si)

Where:
  wi = weight for component i
  Si = score for component i (0-100)
  Σ wi = 1.0
```

**Default Weights:**
```
w_noise   = 0.25
w_drift   = 0.25
w_spike   = 0.20
w_osc     = 0.15
w_missing = 0.15
-----------------
Total     = 1.00
```

**Expanded Form:**
```
SQI = 0.25 * Snoise +
      0.25 * Sdrift +
      0.20 * Sspike +
      0.15 * Sosc +
      0.15 * Smissing
```

**Range:** [0, 100]

## Quality Classification

SQI scores are classified into five categories:

| SQI Range | Class      | Color  | Meaning |
|-----------|------------|--------|---------|
| 90-100    | Excellent  | Green  | Signal is pristine, suitable for all applications |
| 75-89     | Good       | Blue   | Signal is reliable for normal operations |
| 50-74     | Fair       | Yellow | Signal is usable but may require attention |
| 25-49     | Poor       | Orange | Signal quality degraded, investigation recommended |
| 0-24      | Critical   | Red    | Signal unreliable, immediate action required |

## Trend Analysis

SQI trend indicates quality trajectory over recent history.

**Calculation:**
```
history = last 10 SQI values
first_half = mean(history[0:5])
second_half = mean(history[5:10])
diff = second_half - first_half

if diff > 5:   trend = "improving"
if diff < -5:  trend = "degrading"
else:          trend = "stable"
```

**Use Cases:**
- **Improving:** Recent changes have enhanced signal quality
- **Degrading:** Proactive maintenance may be needed
- **Stable:** Signal quality is consistent

## Customization

### Custom Weights

Adjust weights based on application priorities:

**Example 1: Noise-Critical Application**
```python
from sqe.core.sqi import SQIWeights

weights = SQIWeights(
    noise=0.40,      # High priority on noise
    drift=0.20,
    spikes=0.20,
    oscillation=0.10,
    missing=0.10
)
```

**Example 2: Communication-Critical Application**
```python
weights = SQIWeights(
    noise=0.15,
    drift=0.15,
    spikes=0.15,
    oscillation=0.10,
    missing=0.45      # High priority on data availability
)
```

### Custom Thresholds

Adjust sensitivity based on signal characteristics:

```python
sqi_calc = SignalQualityIndex(
    noise_threshold=0.05,      # Stricter noise tolerance
    drift_threshold=0.5,       # Stricter drift tolerance
    spike_threshold=0.02,      # Stricter spike tolerance
    oscillation_threshold=0.2  # Stricter oscillation tolerance
)
```

## Interpretation Examples

### Example 1: High-Quality Signal

**Inputs:**
```
noise_level = 0.02
drift_rate = 0.1
spike_frequency = 0.0
oscillation_energy = 0.0
missing_ratio = 0.0
```

**Component Scores:**
```
Snoise   = 100 * exp(-0.02/0.1)  ≈ 82
Sdrift   = 100 * exp(-0.1/1.0)   ≈ 90
Sspike   = 100 * (1 - 0/0.05)    = 100
Sosc     = 100 * exp(-0/0.3)     = 100
Smissing = 100 * (1 - 0)         = 100
```

**SQI:**
```
SQI = 0.25*82 + 0.25*90 + 0.20*100 + 0.15*100 + 0.15*100
    = 20.5 + 22.5 + 20 + 15 + 15
    = 93
```

**Classification:** Excellent

---

### Example 2: Noisy Signal

**Inputs:**
```
noise_level = 0.5      # High noise
drift_rate = 0.2
spike_frequency = 0.03
oscillation_energy = 0.1
missing_ratio = 0.0
```

**Component Scores:**
```
Snoise   = 100 * exp(-0.5/0.1)   ≈ 1
Sdrift   = 100 * exp(-0.2/1.0)   ≈ 82
Sspike   = 100 * (1 - 0.03/0.05) = 40
Sosc     = 100 * exp(-0.1/0.3)   ≈ 72
Smissing = 100 * (1 - 0)         = 100
```

**SQI:**
```
SQI = 0.25*1 + 0.25*82 + 0.20*40 + 0.15*72 + 0.15*100
    = 0.25 + 20.5 + 8 + 10.8 + 15
    = 55
```

**Classification:** Fair

**Diagnosis:** Noise is the primary issue (Snoise = 1)

---

### Example 3: Communication Issues

**Inputs:**
```
noise_level = 0.05
drift_rate = 0.3
spike_frequency = 0.01
oscillation_energy = 0.0
missing_ratio = 0.3    # 30% packet loss
```

**Component Scores:**
```
Snoise   = 100 * exp(-0.05/0.1)  ≈ 61
Sdrift   = 100 * exp(-0.3/1.0)   ≈ 74
Sspike   = 100 * (1 - 0.01/0.05) = 80
Sosc     = 100 * exp(-0/0.3)     = 100
Smissing = 100 * (1 - 0.3)       = 70
```

**SQI:**
```
SQI = 0.25*61 + 0.25*74 + 0.20*80 + 0.15*100 + 0.15*70
    = 15.25 + 18.5 + 16 + 15 + 10.5
    = 75
```

**Classification:** Good (barely)

**Diagnosis:** Missing samples are reducing overall quality

---

## Operational Guidelines

### Setting Alarm Thresholds

**Conservative (High Reliability Required):**
```
Alarm if SQI < 90 (only excellent acceptable)
Warning if trend = "degrading"
```

**Moderate (Normal Operations):**
```
Alarm if SQI < 50 (fair or better acceptable)
Warning if SQI < 75
```

**Permissive (Best Effort):**
```
Alarm if SQI < 25 (critical only)
Warning if SQI < 50
```

### Maintenance Triggers

| SQI | Action |
|-----|--------|
| < 25 | Immediate investigation required |
| 25-50 | Schedule maintenance within 24 hours |
| 50-75 | Monitor closely, schedule preventive maintenance |
| 75-90 | Normal monitoring |
| > 90 | No action required |

### Trend-Based Actions

| Trend | Current SQI | Action |
|-------|-------------|--------|
| Degrading | < 50 | Immediate investigation |
| Degrading | 50-75 | Schedule inspection |
| Degrading | > 75 | Continue monitoring |
| Stable | Any | No action based on trend |
| Improving | < 50 | Verify improvement continues |

## Statistical Properties

### Sensitivity Analysis

How each input affects SQI (with default weights):

| Input Change | SQI Impact |
|--------------|------------|
| Double noise (CV 0.05 → 0.10) | -15 points |
| Double drift (dX 0.5 → 1.0) | -9 points |
| Add 5% spikes (0% → 5%) | -20 points |
| Add oscillation (E 0 → 0.3) | -9 points |
| Add 10% loss (0% → 10%) | -15 points |

### Typical Ranges

Based on SCADA field experience:

| Signal Type | Typical SQI | Range |
|-------------|-------------|-------|
| High-precision sensor | 85-95 | ±10 |
| Standard RTU analog input | 70-85 | ±15 |
| Derived/calculated signal | 60-75 | ±15 |
| Wireless sensor | 50-70 | ±20 |
| Legacy equipment | 40-60 | ±20 |

## Implementation

### Basic Usage

```python
from sqe.core.sqi import SignalQualityIndex

sqi_calc = SignalQualityIndex()

result = sqi_calc.calculate(
    noise_level=0.05,
    drift_rate=0.3,
    spike_frequency=0.01,
    oscillation_energy=0.1,
    missing_ratio=0.0
)

print(f"SQI: {result['sqi']:.1f}")
print(f"Class: {result['quality_class']}")
print(f"Trend: {result['trend']}")
```

### Component Analysis

```python
# Examine individual components
components = result['components']

print("Component Breakdown:")
print(f"  Noise:       {components['noise']:.1f}")
print(f"  Drift:       {components['drift']:.1f}")
print(f"  Spikes:      {components['spikes']:.1f}")
print(f"  Oscillation: {components['oscillation']:.1f}")
print(f"  Missing:     {components['missing']:.1f}")

# Identify weakest component
weakest = min(components.items(), key=lambda x: x[1])
print(f"\nWeakest: {weakest[0]} ({weakest[1]:.1f})")
```

### Historical Analysis

```python
# Get SQI statistics over time
stats = sqi_calc.get_statistics()

print(f"Mean SQI: {stats['mean_sqi']:.1f}")
print(f"Min SQI:  {stats['min_sqi']:.1f}")
print(f"Max SQI:  {stats['max_sqi']:.1f}")
```

## References

1. IEEE Std 1159-2019: Recommended Practice for Monitoring Electric Power Quality
2. ISA-5.1-2009: Instrumentation Symbols and Identification
3. NAMUR NE 107: Self-monitoring and diagnosis of field devices

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025 | Initial definition |
