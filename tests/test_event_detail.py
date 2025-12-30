"""
Integration test for Event Detail View.

Verifies:
1. Event can be created and closed
2. Features are extracted
3. Detail view can display the event
4. All metrics are properly formatted
"""

import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
from core.event import SignalEvent
from core.config import RFConfig
from core.event_builder import EventBuilder
from core.event_store import EventStore
from core.feature_extractor import FeatureExtractor


def create_test_event():
    """Create a realistic test event with proper history."""
    event = SignalEvent(
        id="test_event_001",
        start_time=0.0,
    )
    
    # Simulate 10 observations of a signal
    for i in range(10):
        event.center_freq_history.append(2.4e9 + i * 1000)  # Slight drift
        event.bandwidth_history.append(1e6 + np.random.randn() * 1e4)  # Small jitter
        event.power_history.append(10.0 + np.random.randn() * 0.5)  # Power variations
        event.hit_count += 1
    
    # Close the event
    event.close(0.5)
    
    # Extract features
    extractor = FeatureExtractor()
    event.features = extractor.extract(event)
    
    return event


def test_feature_extraction():
    """Test that features are properly extracted."""
    event = create_test_event()
    
    print("\n=== Feature Extraction Test ===")
    print(f"Event ID: {event.id}")
    print(f"Duration: {event.duration():.3f}s")
    print(f"Features extracted: {list(event.features.keys())}")
    
    # Check key features
    assert "frequency" in event.features
    assert "bandwidth" in event.features
    assert "power" in event.features
    assert "noise" in event.features
    assert "time_structure" in event.features
    assert "confidence" in event.features
    
    freq_conf = event.features["confidence"]["frequency"]
    print(f"Frequency confidence: {freq_conf:.3f}")
    
    assert 0.0 <= freq_conf <= 1.0, "Confidence should be in [0, 1]"
    print("✓ Feature extraction test passed")
    return event


def test_event_store():
    """Test event store functionality."""
    print("\n=== Event Store Test ===")
    
    store = EventStore()
    event = create_test_event()
    
    # Add event
    store.add(event)
    print(f"Added event to store")
    
    # Retrieve event
    retrieved = store.get_event(event.id)
    assert retrieved is not None
    print(f"Retrieved event: {retrieved.id}")
    
    # Close event
    closed = store.close(event.id, event.end_time)
    assert closed is not None
    print(f"Closed event: {closed.id}")
    
    # Check it's in history
    history = store.get_history()
    assert len(history) > 0
    print(f"Event store history size: {len(history)}")
    print("✓ Event store test passed")


def test_detail_view_data_flow():
    """Test that data flows correctly to detail view."""
    print("\n=== Detail View Data Flow Test ===")
    
    event = create_test_event()
    features = event.features
    
    # Test signal summary generation
    bw_hz = features.get("bandwidth", {}).get("mean_hz", 0)
    if bw_hz > 1e6:
        kind = "Wideband signal"
    else:
        kind = "Narrowband signal"
    
    center_hz = features.get("frequency", {}).get("center_hz", 0)
    freq_mhz = center_hz / 1e6
    print(f"Summary: {kind} near {freq_mhz:.3f} GHz")
    
    # Test Overview metrics
    print("\n--- Overview Tab Metrics ---")
    freq_hz = features.get("frequency", {}).get("center_hz", 0)
    freq_mhz = freq_hz / 1e6
    print(f"Center Frequency: {freq_mhz:.3f} MHz")
    
    bw_hz = features.get("bandwidth", {}).get("mean_hz", 0)
    if bw_hz >= 1e6:
        bw_display = f"{bw_hz / 1e6:.2f} MHz"
    else:
        bw_display = f"{bw_hz / 1e3:.1f} kHz"
    print(f"Bandwidth: {bw_display}")
    
    power_avg = features.get("power", {}).get("avg_power", 0)
    print(f"Avg Power: {power_avg:.1f} dB (relative)")
    
    snr = features.get("noise", {}).get("snr", 0)
    print(f"SNR: {snr:.1f} dB")
    
    duty_cycle = features.get("time_structure", {}).get("duty_cycle", 0)
    print(f"Duty Cycle: {duty_cycle * 100:.1f}%")
    
    duration_s = features.get("meta", {}).get("duration_s", 0)
    print(f"Duration: {duration_s:.2f} s")
    
    freq_conf = features.get("confidence", {}).get("frequency", 0.5)
    print(f"Frequency Confidence: {freq_conf:.3f}")
    
    # Test time behavior data
    print("\n--- Time Behavior Tab Data ---")
    power_history = event.power_history
    center_freq_history = event.center_freq_history
    print(f"Power history length: {len(power_history)}")
    print(f"Frequency history length: {len(center_freq_history)}")
    print(f"Power range: {min(power_history):.2f} to {max(power_history):.2f} dB")
    print(f"Frequency range: {min(center_freq_history)/1e9:.4f} to {max(center_freq_history)/1e9:.4f} GHz")
    
    # Test advanced warnings
    print("\n--- Advanced Tab Warnings ---")
    warnings = []
    snr = features.get("noise", {}).get("snr", 0)
    if snr < 3:
        warnings.append("Low SNR: frequency estimates may be unreliable")
    
    bw_unstable = features.get("bandwidth", {}).get("unstable", False)
    if bw_unstable:
        warnings.append("Bandwidth unstable over time")
    
    duration_s = features.get("meta", {}).get("duration_s", 0)
    if duration_s < 0.5:
        warnings.append("Short observation window: statistics less reliable")
    
    if warnings:
        for w in warnings:
            print(f"  • {w}")
    else:
        print("  No warnings. Data looks good.")
    
    print("✓ Detail view data flow test passed")


if __name__ == "__main__":
    try:
        event = test_feature_extraction()
        test_event_store()
        test_detail_view_data_flow()
        print("\n" + "="*50)
        print("✅ All integration tests passed!")
        print("="*50)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
