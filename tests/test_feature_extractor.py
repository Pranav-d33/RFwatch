"""
FeatureExtractor tests for STEP 10
"""
import pytest
import numpy as np
from core.feature_extractor import FeatureExtractor
from types import SimpleNamespace

class DummyEvent:
    def __init__(self, start_time, end_time, center_freq_history, bandwidth_history, power_history, hit_count, miss_count, is_closed=True):
        self.start_time = start_time
        self.end_time = end_time
        self.center_freq_history = center_freq_history
        self.bandwidth_history = bandwidth_history
        self.power_history = power_history
        self.hit_count = hit_count
        self.miss_count = miss_count
        self.is_closed = is_closed

# 1. Constant tone
@pytest.mark.parametrize("center_freq", [100e3])
def test_constant_tone(center_freq):
    event = DummyEvent(
        start_time=0.0,
        end_time=1.0,
        center_freq_history=[center_freq]*10,
        bandwidth_history=[10e3]*10,
        power_history=[20.0]*10,
        hit_count=10,
        miss_count=0
    )
    features = FeatureExtractor().extract(event)
    assert features["frequency"]["drift_hz_per_s"] == pytest.approx(0.0)
    assert features["confidence"]["frequency"] > 0.9
    assert features["time_structure"]["burst_type"] == "continuous"
    assert features["time_structure"]["duty_cycle"] == 1.0

# 2. Drifting tone
@pytest.mark.parametrize("drift", [100])
def test_drifting_tone(drift):
    center_freqs = np.linspace(100e3, 100e3+drift, 10)
    event = DummyEvent(
        start_time=0.0,
        end_time=1.0,
        center_freq_history=center_freqs.tolist(),
        bandwidth_history=[10e3]*10,
        power_history=[20.0]*10,
        hit_count=10,
        miss_count=0
    )
    features = FeatureExtractor().extract(event)
    assert features["frequency"]["drift_hz_per_s"] > 0.0
    assert features["confidence"]["frequency"] > 0.9

# 3. Burst signal
@pytest.mark.parametrize("miss_count", [5])
def test_burst_signal(miss_count):
    event = DummyEvent(
        start_time=0.0,
        end_time=1.0,
        center_freq_history=[100e3]*10,
        bandwidth_history=[10e3]*10,
        power_history=[20.0]*10,
        hit_count=10,
        miss_count=miss_count
    )
    features = FeatureExtractor().extract(event)
    assert features["time_structure"]["burst_type"] == "bursty"
    assert features["time_structure"]["duty_cycle"] < 1.0

# 4. Pure noise event
@pytest.mark.parametrize("power_level", [0.0])
def test_pure_noise_event(power_level):
    event = DummyEvent(
        start_time=0.0,
        end_time=1.0,
        center_freq_history=[100e3]*10,
        bandwidth_history=[10e3]*10,
        power_history=[power_level]*10,
        hit_count=10,
        miss_count=0
    )
    features = FeatureExtractor().extract(event)
    assert features["confidence"]["frequency"] < 0.2
    assert "timing" not in features or features.get("timing") is None
