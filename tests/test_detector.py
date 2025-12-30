"""
MANDATORY sanity tests for detector.

Tests:
1. Pure noise input → present stays false, noise floor stabilizes
2. Injected CW tone → present latches true, no flicker
3. Burst signal → present toggles correctly, hysteresis works
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import numpy as np
from core.config import RFConfig
from core.detector import Detector, DetectionResult


class TestDetectorBasics(unittest.TestCase):
    """Basic detector functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.detector = Detector(self.config)

    def test_initialization(self):
        """Test detector initializes correctly."""
        self.assertEqual(self.detector.state, "IDLE")
        self.assertEqual(len(self.detector.noise_history), 0)

    def test_returns_detection_result(self):
        """Test detector returns DetectionResult object."""
        noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
        result = self.detector.process(noise.astype(np.complex64))
        
        self.assertIsInstance(result, DetectionResult)
        self.assertTrue(hasattr(result, 'present'))
        self.assertTrue(hasattr(result, 'power_db'))
        self.assertTrue(hasattr(result, 'noise_floor_db'))
        self.assertTrue(hasattr(result, 'snr_db'))


class TestPureNoise(unittest.TestCase):
    """Test 1: Pure noise input."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.detector = Detector(self.config)

    def test_noise_stays_idle(self):
        """Pure noise should keep detector in IDLE state."""
        # Generate low-power noise for 100 chunks
        for _ in range(100):
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            result = self.detector.process(noise.astype(np.complex64))
            
            # Should never detect signal
            self.assertFalse(result.present)
            self.assertEqual(self.detector.state, "IDLE")

    def test_noise_floor_stabilizes(self):
        """Noise floor should stabilize after initial samples."""
        noise_floors = []
        
        for i in range(100):
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            result = self.detector.process(noise.astype(np.complex64))
            noise_floors.append(result.noise_floor_db)
        
        # After 50 chunks, noise floor should be stable (low variance)
        recent_floors = noise_floors[50:]
        variance = np.var(recent_floors)
        
        self.assertLess(variance, 1.0, "Noise floor should stabilize (variance < 1 dB)")

    def test_snr_near_zero(self):
        """SNR should be near zero for pure noise."""
        snr_values = []
        
        for _ in range(50):
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            result = self.detector.process(noise.astype(np.complex64))
            snr_values.append(result.snr_db)
        
        # Median SNR should be close to 0 (noise floor tracks noise)
        median_snr = np.median(snr_values)
        self.assertLess(abs(median_snr), 2.0, f"SNR should be ~0 dB for noise, got {median_snr:.2f}")


class TestCWTone(unittest.TestCase):
    """Test 2: Injected CW tone."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.detector = Detector(self.config)

    def test_cw_tone_triggers_detection(self):
        """Strong CW tone should trigger ACTIVE state initially."""
        # Feed noise first to establish floor
        for _ in range(50):
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            self.detector.process(noise.astype(np.complex64))
        
        self.assertEqual(self.detector.state, "IDLE")
        
        # Feed strong tone - should transition to ACTIVE
        t = np.arange(1024) / 2e6
        tone = 1.0 * np.exp(2j * np.pi * 1e6 * t)
        noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
        signal = tone + noise
        
        result = self.detector.process(signal.astype(np.complex64))
        
        # First tone chunk should trigger detection (SNR >> 10 dB)
        # May take a couple chunks due to median adaptation
        detected = False
        for _ in range(5):
            result = self.detector.process(signal.astype(np.complex64))
            if result.present:
                detected = True
                break
        
        self.assertTrue(detected, "Should detect strong CW tone within 5 chunks")

    def test_no_flicker_on_steady_tone(self):
        """Steady CW tone should not flicker once active."""
        # Establish noise floor
        for _ in range(20):
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            self.detector.process(noise.astype(np.complex64))
        
        # Feed steady tone and check for flicker
        states = []
        for _ in range(100):
            t = np.arange(1024) / 2e6
            tone = 0.5 * np.exp(2j * np.pi * 1e6 * t)  # Strong tone (consistent with above)
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            signal = tone + noise
            result = self.detector.process(signal.astype(np.complex64))
            states.append(self.detector.state)
        
        # Count state transitions
        transitions = sum(1 for i in range(1, len(states)) if states[i] != states[i-1])
        
        # Should have at most 1 transition (IDLE→ACTIVE), no flicker
        self.assertLessEqual(transitions, 1, f"Too many transitions ({transitions}), flicker detected!")


class TestBurstSignal(unittest.TestCase):
    """Test 3: Burst signal with hysteresis."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.detector = Detector(self.config)

    def test_burst_onset_detection(self):
        """Detector should transition IDLE→ACTIVE on burst onset."""
        # Feed noise
        for _ in range(30):
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            result = self.detector.process(noise.astype(np.complex64))
            self.assertFalse(result.present)
        
        # Feed burst
        t = np.arange(1024) / 2e6
        tone = 0.4 * np.exp(2j * np.pi * 1e6 * t)
        noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
        signal = tone + noise
        result = self.detector.process(signal.astype(np.complex64))
        
        # Should detect onset
        self.assertTrue(result.present)
        self.assertEqual(self.detector.state, "ACTIVE")

    def test_burst_offset_detection(self):
        """Detector should transition ACTIVE→IDLE on burst offset."""
        # Establish noise floor
        for _ in range(20):
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            self.detector.process(noise.astype(np.complex64))
        
        # Feed burst to go active
        for _ in range(10):
            t = np.arange(1024) / 2e6
            tone = 0.4 * np.exp(2j * np.pi * 1e6 * t)
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            signal = tone + noise
            self.detector.process(signal.astype(np.complex64))
        
        self.assertEqual(self.detector.state, "ACTIVE")
        
        # Now feed noise again (burst ends)
        for _ in range(5):
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            result = self.detector.process(noise.astype(np.complex64))
        
        # Should return to IDLE
        self.assertEqual(self.detector.state, "IDLE")
        self.assertFalse(result.present)

    def test_hysteresis_prevents_flicker(self):
        """Hysteresis should prevent rapid state transitions."""
        # Establish noise floor
        for _ in range(20):
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            self.detector.process(noise.astype(np.complex64))
        
        # Feed signal near threshold (should cause flicker without hysteresis)
        # SNR slightly above enter, then below, repeat
        states = []
        for i in range(100):
            t = np.arange(1024) / 2e6
            # Vary amplitude to be near threshold
            amp = 0.15 if i % 2 == 0 else 0.12  # Alternating power
            tone = amp * np.exp(2j * np.pi * 1e6 * t)
            noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            signal = tone + noise
            self.detector.process(signal.astype(np.complex64))
            states.append(self.detector.state)
        
        # Count transitions
        transitions = sum(1 for i in range(1, len(states)) if states[i] != states[i-1])
        
        # Hysteresis should limit transitions significantly
        # Without hysteresis: ~50 transitions
        # With hysteresis: <10 transitions
        self.assertLess(transitions, 10, f"Hysteresis failed: {transitions} transitions")


class TestDetectorReset(unittest.TestCase):
    """Test detector reset functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.detector = Detector(self.config)

    def test_reset_clears_state(self):
        """Reset should clear all detector state."""
        # Process some data
        for _ in range(50):
            noise = 0.1 * (np.random.randn(1024) + 1j * np.random.randn(1024))
            self.detector.process(noise.astype(np.complex64))
        
        # Reset
        self.detector.reset()
        
        # Verify clean state
        self.assertEqual(self.detector.state, "IDLE")
        self.assertEqual(len(self.detector.noise_history), 0)
        self.assertEqual(self.detector.chunk_count, 0)


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
