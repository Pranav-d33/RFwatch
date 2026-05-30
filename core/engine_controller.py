"""
Engine Controller - Owns modes, start/stop, retuning, and sweeping.

Core Principle:
    The Engine owns modes and execution.
    The UI only sends configuration + start/stop commands.

This controller is the bridge between UI (control panel) and Engine (RF analysis).

Responsibilities:
    - Mode management (INSPECTOR vs SCANNER)
    - Start/stop lifecycle
    - Hardware retuning (HackRF frequency/gain changes)
    - Sweep loop (for scanner mode)
    - State tracking (IDLE, RUNNING_INSPECTOR, RUNNING_SCANNER, STOPPING)

NOT responsible for:
    - Actual RF analysis (Detector, Segmenter, etc. own that)
    - UI rendering
    - Event storage
"""

import threading
import time
import subprocess
import sys
import os
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Callable, List
import numpy as np

from PySide6.QtCore import QObject, Signal

from .config import RFConfig
from .iq_stream import IQStream
from .detector import Detector
from .segmenter import Segmenter
from .event_builder import EventBuilder
from .psd_publisher import PSDPublisher
from .event_publisher import EventPublisher
from .emitter_publisher import EmitterPublisher
from .emitter_tracker import EmitterTracker, EmitterTrackerConfig

# Optional environment toggles for HackRF / GNU Radio integration.

# When RFWATCH_FORCE_HACKRF is set, we skip the subprocess safety
# probe and assume HackRF is safe to use, as long as GNU Radio is present.
_HACKRF_FORCED = os.getenv("RFWATCH_FORCE_HACKRF", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

try:
    from grblocks.flowgraph import build_flowgraph
    GR_AVAILABLE = True
except ImportError:
    GR_AVAILABLE = False


class ControllerState(Enum):
    """Explicit controller states."""
    IDLE = "IDLE"
    RUNNING_INSPECTOR = "RUNNING_INSPECTOR"
    RUNNING_SCANNER = "RUNNING_SCANNER"
    STOPPING = "STOPPING"


@dataclass
class InspectorConfig:
    """Configuration for Inspector mode."""
    center_freq: float  # Hz
    sample_rate: float  # Hz (bandwidth)
    gain: float = 40.0  # dB


@dataclass
class ScannerConfig:
    """Configuration for Scanner mode."""
    start_freq: float  # Hz
    stop_freq: float  # Hz
    step: float  # Hz
    dwell_time: float  # seconds
    sample_rate: float  # Hz
    gain: float = 40.0  # dB


@dataclass
class ScanResult:
    """Result from a single scan step."""
    center_freq: float
    dwell_time: float
    closed_events: List = None
    updated_emitters: List[str] = None
    timestamp: float = 0.0


class EngineController(QObject):
    """
    Controls RF engine lifecycle and modes.
    
    Owns:
    - Inspector mode (continuous monitoring)
    - Scanner mode (frequency sweep)
    - Start/stop execution
    - Hardware configuration
    - State machine
    
    Does NOT own:
    - RF analysis (Detector, Segmenter, etc.)
    - Event storage
    - UI rendering
    """

    # Qt signals (UI must connect with QueuedConnection for thread-safety)
    state_changed = Signal(object)          # ControllerState
    scan_progress = Signal(int, int, float) # current_step, total_steps, current_freq_hz
    scan_result_ready = Signal(object)      # ScanResult (emitted at end of dwell)
    analysis_reset = Signal()               # User-initiated reset of analysis state

    def __init__(self):
        """Initialize controller in IDLE state."""
        super().__init__()
        self.state = ControllerState.IDLE
        # Default: use HackRF if GNU Radio is available.
        self.use_hackrf = GR_AVAILABLE
        # If forced, assume HackRF is safe without running the subprocess
        # probe; user explicitly requested real hardware.
        self._hackrf_verified = _HACKRF_FORCED
        
        # Engine components (shared across modes)
        self.config = RFConfig()
        self.iq_stream = IQStream()
        self.detector = Detector(self.config)
        self.segmenter = Segmenter(self.config)
        self.event_builder = EventBuilder(self.config)
        self.psd_publisher = PSDPublisher()
        self.event_publisher = EventPublisher()
        self.emitter_publisher = EmitterPublisher()

        et_cfg = EmitterTrackerConfig(
            f_gate_hz=float(self.config.emitter_f_gate_hz),
            bw_gate_hz=float(self.config.emitter_bw_gate_hz),
            p_gate_db=float(self.config.emitter_p_gate_db),
            timeout_s=float(self.config.emitter_timeout_s),
            f_gate_bw_factor=float(getattr(self.config, "emitter_f_gate_bw_factor", 0.25)),
            bw_gate_bw_factor=float(getattr(self.config, "emitter_bw_gate_bw_factor", 0.50)),
            min_overlap_fraction=float(getattr(self.config, "emitter_min_overlap_fraction", 0.20)),
            wf=float(self.config.emitter_wf),
            wb=float(self.config.emitter_wb),
            wp=float(self.config.emitter_wp),
            wt=float(self.config.emitter_wt),
            wo=float(getattr(self.config, "emitter_wo", 1.0)),
            distance_threshold=float(self.config.emitter_distance_threshold),
            emitter_timeout_s=float(self.config.emitter_death_timeout_s),
        )
        self.emitter_tracker = EmitterTracker(et_cfg, emitter_publisher=self.emitter_publisher)
        
        # HackRF/flowgraph support
        self.flowgraph = None
        
        # Threading
        self._engine_thread = None
        self._stop_requested = False
        self._paused = False
        self._state_lock = threading.Lock()
        
        # Callbacks for UI updates
        self.on_state_changed: Optional[Callable[[ControllerState], None]] = None
        self.on_scan_progress: Optional[Callable[[int, int, float], None]] = None  # (current_step, total_steps, current_freq_hz)
        
        # Scanner state
        self.current_scan_plan = None
        self.scan_results: List[ScanResult] = []
        self.current_scan_index = 0

        # Live-adjustable UI controls
        self._sensitivity_value = 0.5  # 0..1 (higher => more sensitive)

        # UI publishing throttles
        self._last_psd_publish_ts = 0.0
        self._ui_psd_min_interval_s = float(os.getenv("RFWATCH_UI_PSD_INTERVAL_S", "0.1"))

        # Detector holdover (reduces event churn on brief flicker)
        self._last_present_ts = 0.0

    # ========================================================================
    # STATE MANAGEMENT
    # ========================================================================

    def _set_state(self, new_state: ControllerState):
        """Thread-safe state change."""
        with self._state_lock:
            old_state = self.state
            self.state = new_state
            print(f"[CONTROLLER] State: {old_state.value} → {new_state.value}")
            # Emit Qt signal for UI (queued connection recommended)
            try:
                self.state_changed.emit(new_state)
            except Exception:
                # Avoid hard failure if Qt isn't available/initialised in some environments.
                pass

            # Legacy callback API (used by tests/CLI)
            if self.on_state_changed:
                self.on_state_changed(new_state)

    def get_state(self) -> ControllerState:
        """Get current state (thread-safe)."""
        with self._state_lock:
            return self.state

    def _test_hackrf_safe(self) -> bool:
        """
        Test HackRF in subprocess to avoid segfault killing main process.
        
        Returns True if HackRF is available and can be started.
        Uses multiple detection methods for reliability.
        """
        # If user forces HackRF usage, skip the safety subprocess.
        if _HACKRF_FORCED:
            print("[CONTROLLER] HackRF forced via RFWATCH_FORCE_HACKRF; skipping safety test")
            self._hackrf_verified = True
            return True

        if self._hackrf_verified or not self.use_hackrf:
            return self.use_hackrf
        
        print("[CONTROLLER] Testing HackRF availability...")
        
        # Method 1: Test with osmosdr.source() - simplest approach
        test_code_simple = """
import sys
try:
    import osmosdr
    # Try to create source - this will fail if HackRF not present
    src = osmosdr.source(args="numchan=1 hackrf=0")
    if src:
        print("OK")
    else:
        print("FAIL_SOURCE_NONE")
except Exception as e:
    print("FAIL", str(e)[:100])
"""
        
        try:
            result = subprocess.run(
                [sys.executable, "-c", test_code_simple],
                capture_output=True,
                timeout=10.0,
                text=True,
            )
            
            if result.returncode == 0 and "OK" in result.stdout:
                print("[CONTROLLER] ✓ HackRF test passed (osmosdr source created)")
                self._hackrf_verified = True
                return True
            else:
                print("[CONTROLLER] ⚠ HackRF osmosdr test failed")
                print(f"[CONTROLLER]   stdout: {result.stdout.strip()}")
                if result.stderr:
                    print(f"[CONTROLLER]   stderr: {result.stderr.strip()[:300]}")
                # Fall through to alternative methods
                
        except subprocess.TimeoutExpired:
            print("[CONTROLLER] ⚠ HackRF osmosdr test timed out")
        except Exception as e:
            print(f"[CONTROLLER] ⚠ HackRF osmosdr test error: {e}")
        
        # Method 2: Check USB device directly with lsusb
        print("[CONTROLLER] Trying alternative detection (lsusb)...")
        try:
            result = subprocess.run(
                ["lsusb"],
                capture_output=True,
                timeout=5.0,
                text=True
            )
            if "1d50:6089" in result.stdout or "HackRF" in result.stdout:
                print("[CONTROLLER] ✓ HackRF found via lsusb")
                self._hackrf_verified = True
                return True
        except Exception as e:
            print(f"[CONTROLLER] lsusb check failed: {e}")
        
        # Method 3: Check /dev/hackrf0
        print("[CONTROLLER] Checking /dev/hackrf0...")
        try:
            import os
            if os.path.exists("/dev/hackrf0"):
                print("[CONTROLLER] ✓ HackRF device found at /dev/hackrf0")
                self._hackrf_verified = True
                return True
        except Exception as e:
            print(f"[CONTROLLER] /dev/hackrf0 check failed: {e}")
        
        print("[CONTROLLER] ✗ HackRF not detected using any method")
        self.use_hackrf = False
        return False

    # ========================================================================
    # INSPECTOR MODE
    # ========================================================================

    def start_inspector(self, config: InspectorConfig):
        """
        Start Inspector mode (continuous monitoring at one frequency).
        
        User provides:
        - Center frequency
        - Sample rate (bandwidth)
        - Gain (optional)
        
        Controller does:
        1. Validate config
        2. Stop anything currently running
        3. Configure hardware (HackRF)
        4. Start IQ source
        5. Start engine thread
        6. Transition to RUNNING_INSPECTOR
        
        Args:
            config: InspectorConfig with frequency/sample_rate/gain
        """
        current_state = self.get_state()
        if current_state != ControllerState.IDLE:
            print(f"[CONTROLLER] Cannot start: already in {current_state.value}")
            return False

        print(f"[CONTROLLER] Starting Inspector mode: {config.center_freq/1e6:.1f} MHz")

        # Update config
        self.config.center_freq = config.center_freq
        self.config.sample_rate = config.sample_rate
        self.config.gain = config.gain
        
        # Initialize engine components
        self.reset_analysis_state()

        # Configure HackRF (REQUIRED)
        if self.use_hackrf:
            # Test HackRF safety first (in subprocess to avoid segfault in main process)
            if not self._test_hackrf_safe():
                print("[CONTROLLER] ERROR: HackRF device not detected. Please connect HackRF and try again.")
                self._set_state(ControllerState.IDLE)
                raise RuntimeError("HackRF device not detected. Please connect HackRF and try again.")
            else:
                try:
                    self.flowgraph = build_flowgraph(self.config, self.iq_stream)
                    print("[CONTROLLER] HackRF flowgraph initialized")
                except Exception as e:
                    print(f"[CONTROLLER] ERROR: HackRF initialization failed: {e}")
                    self._set_state(ControllerState.IDLE)
                    raise RuntimeError(f"HackRF initialization failed: {e}")
        else:
            # HackRF not available
            print("[CONTROLLER] ERROR: HackRF required but not available. Please connect HackRF.")
            self._set_state(ControllerState.IDLE)
            raise RuntimeError("HackRF device not detected. Please connect HackRF and try again.")

        # Start IQ source
        if self.use_hackrf and self.flowgraph:
            try:
                self.flowgraph.start()
                print("[CONTROLLER] HackRF flowgraph started")
            except Exception as e:
                print(f"[CONTROLLER] ERROR: Failed to start flowgraph: {e}")
                self._set_state(ControllerState.IDLE)
                raise RuntimeError(f"Failed to start HackRF: {e}")

        # Start engine thread
        self._stop_requested = False
        self._set_state(ControllerState.RUNNING_INSPECTOR)
        self._engine_thread = threading.Thread(
            target=self._inspector_loop,
            name="InspectorEngine",
            daemon=False
        )
        self._engine_thread.start()
        return True

    def pause_engine(self):
        """Pause the engine (stop flowgraph, keep loop running)."""
        print("[CONTROLLER] Pausing engine for transmission...")
        self._paused = True
        if self.flowgraph:
            try:
                self.flowgraph.stop()
                self.flowgraph.wait()
            except Exception as e:
                print(f"[CONTROLLER] Error stopping flowgraph during pause: {e}")

    def resume_engine(self):
        """Resume the engine (restart flowgraph)."""
        print("[CONTROLLER] Resuming engine after transmission...")
        if self.flowgraph:
            try:
                self.flowgraph.start()
            except Exception as e:
                print(f"[CONTROLLER] Error restarting flowgraph during resume: {e}")
        self._paused = False

    def _inspector_loop(self):
        """Inspector mode main loop (runs on engine thread)."""
        print("[ENGINE] Inspector loop started")
        print(f"[ENGINE] Data source: {'HackRF' if self.use_hackrf else 'Unknown'}")
        print(f"[ENGINE] Center freq: {self.config.center_freq/1e6:.2f} MHz")
        print(f"[ENGINE] Bandwidth: {self.config.sample_rate/1e6:.2f} MHz")
        
        while not self._stop_requested:
            if self._paused:
                time.sleep(0.1)
                continue

            try:
                # Get IQ chunk
                iq = self._get_next_iq_chunk()
                if iq is None:
                    time.sleep(0.05)
                    continue

                # Process through pipeline
                det = self.detector.process(iq)
                # Always run the segmenter to keep the PSD/UI responsive.
                # IMPORTANT: do not treat raw segments as "detection"; the segmenter
                # will produce many small segments on pure noise by design.
                segments_bb = self.segmenter.process(iq)
                segments = self._shift_segments_to_absolute(segments_bb)

                now_ts = time.time()
                if bool(getattr(det, "present", False)):
                    self._last_present_ts = now_ts

                hold_s = float(getattr(self.config, "detector_hold_s", 0.0) or 0.0)
                # Holdover only applies if we were recently present AND we still
                # have plausible segments (prevents false events in empty bands).
                effective_present = bool(getattr(det, "present", False)) or (
                    hold_s > 0.0
                    and (now_ts - float(self._last_present_ts)) <= hold_s
                    and bool(segments)
                )
                
                # Update event builder
                eb_result = self.event_builder.process(
                    timestamp=now_ts,
                    detected=effective_present,
                    segments=segments if effective_present else [],
                )

                # Closed events -> emitter tracking (events are observations)
                try:
                    for ev in (eb_result.get("closed") or []):
                        self.emitter_tracker.process_closed_event(ev)
                except Exception:
                    pass

                # Publish PSD snapshot (throttled, with safety check)
                if hasattr(self.segmenter, 'last_psd') and self.segmenter.last_psd:
                    try:
                        now = time.time()
                        if (now - self._last_psd_publish_ts) < self._ui_psd_min_interval_s:
                            time.sleep(0.01)
                            continue
                        self._last_psd_publish_ts = now

                        freqs, psd = self.segmenter.last_psd
                        freqs = np.asarray(freqs, dtype=np.float64) + float(self.config.center_freq)
                        snapshot = {
                            "freqs": freqs,
                            "psd": psd,
                            "detected": det.present,
                            "segments": [
                                {
                                    "low_hz": seg["low_hz"],
                                    "high_hz": seg["high_hz"],
                                    "confidence": seg["confidence"]
                                } for seg in segments
                            ]
                        }
                        self.psd_publisher.publish(snapshot)
                    except Exception as e:
                        print(f"[ENGINE] PSD publish error: {e}")
                
                time.sleep(0.05)
            except Exception as e:
                print(f"[ENGINE] Inspector loop error: {e}")
                time.sleep(0.05)

        print("[ENGINE] Inspector loop stopped")

    # ========================================================================
    # SCANNER MODE
    # ========================================================================

    def start_scanner(self, config: ScannerConfig):
        """
        Start Scanner mode (sweep across frequency range).
        
        User provides:
        - Start frequency
        - Stop frequency
        - Step size
        - Dwell time
        - Sample rate
        - Gain (optional)
        
        Controller does:
        1. Validate config
        2. Build scan plan
        3. Start engine thread running scanner loop
        4. Transition to RUNNING_SCANNER
        
        Args:
            config: ScannerConfig with frequency range and dwell time
        """
        current_state = self.get_state()
        if current_state != ControllerState.IDLE:
            print(f"[CONTROLLER] Cannot start: already in {current_state.value}")
            return False

        print(f"[CONTROLLER] Starting Scanner mode: {config.start_freq/1e6:.1f} - "
              f"{config.stop_freq/1e6:.1f} MHz, step {config.step/1e3:.1f} kHz")

        # Build scan plan
        self.current_scan_plan = []
        freq = config.start_freq
        while freq <= config.stop_freq:
            self.current_scan_plan.append(freq)
            freq += config.step

        print(f"[CONTROLLER] Scan plan: {len(self.current_scan_plan)} steps")

        # Store configuration
        self.config.sample_rate = config.sample_rate
        self.config.gain = config.gain

        # Initialize engine components
        self.reset_analysis_state()

        # Configure HackRF (REQUIRED)
        if self.use_hackrf:
            # Test HackRF safety first (in subprocess to avoid segfault in main process)
            if not self._test_hackrf_safe():
                print("[CONTROLLER] ERROR: HackRF device not detected. Please connect HackRF and try again.")
                self._set_state(ControllerState.IDLE)
                raise RuntimeError("HackRF device not detected. Please connect HackRF and try again.")
            else:
                try:
                    # Set initial frequency
                    self.config.center_freq = config.start_freq
                    self.flowgraph = build_flowgraph(self.config, self.iq_stream)
                    print("[CONTROLLER] HackRF flowgraph initialized for scanner")
                except Exception as e:
                    print(f"[CONTROLLER] ERROR: HackRF initialization failed: {e}")
                    self._set_state(ControllerState.IDLE)
                    raise RuntimeError(f"HackRF initialization failed: {e}")
        else:
            # HackRF not available
            print("[CONTROLLER] ERROR: HackRF required but not available. Please connect HackRF.")
            self._set_state(ControllerState.IDLE)
            raise RuntimeError("HackRF device not detected. Please connect HackRF and try again.")

        # Start flowgraph if available (with signal safety)
        if self.use_hackrf and self.flowgraph:
            try:
                print("[CONTROLLER] Starting HackRF flowgraph...")
                # Attempt to start - may cause segfault with some firmware versions
                try:
                    self.flowgraph.start()
                    time.sleep(0.1)
                    print("[CONTROLLER] HackRF flowgraph started successfully")
                except (SystemExit, KeyboardInterrupt):
                    raise
                except Exception as fg_error:
                    # Segfault or other C-level error
                    print(f"[CONTROLLER] ERROR: Flowgraph startup error: {fg_error}")
                    self._set_state(ControllerState.IDLE)
                    raise RuntimeError(f"Failed to start HackRF flowgraph: {fg_error}")
            except Exception as e:
                print(f"[CONTROLLER] ERROR: Failed to initialize flowgraph: {e}")
                self._set_state(ControllerState.IDLE)
                raise RuntimeError(f"Failed to start HackRF: {e}")

        # Reset scan results
        self.scan_results = []
        self.current_scan_index = 0

        # Start scanner thread
        self._stop_requested = False
        self._set_state(ControllerState.RUNNING_SCANNER)
        self._engine_thread = threading.Thread(
            target=self._scanner_loop,
            args=(config,),
            name="ScannerEngine",
            daemon=False
        )
        self._engine_thread.start()
        return True

    # ========================================================================
    # LIVE UI CONTROLS
    # ========================================================================

    def set_gain(self, gain_db: float) -> None:
        """Update RF gain (best-effort live update)."""
        try:
            self.config.gain = float(gain_db)
        except Exception:
            return

        # If HackRF is running, try live update without restarting.
        if self.use_hackrf and self.flowgraph:
            if hasattr(self.flowgraph, "set_gain"):
                ok = self.flowgraph.set_gain(self.config.gain)
                if ok:
                    return

            # Fallback: rebuild flowgraph at same center frequency.
            try:
                self._retune_to_frequency(float(self.config.center_freq))
            except Exception:
                pass

    def set_detection_sensitivity(self, sensitivity_0_to_1: float) -> None:
        """Set user-facing sensitivity (0..1); maps to SNR thresholds."""
        try:
            s = float(sensitivity_0_to_1)
        except Exception:
            return
        s = max(0.0, min(1.0, s))
        self._sensitivity_value = s

        # Higher sensitivity => lower enter threshold.
        # Map 0..1 => 15 dB .. 3 dB (clamped).
        enter_db = 15.0 + (3.0 - 15.0) * s
        exit_db = max(0.0, enter_db - 4.0)
        self.config.snr_enter_db = float(enter_db)
        self.config.snr_exit_db = float(exit_db)

    def reset_analysis_state(self) -> None:
        """Reset detector noise floor + events without stopping RX."""
        # Do not stop hardware; just reset analysis pipeline.
        self._reset_engine_state()
        try:
            self.emitter_tracker.reset()
        except Exception:
            pass
        try:
            self.analysis_reset.emit()
        except Exception:
            pass

    def _scanner_loop(self, config: ScannerConfig):
        """
        Scanner mode main loop (runs on engine thread).
        
        Continuously scans the frequency range until stop is requested.
        Each complete sweep is one "iteration" of the loop.
        """
        print("[ENGINE] Scanner loop started (continuous mode)")
        print(f"[ENGINE] Data source: {'HackRF' if self.use_hackrf else 'Unknown'}")
        print(f"[ENGINE] Scan range: {config.start_freq/1e6:.2f} - {config.stop_freq/1e6:.2f} MHz")
        print(f"[ENGINE] Step size: {config.step/1e6:.2f} MHz")
        iteration = 1
        first_freq = True  # Skip retune on first iteration (already tuned in start_scanner)
        
        while not self._stop_requested:
            if self._paused:
                time.sleep(0.1)
                continue

            print(f"[ENGINE] === SCAN ITERATION {iteration} ===")
            
            for idx, center_freq in enumerate(self.current_scan_plan):
                if self._stop_requested:
                    print("[ENGINE] Scanner loop: stop requested, exiting")
                    break

                # Check pause inside the inner loop too
                while self._paused and not self._stop_requested:
                    time.sleep(0.1)
                
                if self._stop_requested:
                    break

                step_num = idx + 1
                total_steps = len(self.current_scan_plan)
                
                print(f"[ENGINE] Scan step {step_num}/{total_steps} (iteration {iteration}): {center_freq/1e6:.1f} MHz")

                # Notify UI of progress
                try:
                    self.scan_progress.emit(step_num, total_steps, center_freq)
                except Exception:
                    pass

                if self.on_scan_progress:
                    self.on_scan_progress(step_num, total_steps, center_freq)

                # Retune to this frequency (skip first freq on first iteration)
                if not first_freq:
                    try:
                        self._retune_to_frequency(center_freq)
                    except Exception as e:
                        print(f"[ENGINE] Retune error: {e}")
                        # Continue (real HackRF data only, no fallback)
                else:
                    first_freq = False
                    # On first iteration, just update config
                    self.config.center_freq = center_freq

                # Dwell at this frequency
                dwell_start = time.time()
                step_emitter_ids: set[str] = set()
                while time.time() - dwell_start < config.dwell_time:
                    if self._stop_requested:
                        break
                    
                    if self._paused:
                        # Extend dwell time or just wait? 
                        # For now, just wait and let dwell time expire (or pause timer?)
                        # Better to pause timer so we don't skip scanning this freq.
                        pause_start = time.time()
                        while self._paused and not self._stop_requested:
                            time.sleep(0.1)
                        # Adjust dwell start to account for pause duration
                        dwell_start += (time.time() - pause_start)
                        continue

                    try:
                        iq = self._get_next_iq_chunk()
                        if iq is None:
                            time.sleep(0.05)
                            continue

                        # Process through pipeline
                        det = self.detector.process(iq)
                        segments_bb = self.segmenter.process(iq) if det.present else []
                        segments = self._shift_segments_to_absolute(segments_bb)
                        
                        eb_result = self.event_builder.process(
                            timestamp=time.time(),
                            detected=det.present,
                            segments=segments
                        )

                        # Closed events -> emitter tracking (keep tracker across scan steps)
                        try:
                            for ev in (eb_result.get("closed") or []):
                                emitter = self.emitter_tracker.process_closed_event(ev)
                                if emitter is not None:
                                    step_emitter_ids.add(getattr(emitter, "id", ""))
                        except Exception:
                            pass

                        # Publish PSD snapshot (for live display during scan, throttled)
                        if hasattr(self.segmenter, 'last_psd') and self.segmenter.last_psd:
                            try:
                                now = time.time()
                                if (now - self._last_psd_publish_ts) < self._ui_psd_min_interval_s:
                                    time.sleep(0.01)
                                    continue
                                self._last_psd_publish_ts = now

                                freqs, psd = self.segmenter.last_psd
                                freqs = np.asarray(freqs, dtype=np.float64) + float(self.config.center_freq)
                                snapshot = {
                                    "freqs": freqs,
                                    "psd": psd,
                                    "detected": det.present,
                                    "segments": [
                                        {
                                            "low_hz": seg["low_hz"],
                                            "high_hz": seg["high_hz"],
                                            "confidence": seg["confidence"]
                                        } for seg in segments
                                    ]
                                }
                                self.psd_publisher.publish(snapshot)
                            except Exception as e:
                                print(f"[ENGINE] PSD publish error: {e}")
                    except Exception as e:
                        print(f"[ENGINE] Processing error: {e}")

                    time.sleep(0.05)

                # End of dwell: collect closed events
                try:
                    closed_events = self.event_builder.get_closed_events()
                    result = ScanResult(
                        center_freq=center_freq,
                        dwell_time=config.dwell_time,
                        closed_events=closed_events,
                        updated_emitters=sorted([e for e in step_emitter_ids if e]),
                        timestamp=time.time()
                    )
                    self.scan_results.append(result)

                    # Notify UI so it can populate the scan results table.
                    try:
                        self.scan_result_ready.emit(result)
                    except Exception:
                        pass
                except Exception as e:
                    print(f"[ENGINE] Error collecting scan results: {e}")
                
                self.current_scan_index = idx + 1

                # Reset for next step
                self._reset_engine_state()

            # End of one complete sweep
            iteration += 1
            if self._stop_requested:
                break
            
            print(f"[ENGINE] Iteration {iteration-1} complete, restarting sweep...")

        print("[ENGINE] Scanner loop finished")
        # Transition back to IDLE (let stop() handle cleanup if needed)
        if not self._stop_requested:
            self._set_state(ControllerState.IDLE)

    def _retune_to_frequency(self, center_freq: float):
        """Retune hardware to a new frequency."""
        if not self.use_hackrf:
            return

        try:
            # Stop current flowgraph safely
            if self.flowgraph:
                try:
                    self.flowgraph.stop()
                    self.flowgraph.wait()
                except Exception as e:
                    print(f"[CONTROLLER] Error stopping flowgraph: {e}")
                    self.flowgraph = None

            # Update config
            self.config.center_freq = center_freq

            # Rebuild flowgraph at new frequency
            try:
                self.flowgraph = build_flowgraph(self.config, self.iq_stream)
                if self.flowgraph:
                    self.flowgraph.start()
                    print(f"[CONTROLLER] Retuned to {center_freq/1e6:.1f} MHz")
                else:
                    print(f"[CONTROLLER] Flowgraph creation returned None")
                    self.use_hackrf = False
            except Exception as e:
                print(f"[CONTROLLER] Flowgraph creation/start failed: {e}")
                self.flowgraph = None
                self.use_hackrf = False
        except Exception as e:
            print(f"[CONTROLLER] Retune error: {e}")
            self.use_hackrf = False

    # ========================================================================
    # START/STOP
    # ========================================================================

    def stop(self):
        """
        Stop current operation (both modes).
        
        Always safe. Handles cleanup gracefully.
        - Sets stop flag
        - Waits for engine thread
        - Stops hardware
        - Transitions to IDLE
        """
        current_state = self.get_state()
        if current_state == ControllerState.IDLE:
            return  # Already idle

        print(f"[CONTROLLER] Stopping from {current_state.value}")
        self._set_state(ControllerState.STOPPING)

        # Signal engine thread to stop
        self._stop_requested = True

        # Wait for engine thread
        if self._engine_thread:
            self._engine_thread.join(timeout=5.0)
            self._engine_thread = None

        # Stop hardware
        self._stop_hardware()

        # Let event builder drain and close events naturally
        time.sleep(0.2)

        # Transition to IDLE
        self._set_state(ControllerState.IDLE)
        print("[CONTROLLER] Stopped")

    def _stop_hardware(self):
        """Stop HackRF flowgraph."""
        if self.flowgraph:
            try:
                self.flowgraph.stop()
                self.flowgraph.wait()
                self.flowgraph = None
                print("[CONTROLLER] HackRF flowgraph stopped")
            except Exception as e:
                print(f"[CONTROLLER] Error stopping flowgraph: {e}")

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _get_next_iq_chunk(self) -> Optional[np.ndarray]:
        """
        Get next IQ chunk from stream.
        
        Returns:
            IQ data as numpy array, or None if no data available.
            
        IMPORTANT: NO SIMULATIONS - Only real data from HackRF or Replay.
        If neither source is available or producing data, returns None.
        """
        try:
            # Try to get data from IQ stream (HackRF or Replay source)
            iq = self.iq_stream.pop(timeout=0.1)
            
            if iq is None:
                # No data available right now
                return None

            return iq
            
        except Exception as e:
            print(f"[ENGINE] Error getting IQ chunk: {e}")
            return None

    def _shift_segments_to_absolute(self, segments: list[dict]) -> list[dict]:
        """Convert baseband segments to absolute Hz using current tuned center."""
        cf = float(self.config.center_freq)
        shifted = []
        for seg in segments:
            try:
                s = dict(seg)
                if "center_hz" in s:
                    s["center_hz"] = float(s["center_hz"]) + cf
                if "low_hz" in s:
                    s["low_hz"] = float(s["low_hz"]) + cf
                if "high_hz" in s:
                    s["high_hz"] = float(s["high_hz"]) + cf
                shifted.append(s)
            except Exception:
                shifted.append(seg)
        return shifted

    def _reset_engine_state(self):
        """Reset detector, segmenter, and event builder state."""
        self.detector = Detector(self.config)
        self.segmenter = Segmenter(self.config)
        self.event_builder = EventBuilder(self.config, event_publisher=self.event_publisher)
        self.iq_stream.clear()
        # SIMULATIONS DISABLED - Only real data from HackRF or Replay
        print("[CONTROLLER] Engine state reset")

    # ========================================================================
    # STATUS / DIAGNOSTICS
    # ========================================================================

    def get_scan_results(self) -> List[ScanResult]:
        """Get results from last scan (scanner mode only)."""
        return self.scan_results

    def get_current_scan_progress(self) -> tuple:
        """Return (current_index, total_steps) for scanner mode."""
        if not self.current_scan_plan:
            return (0, 0)
        return (self.current_scan_index, len(self.current_scan_plan))

    def set_on_state_changed(self, callback: Callable[[ControllerState], None]):
        """Register callback for state changes."""
        self.on_state_changed = callback

    def set_on_scan_progress(self, callback: Callable[[int, int, float], None]):
        """
        Register callback for scan progress updates.
        
        Callback signature: callback(current_step, total_steps, current_freq_hz)
        """
        self.on_scan_progress = callback
