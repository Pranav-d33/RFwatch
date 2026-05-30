# LLM-Friendly Improvements for RFwatch

This document outlines how to make RFwatch more accessible to LLM-based coding agents (Claude Code, Cursor, Copilot, etc.) and easier for contributors to understand and work with.

## 1. Create a `CLAUDE.md` (or `AGENTS.md`)

An LLM instructions file is the single highest-impact change. It tells an LLM agent the project's conventions, architecture, and critical rules so it doesn't have to guess or waste context exploring.

```markdown
# RFwatch for LLM Agents

## Project
RF signal detection and analysis system using HackRF + GNU Radio + PySide6.

## Quick Start
```bash
# System deps (Debian/Kali)
sudo apt install gnuradio gr-osmosdr hackrf \
  python3-pyside6.qtcore python3-pyside6.qtwidgets \
  python3-pyside6.qtgui python3-pyside6.qtopengl

# Python deps
pip install -r requirements.txt

# Run
python -m ui.app
```

## Architecture
- `core/` - Pure Python signal processing (no GNU Radio dependency)
- `grblocks/` - GNU Radio flowgraph integration (hardware abstraction)
- `ui/` - PySide6 Qt widgets
- `utils/` - DSP and statistical helpers

## Critical Rules
1. NEVER import GNU Radio in `core/` modules — they must remain pure Python
2. All Qt signals must use `QueuedConnection` when emitted from worker threads
3. Config lives in `core/config.py` as `RFConfig` — single source of truth
4. No ML, no black-box classification — everything must be deterministic and explainable
5. HackRF source args are controlled via `RFWATCH_HACKRF_ARGS` env var
6. The flowgraph lives in a subprocess for segfault isolation

## Key Files
- `core/engine_controller.py` - Main controller, owns mode lifecycle
- `core/detector.py` - Binary signal presence detection
- `core/segmenter.py` - Frequency segmentation via FFT
- `grblocks/flowgraph.py` - GNU Radio flowgraph builder
- `ui/main_window.py` - Main window and all controls
```

**Impact**: Saves ~20-30 tool calls every time an LLM agent first encounters the project.

## 2. Add `llms.txt` or `llms-full.txt`

Following the emerging `llms.txt` standard (https://llmstxt.org/), add a file that tells LLMs the key entry points:

```markdown
# RFwatch

RFwatch is a desktop application for detecting, analyzing, and visualizing
radio-frequency (RF) signals using HackRF One SDR hardware.

## Key Docs
- README.md: Full project documentation
- ARCHITECTURE.md: Architecture overview and design decisions
- CONTRIBUTING.md: How to contribute

## Core Modules
- core/engine_controller.py: Main lifecycle controller
- core/detector.py: Signal detection with hysteresis
- core/segmenter.py: FFT-based frequency segmentation
- core/emitter_tracker.py: Emitter identity inference
- grblocks/flowgraph.py: GNU Radio HackRF flowgraph
- ui/main_window.py: PySide6 main window

## Quick Install
System: apt install gnuradio gr-osmosdr hackrf \
  python3-pyside6.qtcore python3-pyside6.qtwidgets \
  python3-pyside6.qtgui python3-pyside6.qtopengl
Python: pip install -r requirements.txt
Run: python -m ui.app
```

## 3. Add `ARCHITECTURE.md`

Move the architecture section from README into a dedicated page. Include:
- The four-layer design (UI → Controller → Engine → Hardware)
- Data flow diagrams
- How event pipeline works (Detector → Segmenter → EventBuilder → EmitterTracker)
- Thread model (which threads exist, what they own)

## 4. Add `CONTRIBUTING.md`

Standard file covering:
- How to set up a dev environment
- Code style (PEP 8, type hints, no comments on obvious code)
- Testing expectations
- PR process

## 5. Standardize the License Notice

The current LICENSE is MIT — good. But add a short header to each source file:

```python
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran
```

This makes it clear for LLMs and automated tooling that the code is MIT-licensed and free to use.

## 6. Add Python Type Hints (Stub)

Most functions lack type annotations. Adding them helps LLMs understand function signatures without reading implementation. Focus on:

- All public function signatures in `core/`
- Dataclass fields (already done in `event.py`, `emitter_tracker.py`)
- Return types on key pipeline methods

## 7. Add a `VERSION` File

A simple `VERSION` file with the current version number helps LLMs and CI tooling track what's current.

## 8. Review `__init__.py` Files

The current `__init__.py` files are single-line docstrings. Consider re-exporting key symbols so that `from core import Detector` works instead of `from core.detector import Detector`. This makes the public API surface explicit.

## 9. Dependency Management Improvements

- Pin exact versions in `requirements.txt` (or use `pyproject.toml` with `[project]` table)
- Consider adding a `setup.py` or `pyproject.toml` so `pip install -e .` works
- Document system dependencies with a `install.sh` or in `CONTRIBUTING.md`

## 10. Conventional Commit Format

The commit messages are already reasonable. Adopting conventional commits (`fix:`, `feat:`, `docs:`, etc.) makes changelog generation and LLM parsing easier.

## Summary Priority Table

| Item | Effort | Impact for LLMs | Impact for Humans |
|---|---|---|---|
| CLAUDE.md | Low | Very High | Low |
| ARCHITECTURE.md | Medium | High | High |
| Type hints | Medium | High | High |
| CONTRIBUTING.md | Low | Medium | High |
| llms.txt | Low | High | Low |
| pyproject.toml | Low | Medium | Medium |
| SPDX headers | Low | Low | Medium |
| __init__ exports | Low | Medium | Medium |
| VERSION file | Low | Low | Low |
