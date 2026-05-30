# RFwatch — LLM Agent Guide

## Project Overview
RF signal detection and analysis desktop app for HackRF One.
Built with GNU Radio + PySide6 + Python.

## Quick Start
```bash
# System deps (Debian/Kali)
sudo apt install gnuradio gr-osmosdr hackrf \
  python3-pyside6.qtcore python3-pyside6.qtwidgets \
  python3-pyside6.qtgui python3-pyside6.qtopengl

# Python deps
pip install -r requirements.txt

# Run GUI
python -m ui.app

# Run CLI
python cli/run.py --freq 100e6 --duration 10
```

## Project Structure
```
rfwatch/
├── core/             # Pure Python signal processing (no GNU Radio)
│   ├── config.py         # RFConfig — all user-configurable params
│   ├── detector.py       # Binary signal presence (power + SNR hysteresis)
│   ├── segmenter.py      # FFT-based frequency segmentation
│   ├── event_builder.py  # Time aggregation of segments → SignalEvent
│   ├── feature_extractor.py  # Feature extraction on event close
│   ├── emitter_tracker.py    # Emitter identity inference (gated NN)
│   ├── iq_stream.py      # Thread-safe IQ sample buffer (queue.Queue)
│   ├── engine_controller.py  # Mode lifecycle, state machine
│   └── event.py          # SignalEvent dataclass
├── grblocks/          # GNU Radio integration
│   ├── flowgraph.py       # HackRF flowgraph builder
│   └── iq_source_block.py # Custom GNU Radio sink block
├── ui/                # PySide6 desktop UI
│   ├── app.py             # QApplication entry point
│   ├── main_window.py     # Main window, all controls
│   ├── spectrum_view.py   # Real-time spectrum + waterfall
│   ├── signal_list.py     # Emitter list table
│   ├── event_detail.py    # Event inspector dock panel
│   ├── scan_results.py    # Scanner results table
│   └── settings_store.py  # JSON persistence in ~/.rfwatch/
├── cli/               # Headless CLI
├── utils/             # DSP helpers (PSD, stats, logging)
└── tests/             # pytest unit tests
```

## Architecture: Four-Layer Design
```
┌─────────────────────────────────────────┐
│  UI (PySide6 Widgets)                   │
│  Sends config + start/stop commands     │
│  Never runs loops or retunes hardware   │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│  EngineController (QObject)             │
│  Owns modes (Inspector / Scanner)       │
│  Manages start/stop lifecycle           │
│  Runs engine thread                     │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│  Engine Pipeline (Pure Python)          │
│  Detector → Segmenter → EventBuilder    │
│  → FeatureExtractor → EmitterTracker    │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│  IQ Source (GNU Radio Flowgraph)        │
│  HackRF → DC Blocker → Vector Sink      │
│  Lives in daemon thread, segfault-safe  │
└─────────────────────────────────────────┘
```

## Critical Rules
1. **`core/` must never import GNU Radio** — pure Python only. Import errors crash the app.
2. **All Qt cross-thread signals use `QueuedConnection`** — controller emits from worker thread.
3. **No ML, no black-box classification** — everything is deterministic and explainable.
4. **Config single source of truth** is `core/config.py` → `RFConfig`. UI and engine both read from it.
5. **HackRF source args** via env var `RFWATCH_HACKRF_ARGS` (default: `numchan=1 hackrf=0`).
6. **Data source detection** is a multi-method subprocess probe (`_test_hackrf_safe()` in `engine_controller.py`).
7. **No simulated data** — if HackRF isn't available, the engine returns `None` chunks.

## Signal Processing Pipeline
```
IQ Chunk
  → Detector.process() → DetectionResult(present, power_db, noise_floor_db, snr_db)
  → Segmenter.process() → List[dict{low_hz, high_hz, center_hz, bandwidth_hz, confidence}]
  → EventBuilder.process() → Dict{active: [...], closed: [...]}
  → FeatureExtractor.extract(event) → features dict
  → EmitterTracker.process_closed_event(event) → Emitter
```

## Environment Variables
| Variable | Default | Purpose |
|---|---|---|
| `RFWATCH_FORCE_HACKRF` | — | Skip HackRF safety probe |
| `RFWATCH_HACKRF_ARGS` | `numchan=1 hackrf=0` | HackRF source arguments |
| `RFWATCH_HACKRF_BIAS_T` | — | Enable antenna power |
| `RFWATCH_DEBUG` | — | Debug logging |
| `RFWATCH_DEBUG_DETECTOR` | — | Detector per-chunk debug |
| `RFWATCH_UI_PSD_INTERVAL_S` | `0.1` | PSD publish throttle |

## Testing
```bash
python -m pytest tests/ -v
```

## Common Pitfalls
- `PySide6.QtCore` will not import if `python3-pyside6.qtcore` apt package is missing (yes, even though PySide6 base is installed).
- The `_test_hackrf_safe()` subprocess method (`engine_controller.py:248`) previously had a hardcoded `cwd` path — now removed.
- `osmosdr.source()` can segfault with certain HackRF firmware versions — flowgraph runs in daemon thread for isolation.
