# RFwatch Architecture

## Four-Layer Design

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

## Layer Responsibilities

### UI Layer (`ui/`)
- Pure Qt widgets — no signal processing, no hardware control
- Communicates with EngineController via Qt signals (QueuedConnection from worker threads)
- Two modes: Inspector (single frequency) and Scanner (frequency sweep)
- Reads from EventStore/EmitterStore for display; never writes directly

### EngineController (`core/engine_controller.py`)
- QObject that owns the mode state machine
- `ControllerState`: IDLE → RUNNING_INSPECTOR / RUNNING_SCANNER → STOPPING → IDLE
- Emits Qt signals: `state_changed`, `scan_progress`, `scan_result_ready`, `analysis_reset`
- Manages engine thread lifecycle
- Handles hardware retuning via `_retune_to_frequency()` (stop → rebuild → start flowgraph)

### Engine Pipeline (`core/`)
Pure Python processing chain — no GNU Radio imports:

```
IQ Chunk (np.complex64)
  → Detector.process()
    → DetectionResult(present, power_db, noise_floor_db, snr_db)
  → Segmenter.process(iq)
    → List[segment{low_hz, high_hz, center_hz, bandwidth_hz, confidence}]
  → EventBuilder.process(timestamp, detected, segments)
    → Dict{active: [SignalEvent], closed: [SignalEvent]}
  → FeatureExtractor.extract(event)
    → features dict
  → EmitterTracker.process_closed_event(event)
    → Emitter (or None if no valid features)
```

### IQ Source (`grblocks/`)
- `flowgraph.py`: Builds GNU Radio flowgraph: `osmosdr.source → dc_blocker_cc → vector_sink_c`
- `iq_source_block.py`: Custom GNU Radio sync block (used in test flowgraph only)
- Runs in a daemon thread for segfault isolation
- HackRF safety is tested via subprocess before starting

## Thread Model

| Thread | Owns | Communicates via |
|---|---|---|
| Main (Qt) | UI widgets, EventStore, EmitterStore | Qt signals (QueuedConnection) |
| Engine | Engine pipeline, flowgraph start/stop | Qt signals from controller |
| IQStreamPuller | Polls vector_sink, pushes to IQStream | queue.Queue |
| Flowgraph (GNU Radio) | HackRF hardware | vector_sink → queue.Queue |

## Data Flow: Inspector Mode

```
HackRF → osmosdr.source → dc_blocker → vector_sink
                                              ↓  (polled by IQStreamPuller)
                                         IQStream (queue.Queue)
                                              ↓  (popped by engine thread)
                                    ┌─────────────────────┐
                                    │  Detector.process() │──→ DetectionResult
                                    └─────────────────────┘
                                              ↓  (IQ samples also passed)
                                    ┌─────────────────────┐
                                    │  Segmenter.process() │──→ List[segments]
                                    └─────────────────────┘
                                              ↓
                                    ┌──────────────────────┐
                                    │  EventBuilder.process │──→ active / closed
                                    └──────────────────────┘
                                              ↓ (closed events)
                                    ┌─────────────────────────┐
                                    │ EmitterTracker.process  │──→ Emitter
                                    └─────────────────────────┘
                                              ↓ (Qt signal)
                                          UI Display
```

## Data Flow: Scanner Mode

Same pipeline per dwell step, plus:
1. Retune HackRF to next frequency
2. Dwell for configured duration
3. Collect closed events → `ScanResult`
4. Emit `scan_result_ready` to populate scan results table
5. Repeat until stop requested

## State Machine

```
                    ┌──────────┐
                    │   IDLE   │◄──────────────────┐
                    └────┬─────┘                    │
                         │ start_inspector/         │
                         │ start_scanner            │
                         ▼                          │
              ┌─────────────────────┐               │
              │  RUNNING_INSPECTOR  │               │
              │  or RUNNING_SCANNER │── stop() ─────┘
              └──────────┬──────────┘
                         │ stop() called
                         ▼
                    ┌──────────┐
                    │ STOPPING │
                    └────┬─────┘
                         │ engine thread joined,
                         │ hardware stopped
                         ▼
                    ┌──────────┐
                    │   IDLE   │
                    └──────────┘
```

## HackRF Detection Flow

```
EngineController.__init__()
  → GR_AVAILABLE = (gnuradio import succeeds)
  → use_hackrf = GR_AVAILABLE (default)

start_inspector() / start_scanner()
  → _test_hackrf_safe()
    1. If RFWATCH_FORCE_HACKRF set → skip probe, assume available
    2. Subprocess test: import osmosdr + create source
    3. Fallback: lsusb for HackRF VID:PID (1d50:6089)
    4. Fallback: check /dev/hackrf0
  → If all fail → RuntimeError("HackRF device not detected")
  → If success → build_flowgraph() → start()
```

## Event Lifecycle

```
segment unmatched → _start_event() → active_events[]
segment matched   → _update_event() → hit_count++
no match for N iterations → _close_event()
  → FeatureExtractor.extract(event) → features
  → EmitterTracker.process_closed_event(event)
  → event moved to closed_events[]
```

## Emitter Lifecycle

```
closed_event arrives → _event_to_observation()
  → _associate(): gated nearest-neighbor against active emitters
    → _in_gate(): frequency, bandwidth, time, and overlap gates
    → _distance(): weighted distance in normalized feature space
  → If match: _update_emitter()
  → If no match: _spawn_emitter()
  → _expire_emitters(): close emitters past emitter_timeout_s
```
