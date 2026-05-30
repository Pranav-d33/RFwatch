# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

"""
Defines Signal Event object.

The SignalEvent is the currency of the RFwatch system.
It represents a detected RF signal with all associated metadata.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
from datetime import datetime


@dataclass
class FreqSegment:
    """Represents a frequency segment of a signal."""

    center_freq: float  # Hz
    bandwidth: float  # Hz
    start_time: float  # seconds
    end_time: float  # seconds
    power: float  # dB


@dataclass
class SignalEvent:
    """
    Represents a detected RF signal event.

    This is the primary object flowing through the system.
    """

    id: str
    start_time: float  # absolute timestamp
    end_time: float = None  # None until event closes
    freq_segments: List[FreqSegment] = field(default_factory=list)
    iq_refs: List[Any] = field(default_factory=list)  # references to IQ buffers
    features: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0  # 0.0 to 1.0
    active: bool = True
    
    # Event tracking history (for event builder)
    center_freq_history: List[float] = field(default_factory=list)
    bandwidth_history: List[float] = field(default_factory=list)
    power_history: List[float] = field(default_factory=list)
    timestamp_history: List[float] = field(default_factory=list)
    present_history: List[bool] = field(default_factory=list)
    hit_count: int = 0
    miss_count: int = 0
    
    # Last observed values (for matching)
    last_center: float = 0.0
    last_bandwidth: float = 0.0
    last_seen: float = 0.0  # timestamp

    def close(self, end_time: float):
        """Mark event as closed."""
        self.end_time = end_time
        self.active = False

    def duration(self) -> float:
        """Return event duration in seconds."""
        if self.end_time is None:
            return None
        return self.end_time - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "id": self.id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "active": self.active,
            "last_center_hz": self.last_center,
            "last_bandwidth_hz": self.last_bandwidth,
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "center_freq_history_hz": list(self.center_freq_history),
            "bandwidth_history_hz": list(self.bandwidth_history),
            "power_history_db": list(self.power_history),
            "timestamp_history": list(self.timestamp_history),
            "present_history": list(self.present_history),
            "features": self.features,
        }
