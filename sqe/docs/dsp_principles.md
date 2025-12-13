# DSP Principles in Signal Quality Engine

## Mathematical Foundations

This document explains the digital signal processing mathematics implemented in SQE.

## 1. Discrete-Time Signals

All signals in SQE are discrete-time sequences:

```
x[n] = signal value at sample n
n = 0, 1, 2, ...
Δt = sampling interval (e.g., 0.1 seconds)
```

Physical time: `t = n * Δt`

## 2. Low-Pass Filtering (EWMA)

### Exponentially Weighted Moving Average

**Difference Equation:**
```
y[n] = α * x[n] + (1 - α) * y[n-1]
```

Where:
- `x[n]` = input sample
- `y[n]` = filtered output
- `α` = smoothing factor (0 < α ≤ 1)
- `y[n-1]` = previous output

### Transfer Function

Z-transform:
```
H(z) = α / (1 - (1-α)z⁻¹)
```

### Frequency Response

```
|H(f)| = α / sqrt(1 + (1-α)² - 2(1-α)cos(2πfΔt))
```

### Cutoff Frequency

3dB cutoff occurs approximately at:
```
fc ≈ α * fs / (2π(1-α))
```

Where `fs = 1/Δt` is sampling frequency.

### Design Guidelines

- **α = 0.1:** Heavy smoothing, slow response
- **α = 0.3:** Moderate smoothing (default)
- **α = 0.5:** Light smoothing, fast response
- **α = 1.0:** No filtering (pass-through)

### Time Constant

The filter's time constant τ relates to α:
```
τ = -Δt / ln(1 - α)
```

For α = 0.3 and Δt = 0.1s:
```
τ ≈ 0.28 seconds
```

### Implementation

```python
class EWMAFilter:
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.last_output = None

    def update(self, x):
        if self.last_output is None:
            self.last_output = x
            return x

        y = self.alpha * x + (1 - self.alpha) * self.last_output
        self.last_output = y
        return y
```

## 3. High-Pass Filtering

### Derived from Low-Pass

The high-pass filter is derived by subtracting the low-pass output from the input:

```
hp[n] = x[n] - lp[n]
```

Where `lp[n]` is the EWMA low-pass filtered signal.

### Properties

- Removes DC component
- Removes slow trends
- Passes high-frequency content
- Complementary to low-pass filter

### Frequency Response

```
Hhp(f) = 1 - Hlp(f)
```

### Use Cases

- Removing signal baseline
- Detecting rapid changes
- AC coupling

## 4. Moving Average Filter

### Equation

```
y[n] = (1/N) * Σ(i=0 to N-1) x[n-i]
```

Where N is the window size.

### Frequency Response

Sinc function in frequency domain:
```
H(f) = |sin(πfNΔt) / (N * sin(πfΔt))|
```

### Properties

- Linear phase (no distortion)
- Uniform weighting within window
- Good noise reduction
- Poor at preserving edges

### Comparison to EWMA

| Property | EWMA | Moving Average |
|----------|------|----------------|
| Memory | O(1) | O(N) |
| Phase | Non-linear | Linear |
| Edge Response | Gradual | Sharp |
| Noise Reduction | Exponential weights | Uniform weights |

## 5. Variance Calculation

### Welford's Online Algorithm

Numerically stable method for computing variance:

**Initialize:**
```
count = 0
mean = 0
M2 = 0
```

**Update:**
```
count = count + 1
delta = x - mean
mean = mean + delta / count
delta2 = x - mean
M2 = M2 + delta * delta2
```

**Compute:**
```
variance = M2 / (count - 1)  # Sample variance
```

### Why Welford's Algorithm?

Traditional formula can suffer from catastrophic cancellation:
```
var = Σ(x²) / N - (Σx / N)²  # AVOID: numerical instability
```

Welford's algorithm:
- Single pass
- Numerically stable
- O(1) memory
- Avoids overflow

### Sliding-Window Variance

For a fixed window of N samples:

```
mean[n] = (1/N) * Σ(i=0 to N-1) x[n-i]

var[n] = (1/N) * Σ(i=0 to N-1) (x[n-i] - mean[n])²
```

### Coefficient of Variation

Noise level normalized by signal magnitude:
```
CV = σ / |μ|

Where:
  σ = standard deviation
  μ = mean
```

CV is dimensionless and allows comparison across different signal ranges.

## 6. Drift Detection

### Discrete Derivative

First-order difference:
```
dX[n] = x[n] - x[n-1]
```

### Drift Classification

**1. No Drift:**
```
|dX[n]| < ε (small threshold)
```

**2. Small Sustained Drift:**
```
|dX[n]| > ε for k consecutive samples
```

**3. Large Transient Drift:**
```
|dX[n]| > δ (large threshold)
```

**4. Monotonic Drift:**
```
sign(dX[n]) = sign(dX[n-1]) = ... (consistent direction)
```

### Severity Score

```
severity = min(|dX[n]| / δ, 1.0)

Enhanced if monotonic:
  severity = min(severity * 1.5, 1.0)
```

### Physical Interpretation

- **Small sustained:** Sensor degradation, calibration drift
- **Large transient:** Valve operation, equipment startup
- **Monotonic:** Tank filling/draining, slow leak

## 7. Spike Detection

### Statistical Threshold

Spike detected if:
```
|x[n] - μ| > k * σ

Where:
  μ = mean of recent samples
  σ = standard deviation of recent samples
  k = threshold multiplier (typically 3.0)
```

### Gaussian Assumption

For Gaussian noise:
- k = 3: 99.7% of samples within bounds
- k = 4: 99.99% of samples within bounds
- k = 5: 99.9999% of samples within bounds

### Adaptive Threshold

Threshold adapts to signal statistics:
```
threshold[n] = μ[n] + k * σ[n]
```

Updated each sample with sliding window.

## 8. Frequency Detection (Correlation Method)

### Cross-Correlation with Reference

For each reference frequency fᵢ:

**Sine Correlation:**
```
Cs[i] = (1/N) * Σ(n=0 to N-1) x[n] * sin(2π fᵢ n Δt)
```

**Cosine Correlation:**
```
Cc[i] = (1/N) * Σ(n=0 to N-1) x[n] * cos(2π fᵢ n Δt)
```

### Magnitude and Phase

```
Magnitude: M[i] = sqrt(Cs[i]² + Cc[i]²)
Phase:     φ[i] = atan2(Cs[i], Cc[i])
```

### Detection Threshold

Frequency component detected if:
```
M[i] > threshold (e.g., 0.5)
```

### Energy

Oscillation energy:
```
E[i] = M[i]²
```

Total energy:
```
Etotal = Σ E[i] for all detected frequencies
```

## 9. FFT-Based Frequency Analysis

### Discrete Fourier Transform

```
X[k] = Σ(n=0 to N-1) x[n] * e^(-j2πkn/N)

For k = 0, 1, ..., N-1
```

### Frequency Bins

```
f[k] = k * fs / N

Where:
  fs = 1/Δt (sampling frequency)
  N = FFT size
```

### Windowing

Apply Hanning window to reduce spectral leakage:
```
w[n] = 0.5 * (1 - cos(2πn/(N-1)))

x_windowed[n] = x[n] * w[n]
```

### Magnitude Spectrum

```
|X[k]| = sqrt(Real(X[k])² + Imag(X[k])²) / N
```

## 10. Signal Quality Index (SQI)

### Component Scores

Each component scored 0-100, where 100 is perfect:

**1. Noise Score:**
```
Snoise = 100 * exp(-CV / CV_threshold)

Where CV = coefficient of variation
```

**2. Drift Score:**
```
Sdrift = 100 * exp(-|dX| / dX_threshold)
```

**3. Spike Score:**
```
Sspike = 100 * (1 - min(spike_freq / freq_threshold, 1.0))
```

**4. Oscillation Score:**
```
Sosc = 100 * exp(-E / E_threshold)
```

**5. Missing Sample Score:**
```
Smissing = 100 * (1 - missing_ratio)
```

### Weighted Composite

```
SQI = Σ (wi * Si)

Where:
  wi = weight for component i
  Si = score for component i
  Σ wi = 1.0 (normalized weights)
```

### Default Weights

```
w_noise = 0.25
w_drift = 0.25
w_spike = 0.20
w_osc   = 0.15
w_miss  = 0.15
```

### Quality Classification

```
SQI ≥ 90: Excellent
SQI ≥ 75: Good
SQI ≥ 50: Fair
SQI ≥ 25: Poor
SQI < 25: Critical
```

## 11. Sampling Theory

### Nyquist Theorem

To avoid aliasing:
```
fs > 2 * fmax

Where:
  fs = sampling frequency
  fmax = maximum frequency of interest
```

### Example

For 0.1s sampling interval:
```
fs = 10 Hz
fmax < 5 Hz (Nyquist frequency)
```

Reference frequencies [0.1, 0.5, 1.0] Hz are well within Nyquist limit.

## 12. Numerical Considerations

### Floating-Point Precision

- All calculations use IEEE 754 double precision
- Approximately 15-17 decimal digits
- Sufficient for SCADA telemetry (typically 12-16 bit ADC)

### Avoiding Overflow

- Normalized correlation (divide by N)
- Incremental variance (Welford's algorithm)
- Bounded SQI scores (clip to [0, 100])

### Avoiding Underflow

- Check for division by zero
- Minimum variance threshold
- Guard clauses for empty buffers

## 13. Performance Optimization

### Precomputed References

For frequency detection, precompute reference waveforms:
```python
# Once at initialization
sin_ref = np.sin(2 * π * f * Δt * np.arange(N))
cos_ref = np.cos(2 * π * f * Δt * np.arange(N))

# Fast correlation
corr_sin = np.sum(signal * sin_ref) / N
corr_cos = np.sum(signal * cos_ref) / N
```

### Memory Locality

- Contiguous arrays for cache efficiency
- Minimize random access
- Sequential processing

### Algorithmic Complexity

All per-sample operations are O(1) or O(N) where N is window size, not total samples.

## References

1. Smith, S. W. (1997). *The Scientist and Engineer's Guide to Digital Signal Processing*.

2. Oppenheim, A. V., & Schafer, R. W. (2009). *Discrete-Time Signal Processing*.

3. Welford, B. P. (1962). "Note on a method for calculating corrected sums of squares and products". *Technometrics*.

4. Lyons, R. G. (2011). *Understanding Digital Signal Processing*.
