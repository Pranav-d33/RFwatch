# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

"""
Reusable DSP functions.

Functions:
- FFT and PSD computation
- Autocorrelation
- Envelope extraction
- Bandwidth detection
- Modulation estimation
"""

import numpy as np
from typing import Tuple, Optional


def compute_psd(
    iq_chunk: np.ndarray, sample_rate: float, fft_size: int = 4096
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute Power Spectral Density.

    Args:
        iq_chunk: Complex IQ samples
        sample_rate: Sample rate in Hz
        fft_size: FFT size

    Returns:
        Tuple of (frequencies, psd_db)
    """
    # Zero-pad if necessary
    if len(iq_chunk) < fft_size:
        iq_chunk = np.pad(iq_chunk, (0, fft_size - len(iq_chunk)))

    # Apply Hann window and compute FFT
    window = np.hanning(len(iq_chunk))
    windowed = iq_chunk * window
    fft_result = np.fft.fft(windowed, n=fft_size)

    # Compute power and convert to dB
    power = np.abs(fft_result) ** 2 / (sample_rate * np.sum(window ** 2))
    psd_db = 10 * np.log10(power + 1e-12)

    # Frequency vector
    freqs = np.fft.fftfreq(fft_size, 1 / sample_rate)

    return freqs, psd_db


def find_signal_bandwidth(
    freqs: np.ndarray,
    psd_db: np.ndarray,
    bw_threshold: float,
    sample_rate: float,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Find signal center frequency and bandwidth.

    Args:
        freqs: Frequency vector
        psd_db: PSD in dB
        bw_threshold: Minimum bandwidth in Hz
        sample_rate: Sample rate in Hz

    Returns:
        Tuple of (center_freq, bandwidth, power) or (None, None, None)
    """
    # Shift to positive frequencies
    positive_mask = freqs >= 0
    freqs_pos = freqs[positive_mask]
    psd_pos = psd_db[positive_mask]

    # Find peak
    peak_idx = np.argmax(psd_pos)
    peak_freq = freqs_pos[peak_idx]
    peak_power = psd_pos[peak_idx]

    # Find -3dB bandwidth
    threshold = peak_power - 3
    above_threshold = psd_pos > threshold

    if not np.any(above_threshold):
        return None, None, None

    # Find edges
    indices = np.where(above_threshold)[0]
    if len(indices) == 0:
        return None, None, None

    start_idx = indices[0]
    end_idx = indices[-1]

    start_freq = freqs_pos[start_idx]
    end_freq = freqs_pos[end_idx]
    bandwidth = end_freq - start_freq

    if bandwidth < bw_threshold:
        return None, None, None

    center_freq = (start_freq + end_freq) / 2
    return center_freq, bandwidth, peak_power


def autocorrelation(signal: np.ndarray, max_lag: int = 100) -> np.ndarray:
    """
    Compute autocorrelation.

    Args:
        signal: Input signal
        max_lag: Maximum lag to compute

    Returns:
        Autocorrelation values
    """
    signal = signal - np.mean(signal)
    c = np.correlate(signal, signal, mode="full")
    c = c / c[len(c) // 2]
    return c[len(c) // 2 : len(c) // 2 + max_lag]


def envelope_extraction(iq_signal: np.ndarray) -> np.ndarray:
    """
    Extract envelope (magnitude) of IQ signal.

    Args:
        iq_signal: Complex IQ samples

    Returns:
        Envelope magnitude
    """
    return np.abs(iq_signal)


def estimate_modulation_type(iq_refs: list) -> str:
    """
    Estimate modulation type (stub).

    Args:
        iq_refs: References to IQ buffers

    Returns:
        Modulation type string
    """
    # Placeholder: actual implementation would analyze IQ constellation
    return "unknown"
