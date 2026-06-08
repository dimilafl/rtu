# Changelog

## 1.0.0 (2025)

- Initial release
- Complete DSP pipeline with EWMA, high-pass, moving average filters
- Drift detection (sustained, transient, monotonic)
- Spike detection with configurable sigma thresholds
- Low-frequency oscillation detection (correlation-based and FFT)
- Signal Quality Index (SQI) composite metric (0-100)
- Quality incident lifecycle (started, updated, resolved)
- Comms health monitoring and budget reporting
- Root cause analysis engine
- Deterministic replay pipeline
- Integration adapters for PointCore-Simulator, PLC_Scan_Engine, and SCADA-Comms-Front-End-Processor
- CLI tool (analyze, simulate, incidents, replay, eval)
- Offline parameter tuning pipeline
- Comprehensive test suite (146+ tests)
- Full documentation (15+ docs)
