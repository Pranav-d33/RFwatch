"""
Binary signal detection using power estimation and hysteresis.

Responsibilities:
- Power estimation (time domain)
- Noise floor estimation (median-based)
- SNR calculation
- Signal presence decision (with hysteresis)

NOT responsible for:
- Frequency analysis (FFT)
- Bandwidth detection
- Feature extraction
- UI
- GNU Radio

This is a gate. Nothing more.
"""

import os
import numpy as np
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class DetectionResult:
    """Result of signal detection for one chunk."""

    present: bool  # Is signal present (after hysteresis)?
    power_db: float  # Instantaneous power
    noise_floor_db: float  # Estimated noise floor
    snr_db: float  # Signal-to-noise ratio


class Detector:
    """Binary signal detection using power estimation."""

    def __init__(self, config):
        """
        Initialize detector.

        Args:
            config: RFConfig instance
        """
        self.config = config

        # Noise floor estimation (median of recent power values)
        self.noise_history = deque(maxlen=500)  # Last 500 samples (increased from 100)

        # State machine for hysteresis
        self.state = "IDLE"  # "IDLE" or "ACTIVE"

        # For diagnostics
        self.chunk_count = 0
        self.transitions = []

    def process(self, iq_chunk: np.ndarray) -> DetectionResult:
        """
        Detect signal presence in IQ chunk.

        Uses hysteresis to eliminate flicker:
        - IDLE → ACTIVE: SNR > snr_enter_db
        - ACTIVE → IDLE: SNR < snr_exit_db

        Args:
            iq_chunk: Complex IQ samples (np.ndarray)

        Returns:
            DetectionResult with presence, power, noise floor, SNR
        """
        self.chunk_count += 1

        # ============================================================
        # Step 1: Power estimation (time domain)
        # ============================================================
        power_linear = np.mean(np.abs(iq_chunk) ** 2)
        power_db = 10 * np.log10(power_linear + 1e-20)

        # ============================================================
        # Step 2: Noise floor estimation (robust median)
        # ============================================================
        self.noise_history.append(power_db)

        # Use median: noise is dominant most of the time
        # Median rejects transient signal bursts
        if len(self.noise_history) > 0:
            noise_floor_db = np.median(list(self.noise_history))
        else:
            noise_floor_db = power_db

        # ============================================================
        # Step 3: SNR calculation
        # ============================================================
        snr_db = power_db - noise_floor_db

        # ============================================================
        # Step 4: Presence decision with hysteresis
        # ============================================================
        present = False
        old_state = self.state
        
        # Debug: Sample every 100 chunks
        if self.chunk_count % 100 == 0 and os.getenv("RF_INSPECTOR_DEBUG_DETECTOR", "").lower() in {"1", "true"}:
            print(f"[DETECTOR] chunk={self.chunk_count}: power={power_db:.1f}dB, noise={noise_floor_db:.1f}dB, snr={snr_db:.1f}dB, threshold={self.config.snr_enter_db}dB")

        if self.state == "IDLE":
            # Transition to ACTIVE if SNR exceeds enter threshold
            if snr_db > self.config.snr_enter_db:
                self.state = "ACTIVE"
                present = True
                self.transitions.append(
                    {
                        "chunk": self.chunk_count,
                        "transition": "IDLE → ACTIVE",
                        "snr_db": snr_db,
                    }
                )
        else:  # ACTIVE
            # Stay active if above exit threshold
            if snr_db < self.config.snr_exit_db:
                self.state = "IDLE"
                present = False
                self.transitions.append(
                    {
                        "chunk": self.chunk_count,
                        "transition": "ACTIVE → IDLE",
                        "snr_db": snr_db,
                    }
                )
            else:
                present = True

        return DetectionResult(
            present=present,
            power_db=power_db,
            noise_floor_db=noise_floor_db,
            snr_db=snr_db,
        )

    def get_state(self) -> str:
        """Get current state (IDLE or ACTIVE)."""
        return self.state

    def reset(self) -> None:
        """Reset detector to initial state."""
        self.noise_history.clear()
        self.state = "IDLE"
        self.chunk_count = 0
        self.transitions.clear()

    def get_statistics(self) -> dict:
        """Get detector diagnostics."""
        return {
            "state": self.state,
            "chunk_count": self.chunk_count,
            "noise_history_size": len(self.noise_history),
            "transitions": len(self.transitions),
            "recent_transitions": self.transitions[-5:],  # Last 5
        }

