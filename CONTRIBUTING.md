# Contributing to Signal Quality Engine

Thanks for your interest in contributing!

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/dimilafl/rtu.git
   cd rtu
   ```
3. Install in development mode:
   ```bash
   pip install -e ".[dev]"
   ```

## Development Workflow

### Before Submitting Changes

```bash
# Run the test suite (146+ tests)
pytest -q

# Format code
black sqe/ tests/

# Lint
flake8 sqe/ tests/

# Type check
mypy sqe/core/
```

### Code Style

- Python 3.8+ compatible
- Follow PEP 8
- Single-file modules per concept in `sqe/core/`
- Typed dataclasses for public outputs
- Explicit `None` checks rather than implicit truthiness

### Commit Messages

- Use present tense ("Add feature" not "Added feature")
- Keep the first line under 72 characters
- Reference issues when applicable

## Adding a New Detector

1. Create a new file in `sqe/core/`
2. Define a result dataclass
3. Implement the detector class with `update()` and `reset()`
4. Add tests in `sqe/tests/`
5. Wire into `SignalProcessor` in `sqe/core/engine.py`
6. Add config parameters to `sqe/config/defaults.yaml`

## Running Tests

```bash
# All tests
pytest -q

# With coverage
pytest --cov=sqe -q

# Specific module
pytest sqe/tests/test_engine.py
```

## Getting Help

Open an issue on GitHub or start a discussion.
