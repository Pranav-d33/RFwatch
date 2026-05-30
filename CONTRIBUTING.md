# Contributing to RFwatch

## Development Setup

### 1. System Dependencies
```bash
sudo apt install gnuradio gr-osmosdr hackrf \
  python3-pyside6.qtcore python3-pyside6.qtwidgets \
  python3-pyside6.qtgui python3-pyside6.qtopengl
```

### 2. Clone and Install
```bash
git clone https://github.com/thecipher24/RFwatch.git
cd RFwatch
pip install -r requirements.txt
pip install -e .  # editable install
```

### 3. Verify
```bash
hackrf_info              # Should detect your HackRF
python -m pytest tests/  # All tests pass
python -m ui.app         # GUI launches
python cli/run.py --duration 5 --freq 100e6  # CLI works
```

## Code Style

- **PEP 8** with 100-character line limit
- **Type hints** on all public function signatures
- **No comments on obvious code** — comments explain *why*, not *what*
- **No speculative features** — implement only what's asked
- **SPDX license header** in every source file: `# SPDX-License-Identifier: MIT`

## Architecture Rules

1. `core/` must never import GNU Radio — pure Python only
2. All Qt cross-thread signals must use `QueuedConnection`
3. No ML, no black-box classification — everything deterministic and explainable
4. Config single source of truth: `core/config.py` → `RFConfig`
5. No simulated data — if HackRF isn't available, return `None`

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test
python -m pytest tests/test_detector.py -v

# Run with live hardware (requires HackRF)
python cli/run.py --freq 100e6 --duration 5
```

## Pull Request Process

1. Branch naming: `refactor/<description>`, `fix/<description>`, `feat/<description>`
2. Commit messages: conventional commits (`fix:`, `feat:`, `refactor:`, `docs:`)
3. Ensure tests pass and lint is clean
4. Update `ARCHITECTURE.md` if layer boundaries or data flow changes
5. Update `CLAUDE.md` if critical rules, env vars, or project structure changes

## CI/CD

The project uses GitHub Actions:
- Tests run on push and PR
- Verifies Python package install
- Linting via ruff (config in pyproject.toml)

## Project Structure

```
rfwatch/
├── core/             # Pure Python signal processing
├── grblocks/         # GNU Radio integration
├── ui/               # PySide6 desktop UI
├── utils/            # DSP helpers and utilities
├── cli/              # Headless CLI
└── tests/            # pytest unit tests
```
