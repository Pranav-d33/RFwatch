"""
Tests for EventBuilder.

Critical tests (as specified in STEP 9):
1. Single steady tone → one event, correct duration
2. Burst signal → one event, correct on/off timing
3. Two simultaneous tones → two events, no merging
4. Drifting tone → one event, smooth center history
"""

import pytest
import numpy as np
from core.event_builder import EventBuilder
from core.config import RFConfig


class TestEventBuilder:
    """Test suite for EventBuilder event construction."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        cfg = RFConfig()
        cfg.match_bw_factor = 0.5
        cfg.max_misses = 3
        return cfg

    @pytest.fixture
    def builder(self, config):
        """Create EventBuilder instance."""
        return EventBuilder(config)

    def test_single_steady_tone(self, builder):
        """
        Test 1: Single steady tone creates one event with correct duration.
        
        Scenario:
        - Same frequency segment appears for 5 consecutive chunks
        - Should create exactly 1 event
        - Duration should match time span
        """
        # Simulate 5 chunks of steady tone at 100 kHz, 10 kHz bandwidth
        segment = {
            "center_hz": 100e3,
            "bandwidth_hz": 10e3,
            "low_hz": 95e3,
            "high_hz": 105e3,
            "confidence": 0.9,
            "peak_db": 20.0,
        }

        start_time = 0.0
        chunk_duration = 0.01  # 10 ms per chunk

        # Process 5 chunks
        for i in range(5):
            timestamp = start_time + i * chunk_duration
            result = builder.process(timestamp, detected=True, segments=[segment])

        # Verify: exactly 1 active event
        active = builder.get_active_events()
        assert len(active) == 1, "Should have exactly 1 active event"

        event = active[0]
        assert event.hit_count == 5, "Event should have 5 hits"
        assert event.miss_count == 0, "Event should have 0 misses"
        assert len(event.center_freq_history) == 5, "Should have 5 frequency observations"

        # Now close the event by missing 3 times
        for i in range(3):
            timestamp = start_time + (5 + i) * chunk_duration
            result = builder.process(timestamp, detected=False, segments=[])

        # Event should now be closed
        closed = builder.get_closed_events()
        assert len(closed) == 1, "Should have 1 closed event"
        assert len(builder.get_active_events()) == 0, "Should have 0 active events"

        event = closed[0]
        assert event.duration() is not None, "Event should have duration"
        # Duration is from start (0.0) to when event was closed (0.07)
        # Event was last seen at 0.04, then missed at 0.05, 0.06, 0.07 (closed)
        expected_duration = 7 * chunk_duration  # 0.0 to 0.07
        assert abs(event.duration() - expected_duration) < 1e-6, f"Duration mismatch: {event.duration()} vs {expected_duration}"

    def test_burst_signal(self, builder):
        """
        Test 2: Burst signal creates one event with correct on/off timing.
        
        Scenario:
        - Signal present for 3 chunks
        - Absent for 1 chunk (miss)
        - Present for 2 more chunks (should continue same event)
        - Absent for 3 chunks (should close)
        """
        segment = {
            "center_hz": 200e3,
            "bandwidth_hz": 15e3,
            "confidence": 0.85,
            "peak_db": 18.0,
        }

        chunk_duration = 0.01
        timestamp = 0.0

        # Present for 3 chunks
        for i in range(3):
            result = builder.process(timestamp, detected=True, segments=[segment])
            timestamp += chunk_duration

        assert len(builder.get_active_events()) == 1

        # Absent for 1 chunk (miss 1)
        result = builder.process(timestamp, detected=False, segments=[])
        timestamp += chunk_duration
        assert len(builder.get_active_events()) == 1  # Still active (only 1 miss)

        # Present for 2 more chunks (resets miss count)
        for i in range(2):
            result = builder.process(timestamp, detected=True, segments=[segment])
            timestamp += chunk_duration

        event = builder.get_active_events()[0]
        assert event.hit_count == 5  # 3 + 2 = 5 hits
        assert event.miss_count == 0  # Reset after re-match

        # Absent for 3 chunks → should close
        for i in range(3):
            result = builder.process(timestamp, detected=False, segments=[])
            timestamp += chunk_duration

        assert len(builder.get_active_events()) == 0
        assert len(builder.get_closed_events()) == 1

        # Verify duration includes the gap
        event = builder.get_closed_events()[0]
        assert event.duration() > 0.04  # Should span multiple chunks

    def test_two_simultaneous_tones(self, builder):
        """
        Test 3: Two simultaneous tones create two separate events.
        
        Scenario:
        - Two segments at different frequencies appear together
        - Should create 2 distinct events
        - Events should NOT merge
        """
        segment1 = {
            "center_hz": 100e3,
            "bandwidth_hz": 10e3,
            "confidence": 0.9,
            "peak_db": 20.0,
        }

        segment2 = {
            "center_hz": 300e3,  # Far apart: 200 kHz separation
            "bandwidth_hz": 10e3,
            "confidence": 0.85,
            "peak_db": 18.0,
        }

        timestamp = 0.0
        chunk_duration = 0.01

        # Process 5 chunks with both segments
        for i in range(5):
            result = builder.process(
                timestamp, detected=True, segments=[segment1, segment2]
            )
            timestamp += chunk_duration

        # Verify: exactly 2 active events
        active = builder.get_active_events()
        assert len(active) == 2, "Should have exactly 2 active events"

        # Verify they're at different frequencies
        centers = sorted([e.last_center for e in active])
        assert centers[0] == pytest.approx(100e3)
        assert centers[1] == pytest.approx(300e3)

        # Both should have 5 hits
        for event in active:
            assert event.hit_count == 5
            assert len(event.center_freq_history) == 5

    def test_drifting_tone(self, builder):
        """
        Test 4: Drifting tone creates one event with smooth center history.
        
        Scenario:
        - Frequency drifts gradually from 100 kHz to 102 kHz
        - Drift is small enough to stay within match threshold
        - Should create 1 event (not multiple)
        - Center frequency history should show smooth drift
        """
        start_freq = 100e3
        end_freq = 102e3
        num_chunks = 10
        drift_per_chunk = (end_freq - start_freq) / num_chunks

        timestamp = 0.0
        chunk_duration = 0.01

        for i in range(num_chunks):
            freq = start_freq + i * drift_per_chunk
            segment = {
                "center_hz": freq,
                "bandwidth_hz": 10e3,
                "confidence": 0.9,
                "peak_db": 20.0,
            }

            result = builder.process(timestamp, detected=True, segments=[segment])
            timestamp += chunk_duration

        # Verify: exactly 1 event (not fragmented)
        active = builder.get_active_events()
        assert len(active) == 1, "Drifting signal should create 1 event, not multiple"

        event = active[0]
        assert event.hit_count == num_chunks

        # Verify center frequency history shows smooth drift
        history = event.center_freq_history
        assert len(history) == num_chunks

        # Check monotonic increase
        for i in range(1, len(history)):
            assert history[i] >= history[i - 1], "Frequency should drift upward"

        # Check start and end frequencies
        assert history[0] == pytest.approx(start_freq, abs=1e3)
        assert history[-1] == pytest.approx(end_freq, abs=1e3)

    def test_event_closure_on_max_misses(self, builder):
        """
        Test that event closes after max_misses consecutive misses.
        """
        segment = {
            "center_hz": 150e3,
            "bandwidth_hz": 10e3,
            "confidence": 0.9,
            "peak_db": 20.0,
        }

        # Create event with 1 hit
        result = builder.process(0.0, detected=True, segments=[segment])
        assert len(builder.get_active_events()) == 1

        # Miss max_misses times (default = 3)
        for i in range(3):
            result = builder.process(0.01 * (i + 1), detected=False, segments=[])

        # Event should be closed
        assert len(builder.get_active_events()) == 0
        assert len(builder.get_closed_events()) == 1

    def test_matching_threshold(self, builder):
        """
        Test that matching threshold works correctly.
        
        Segments within match_bw_factor * bandwidth should match.
        Segments outside should create new events.
        """
        # First segment at 100 kHz, 10 kHz bandwidth
        seg1 = {
            "center_hz": 100e3,
            "bandwidth_hz": 10e3,
            "confidence": 0.9,
            "peak_db": 20.0,
        }

        builder.process(0.0, detected=True, segments=[seg1])

        # Second segment at 103 kHz (within 0.5 * 10 kHz = 5 kHz threshold)
        seg2 = {
            "center_hz": 103e3,
            "bandwidth_hz": 10e3,
            "confidence": 0.9,
            "peak_db": 20.0,
        }

        builder.process(0.01, detected=True, segments=[seg2])

        # Should still be 1 event (matched)
        assert len(builder.get_active_events()) == 1

        # Third segment at 120 kHz (far outside threshold)
        seg3 = {
            "center_hz": 120e3,
            "bandwidth_hz": 10e3,
            "confidence": 0.9,
            "peak_db": 20.0,
        }

        builder.process(0.02, detected=True, segments=[seg3])

        # Should now be 2 events (new one created)
        assert len(builder.get_active_events()) == 2

    def test_reset(self, builder):
        """Test that reset clears all state."""
        segment = {
            "center_hz": 100e3,
            "bandwidth_hz": 10e3,
            "confidence": 0.9,
            "peak_db": 20.0,
        }

        # Create some events
        builder.process(0.0, detected=True, segments=[segment])
        builder.process(0.1, detected=False, segments=[])
        builder.process(0.2, detected=False, segments=[])
        builder.process(0.3, detected=False, segments=[])

        assert len(builder.get_closed_events()) > 0 or len(builder.get_active_events()) > 0

        # Reset
        builder.reset()

        assert len(builder.get_active_events()) == 0
        assert len(builder.get_closed_events()) == 0
        assert builder._event_counter == 0
