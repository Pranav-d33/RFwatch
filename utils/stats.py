"""
Statistical utilities.

Functions:
- Variance
- Kurtosis
- Percentiles
- Signal statistics
"""

import numpy as np
from typing import Dict, Any


def compute_stats(signal: np.ndarray) -> Dict[str, Any]:
    """
    Compute comprehensive statistics on signal.

    Args:
        signal: Input signal (real or complex)

    Returns:
        Dictionary of statistics
    """
    if np.iscomplexobj(signal):
        mag = np.abs(signal)
    else:
        mag = signal

    stats = {
        "mean": np.mean(mag),
        "std": np.std(mag),
        "var": np.var(mag),
        "min": np.min(mag),
        "max": np.max(mag),
        "median": np.median(mag),
        "kurtosis": kurtosis(mag),
        "crest_factor": np.max(mag) / (np.mean(mag) + 1e-12),
    }

    return stats


def kurtosis(signal: np.ndarray) -> float:
    """
    Compute kurtosis of signal.

    Args:
        signal: Input signal

    Returns:
        Kurtosis value
    """
    signal = signal - np.mean(signal)
    m4 = np.mean(signal ** 4)
    m2 = np.mean(signal ** 2)
    return (m4 / (m2 ** 2 + 1e-12)) - 3  # Excess kurtosis


def percentile(signal: np.ndarray, p: float) -> float:
    """
    Compute percentile.

    Args:
        signal: Input signal
        p: Percentile (0-100)

    Returns:
        Percentile value
    """
    return np.percentile(signal, p)
