# RF Inspector

RF signal detection and analysis system.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

RF Inspector is a desktop application for detecting, analyzing, and visualizing radio-frequency (RF) signals in real time. It is designed to work with Software Defined Radio (SDR) hardware (currently HackRF One) and provides both focused single-band inspection and wideband scanning capabilities.

The tool emphasizes physical-layer signal understanding rather than protocol decoding or modulation guessing.

---

## Screenshots

Below are a few UI screenshots to give a quick feel for the workflow and capabilities.

![Inspector mode (live spectrum + controls)](assets/rfwatch_inspector.png)
Inspector mode: live spectrum view with controls for tuning and inspecting a single band in real time.

![Signal details (event breakdown)](assets/rfwatch_signaldetails.png)
Signal details: event-centric view showing the measured characteristics of a detected signal over time.

![Scanner mode (wideband sweep + results)](assets/rfwatch_scanner.png)
Scanner mode: sweep across a frequency range and summarize activity as detected events.

![Transmit controls in Inspector](/assets/rfwatch_inspector_tx.png)
Inspector TX: transmit test signals (Noise + Tone) at a chosen frequency for validation and experiments (HackRF required).

![Quick TX from scan results](/assets/rfwatch_tx.png)
Scan Results TX: quickly transmit at a detected frequency directly from the scan results table.

---

## Core Philosophy & Vision

RF Inspector is built around a few deliberate principles that guide both its architecture and feature set.

### Physical-Layer First

RF Inspector operates strictly at the **physical layer**.  
It observes energy, bandwidth, time behavior, and stability — not packets, protocols, or modulation schemes.

If something cannot be supported directly by the RF data and hardware limits, RF Inspector does not guess.

### Events, Not Guesswork

Instead of forcing users to interpret raw waterfalls and instantaneous spectra, RF Inspector treats RF activity as **events**:

- When a signal appears
- How long it persists
- How wide it is
- How stable or bursty it behaves over time

This event-centric model allows the system to summarize RF behavior honestly and consistently.

### Honest Constraints

RF Inspector does not attempt to hide or “work around” hardware limitations.

For example:
- HackRF’s instantaneous bandwidth is respected
- Wideband monitoring is implemented via time-sliced scanning, not false continuity
- Power measurements are relative, not calibrated

The goal is **clarity**, not illusion.

### Deterministic, Explainable Analysis

All analysis in RF Inspector is deterministic and explainable:
- No machine learning
- No black-box classification
- No protocol inference

Every displayed value can be traced back to observable RF behavior.

### Long-Term Vision

RF Inspector aims to become a **reliable RF inspection and monitoring foundation**, suitable for:
- RF exploration and learning
- Research and experimentation
- Security and spectrum monitoring
- Building higher-level RF tooling

Future versions may add deeper analysis layers, but never at the cost of transparency or trust.

---

## Features

-   **Real-time Spectrum Analysis**: Visualize RF spectrum in real-time.
-   **Signal Detection**: Automated detection of signals based on power and SNR.
-   **Event Tracking**: Tracks signal events over time, recording start/end times and characteristics.
-   **Transmission**: Capable of transmitting test signals (Noise + Tone) at user-defined frequencies (requires HackRF).
-   **Dual Modes**:
    -   **Inspector Mode**: Continuous monitoring of a single frequency.
    -   **Scanner Mode**: Sweeps across a user-defined frequency range.
-   **Hardware Support**: Integrated with HackRF via GNU Radio.
-   **Modular Architecture**: Clean separation between UI, Core Engine, and Hardware abstraction.

## Project Structure

```
rf_inspector/
├── core/           # Core detection engine (the brain)
├── grblocks/       # GNU Radio integration blocks
├── ui/             # User interface (PySide6/PyQt)
├── utils/          # Shared DSP and utility functions
├── cli/            # Command-line interface
└── tests/          # Unit tests
```

## Core Modules

-   **config.py**: Single source of truth for all configuration parameters.
-   **event.py**: Signal event object definition.
-   **iq_stream.py**: Thread-safe IQ sample buffer.
-   **detector.py**: Binary signal detection (power + SNR estimation).
-   **segmenter.py**: Frequency and time segmentation.
-   **event_store.py**: Central thread-safe event storage.
-   **feature_extractor.py**: Feature extraction from completed events.

## Architecture

### Four-Layer Design

```
┌─────────────────────────────────────────┐
│  UI (Control Panel + Display)           │
│  - Mode selector (Inspector/Scanner)    │
│  - Frequency inputs                     │
│  - Start/Stop buttons                   │
│  - Live spectrum display                │
│  - Progress bar (scanner mode)          │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│  EngineController (Mode Management)     │
│  - Owns Inspector & Scanner modes       │
│  - Manages start/stop lifecycle         │
│  - Handles hardware retuning            │
│  - Controls scan loops                  │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│  Engine (RF Analysis - Pure Pipeline)   │
│  - Detector (binary detection)          │
│  - Segmenter (frequency analysis)       │
│  - EventBuilder (time aggregation)      │
│  - FeatureExtractor (on event close)    │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│  IQ Source (Hardware)                   │
│  - HackRF (live RF data)                │
└─────────────────────────────────────────┘
```

### Core Principle
**UI never runs loops, never retunes hardware, never decides "what happens next".**
The Engine Controller owns modes and execution. UI is just a control panel.

## Installation

### Prerequisites
-   Linux (Recommended)
-   Python 3.8+
-   GNU Radio 3.8+ (with Python bindings)
-   HackRF tools and libraries (`libhackrf`, `gr-osmosdr`)

### Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/rf_inspector.git
    cd rf_inspector
    ```

2.  **Create a virtual environment:**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

    *Note: You may need to install `gnuradio` and `osmosdr` via your system package manager (e.g., `apt install gnuradio gr-osmosdr` on Ubuntu/Debian).*

## Usage

### GUI (Recommended)

To run the main application:

```bash
source .venv/bin/activate
python -m ui.app
```

#### Hardware Control
-   **Force HackRF**: To force real HackRF data (skips safety checks):
    ```bash
    export RF_INSPECTOR_FORCE_HACKRF=1
    python -m ui.app
    ```

#### Transmission Features
The application includes transmission capabilities for testing and signal generation.
1.  **Enable Transmission**: Go to Settings (gear icon) and check "Enable Transmission".
2.  **Manual Transmission**: Use the "TX" controls in Inspector or Scanner mode to set a frequency and transmit a test signal (Noise + Tone).
3.  **Quick Action**: In the Scan Results table, use the "TX" button to quickly transmit on a detected frequency.

### CLI

To run the command-line interface for headless detection:

```bash
python cli/run.py --duration 10 --sample-rate 2e6 --threshold 6.0
```

## Testing

Run the test suite to verify installation:

```bash
python -m pytest tests/ -v
```

## Troubleshooting

-   **HackRF not found**: Ensure your user has permission to access USB devices. You might need to install udev rules for HackRF.
    ```bash
    sudo apt install hackrf
    ```
-   **GNU Radio Import Errors**: Ensure that the Python environment can see the system GNU Radio packages. Sometimes it's easier to use the system Python or link the site-packages.

## Project Status

RF Inspector is currently in **early-stage development (v1)**.

The core architecture and feature set are stable, but the project is expected to evolve as new capabilities and refinements are added. The current release focuses on correctness, transparency, and physical-layer accuracy rather than breadth of features. Designed for correctness over completeness.

Contributions welcome. Feedback encouraged.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

RF Inspector is created and maintained by **Pranav Dhiran**.

This project originated as an effort to build an honest, event-centric RF inspection tool that respects physical-layer constraints and avoids protocol-level guessing.

