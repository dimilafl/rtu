# Developer Guide

## Setup

### Prerequisites

- Python >= 3.8
- pip

### Install for development

```bash
git clone https://github.com/dimilafl/rtu.git
cd rtu
pip install -e ".[dev]"
```

This installs the project in editable mode with dev dependencies: `pytest`, `pytest-cov`, `black`, `flake8`, and `mypy`.

For optional plotting support:

```bash
pip install -e ".[all]"
```

### Verify installation

```bash
sqe version                 # prints version
pytest sqe/tests/ tests/ -q # runs test suite
```

## Development Workflow

### Before committing

```bash
# Run test suite
pytest sqe/tests/ tests/ -q

# Format code
black sqe/ tests/

# Lint
flake8 sqe/ tests/

# Type check (optional, not yet required by CI)
mypy sqe/core/
```

### CI Pipeline

The CI pipeline (`.github/workflows/ci.yml`) runs on every push:

- **`tests` job:** `pytest -q` on Python 3.11 and 3.12
- **`perf` job:** Performance smoke tests on Python 3.11

## Code Style

- Python 3.8+ compatible (no `match`/`case`, no `|` type unions)
- `from __future__ import annotations` at the top of files that use forward references
- Single-file modules per concept (one class/concept per file in `sqe/core/`)
- Typed dataclasses for public outputs, `dict` for internal intermediates
- `frozen=True` on data transfer objects
- Explicit `None` checks rather than implicit truthiness

### Naming

| Concept | Convention | Example |
|---------|-----------|---------|
| Classes | PascalCase | `VarianceCalculator` |
| Functions/methods | snake_case | `get_effective_missing_ratio()` |
| Private attributes | `_leading_underscore` | `self._sum` |
| Constants | UPPER_SNAKE_CASE | `DEFAULT_CONFIG_PATH` |
| Modules | snake_case | `signal_buffer.py` |

### Imports

```python
# Standard library
from collections import deque
from typing import Optional, Dict, List

# Third-party
import numpy as np

# First-party (sqe)
from sqe.core.engine import SignalConfig
```

## Project Structure

```
rtu/
├── sqe/                          # Main package
│   ├── __init__.py               # Exports SignalQualityEngine, SignalQualityIndex
│   ├── schema.py                 # JSON schemas for all output types
│   ├── config/                   # YAML configuration
│   │   ├── defaults.yaml         # All configurable parameters (~260 keys)
│   │   ├── loader.py             # Config loading, deep-merge, validation
│   │   └── yaml_strict.py        # Strict YAML (no duplicate keys)
│   ├── core/                     # DSP algorithms and processing engine
│   │   ├── engine.py             # SignalQualityEngine, SignalProcessor, SignalConfig, ProcessedSignal
│   │   ├── signal_buffer.py      # NumPy circular buffer (O(1) push/read)
│   │   ├── filters.py            # EWMA, HighPass, MovingAverage, FilterBank
│   │   ├── drift.py              # DriftDetector, DriftAnalyzer
│   │   ├── variance.py           # VarianceCalculator, WelfordVariance, SpikeDetector
│   │   ├── freq_detect.py        # FrequencyDetector, FFTFrequencyAnalyzer, OscillationDetector
│   │   ├── innovation.py         # Kalman-based InnovationModel
│   │   ├── sqi.py                # SignalQualityIndex, SQIWeights
│   │   ├── stale.py              # StaleDetector (flatline + timestamp)
│   │   ├── step_change.py        # StepChangeDetector
│   │   ├── plausibility.py       # PlausibilityChecker (range + rate)
│   │   ├── sample.py             # Sample, SampleQuality
│   │   ├── incidents.py          # IncidentEngine, IncidentPolicy, QualityIncident
│   │   ├── group_incidents.py    # GroupIncidentEngine, GroupIncidentPolicy
│   │   ├── grouping.py           # GroupResolver, GroupingConfig
│   │   └── event_filter.py       # EventFilter, EventFilterPolicy
│   ├── ops/                      # Operational service layer
│   │   └── service.py            # RealtimeQualityService
│   ├── integration/              # External system adapters
│   │   ├── pointcore_adapter.py
│   │   ├── plcscan_adapter.py
│   │   ├── comms_adapter.py
│   │   └── publisher.py
│   ├── comms/                    # Comms health monitoring
│   │   ├── api.py                # Public API
│   │   ├── health.py             # Health aggregation + classification
│   │   ├── budget.py             # Capacity budgeting
│   │   ├── schema.py             # Comms JSON schemas
│   │   └── topology_index.py     # Topology-based comms lookup
│   ├── rca/                      # Root cause analysis
│   │   ├── engine.py             # RCA orchestrator
│   │   ├── evidence.py           # Evidence collection
│   │   ├── scoring.py            # Scoring algorithms
│   │   ├── scenario.py           # Scenario modeling
│   │   ├── schema.py             # RCA JSON schemas
│   │   ├── state.py              # State management
│   │   ├── suppression.py        # Priority/suppression rules
│   │   ├── node_incidents.py     # Node incident lifecycle
│   │   └── confidence.py         # Confidence scoring
│   ├── topology/                 # Topology management
│   │   ├── model.py              # TopologySnapshot, nodes, edges
│   │   ├── loader.py             # YAML topology loader
│   │   └── index.py              # Topology lookup
│   ├── replay/                   # Deterministic replay
│   │   ├── runner.py             # Replay engine
│   │   └── schema.py             # Replay output schemas
│   ├── eval/                     # Evaluation harness
│   │   ├── labels.py             # Label loading
│   │   └── metrics.py            # Precision/recall/F1
│   ├── cli/                      # Command-line interface
│   │   └── sqe_cli.py            # analyze, simulate, incidents, replay, eval, offline-tuning
│   ├── tools/                    # Utility tools
│   │   ├── bench.py              # Performance benchmark
│   │   ├── offline_tuning.py     # Offline parameter tuning
│   │   ├── impact_report.py      # Impact report generator
│   │   ├── export_vectors.py     # Portability vector exporter
│   │   └── dump_config_map.py    # Config dump helper
│   ├── examples/                 # Demo scripts
│   │   ├── demo_pipeline.py
│   │   └── noisy_signal_demo.py
│   ├── vectors/                  # Cross-language portability vectors
│   │   ├── scans.jsonl           # Test input
│   │   ├── cfg.yaml              # Vector config
│   │   ├── expected_incidents.jsonl
│   │   └── expected_group_incidents.jsonl
│   ├── docs/                     # Documentation
│   │   ├── architecture.md
│   │   ├── dataflow_per_scan.md
│   │   ├── config_map.md
│   │   ├── dsp_principles.md
│   │   ├── sqi_definition.md
│   │   ├── incidents.md
│   │   ├── integration_guide.md
│   │   ├── offline_tuning.md
│   │   ├── performance.md
│   │   ├── evaluation.md
│   │   ├── comms_health_mvp.md
│   │   ├── comms_budget_v2.md
│   │   ├── development.md
│   │   ├── module_reference.md
│   │   ├── testing.md
│   │   ├── refactor_analysis.md
│   │   └── prd_refactor.md
│   └── tests/                    # Package-level tests (48 files)
│       └── fixtures/             # Test fixtures (replay, eval, etc.)
├── tests/                        # Top-level tests (4 files)
├── pyproject.toml                # Build config
├── setup.py                      # Legacy setup.py shim
├── requirements.txt              # Core deps (numpy, pyyaml)
├── requirements-dev.txt          # Dev deps (pytest, black, etc.)
├── requirements-optional.txt     # Optional deps (matplotlib)
└── README.md
```

## Determinism

SQE is deterministic by design. Given the same input scans, configuration, and system:

- Processed signals are identical across runs
- Incident IDs are stable (derived from `run_id:signal_id:scan_index`)
- Registration order is preserved via `_registration_order` deque
- Replay outputs sort by deterministic keys

### Verifying determinism

```bash
sqe replay --in vectors/scans.jsonl --config vectors/cfg.yaml --out /tmp/run_a
sqe replay --in vectors/scans.jsonl --config vectors/cfg.yaml --out /tmp/run_b
diff /tmp/run_a/incidents.jsonl /tmp/run_b/incidents.jsonl   # should be empty
diff /tmp/run_a/group_incidents.jsonl /tmp/run_b/group_incidents.jsonl  # empty
```

## Adding a New Detector

1. Create a new file in `sqe/core/` (e.g., `jitter.py`)
2. Define a result dataclass (e.g., `JitterResult`)
3. Implement the detector class with `update()` and `reset()`
4. Add a test file in `sqe/tests/` (e.g., `test_jitter.py`)
5. Wire into `SignalProcessor.__init__()` and `SignalProcessor.update()` in `engine.py`
6. Add config parameters to `SignalConfig` and `defaults.yaml`
7. Add to `build_signal_config()` in `loader.py`

## Versioning

Bump `__version__` in `sqe/__init__.py` and `SCHEMA_VERSION` in `sqe/schema.py` when output formats change.

## Getting Help

For architecture questions, start with `sqe/docs/architecture.md` and `sqe/docs/dataflow_per_scan.md`. For DSP fundamentals, see `sqe/docs/dsp_principles.md`.
