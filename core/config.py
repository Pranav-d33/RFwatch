# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

"""
Single source of truth for RFwatch configuration.

All configuration parameters are centralized here.
UI edits this. Detector reads this. No globals.
"""


class RFConfig:
    """Configuration schema for RF signal detection."""

    def __init__(self):
        """Initialize with sensible defaults."""
        # SDR acquisition
        self.sample_rate = 2e6  # Hz
        self.center_freq = 1e9  # Hz
        self.gain = 40  # dB

        # FFT and frequency analysis
        self.fft_size = 4096
        self.overlap = 0.75  # 75% overlap

        # Chunk processing
        self.chunk_size = 16384  # samples per chunk

        # Detection thresholds (binary presence detection)
        self.snr_enter_db = 14.0  # dB: transition IDLE → ACTIVE (signal must be 14 dB above noise)
        self.snr_exit_db = 10.0  # dB: transition ACTIVE → IDLE (4 dB hysteresis)
        # Hysteresis = enter - exit = 4 dB (reduces flicker)

        # Detector holdover: if the detector briefly flickers to "absent" but
        # segmentation still finds plausible energy, keep events alive for a
        # short time window. This reduces repeated close/re-open churn without
        # creating events in empty bands.
        self.detector_hold_s = 0.25

        # Segmentation thresholds (frequency analysis)
        self.bw_threshold_db = 14.0  # dB above noise floor for bandwidth detection
        self.min_bw_bins = 1  # Minimum bins for valid segment (allows narrow CW tones)
        # Hz minimum bandwidth for valid segments (converted to bins internally).
        # This is the primary control to suppress 1-bin noise spikes when using
        # high sample rates with limited FFT size.
        self.bw_threshold = 10e3  # legacy, not used for min-bins gating

        # General minimum contiguous bins for a valid segment.
        # Using >=5 bins suppresses most noise-only spikes while still allowing
        # narrowband tones (window leakage typically spans multiple bins).
        self.min_segment_bins = 5

        # Light PSD smoothing (moving average over bins) before thresholding.
        # Reduces false segments due to single-bin stochastic peaks.
        self.psd_smooth_bins = 5

        # Segment validation: require the segment peak to exceed the threshold by
        # an additional margin. This is a simple, explainable way to reject
        # borderline noise spikes.
        self.segment_peak_prominence_db = 6.0
        self.segment_peak_prominence_narrow_db = 10.0
        self.narrow_segment_max_bins = 6

        # Event management
        self.event_timeout = 1.0  # seconds before closing event
        self.min_event_duration = 0.5  # seconds
        
        # Event builder (tracking and matching)
        self.match_bw_factor = 1.0  # Matching tolerance: |center_new - center_old| < factor * bw_old
        self.max_misses = 3  # Close event after N consecutive misses

        # ==================================================================
        # Emitter tracking (identity inference over closed events)
        # ==================================================================
        # Gating
        self.emitter_f_gate_hz = 250e3
        self.emitter_bw_gate_hz = 1.5e6
        self.emitter_p_gate_db = 25.0
        self.emitter_timeout_s = 4.0

        # Wideband robustness:
        # For wideband emitters (Wi-Fi/LTE), center-frequency estimates can
        # move around inside the occupied bandwidth. These factors expand
        # the frequency/bandwidth gates proportionally to the observed BW.
        self.emitter_f_gate_bw_factor = 0.25   # additional f-gate = factor * max(bw)
        self.emitter_bw_gate_bw_factor = 0.50  # additional bw-gate = factor * max(bw)
        # Allow association based on overlap of occupied bands even if centers drift.
        self.emitter_min_overlap_fraction = 0.20

        # Distance weights (dimensionless, on normalized deltas)
        self.emitter_wf = 2.0
        self.emitter_wb = 1.0
        self.emitter_wp = 1.0
        self.emitter_wt = 1.5
        self.emitter_wo = 1.0  # overlap penalty weight (0 disables)

        # Accept if distance < threshold
        self.emitter_distance_threshold = 5.0

        # Lifecycle
        self.emitter_death_timeout_s = 8.0

    def to_dict(self):
        """Export config as dictionary."""
        return self.__dict__.copy()

    def update_from_dict(self, params):
        """Update config from dictionary."""
        for key, value in params.items():
            if hasattr(self, key):
                setattr(self, key, value)
