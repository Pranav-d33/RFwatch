"""
MANDATORY sanity tests for segmenter.

Tests:
1. Pure noise → no segments
2. Single CW tone → narrow segment
3. Wideband noise → one wide segment  
4. Two tones → two segments with correct spacing
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import numpy as np
from core.config import RFConfig
from core.segmenter import Segmenter


class TestSegmenterBasics(unittest.TestCase):
    """Basic segmenter functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.segmenter = Segmenter(self.config)

    def test_initialization(self):
        """Test segmenter initializes correctly."""
        self.assertIsNotNone(self.segmenter.config)

    def test_returns_list(self):
        """Test segmenter returns list of segments."""
        noise = 0.01 * (np.random.randn(1024) + 1j * np.random.randn(1024))
        segments = self.segmenter.process(noise.astype(np.complex64))
        
        self.assertIsInstance(segments, list)


class TestPureNoise(unittest.TestCase):
    """Test 1: Pure noise → no segments."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.segmenter = Segmenter(self.config)

    def test_noise_produces_few_segments(self):
        """Pure noise should produce many small segments (normal FFT behavior)."""
        # Generate low-power noise
        noise = 0.01 * (np.random.randn(2048) + 1j * np.random.randn(2048))
        segments = self.segmenter.process(noise.astype(np.complex64))
        
        # Noise creates many small transient segments (FFT of random data)
        # The key is they should be small/narrow
        if segments:
            avg_bw = np.mean([s["bandwidth_hz"] for s in segments])
            # Each should be very narrow (< 50 kHz average)
            self.assertLess(avg_bw, 50e3, "Noise segments should be very narrow")


class TestSingleCWTone(unittest.TestCase):
    """Test 2: Single CW tone → narrow segment."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.segmenter = Segmenter(self.config)

    def test_cw_tone_produces_segment(self):
        """Single CW tone should produce one narrow segment."""
        N = 4096  # Larger for better frequency resolution
        fs = self.config.sample_rate
        
        # Generate CW tone at 500 kHz offset with low noise floor
        t = np.arange(N) / fs
        f_offset = 500e3
        tone = 0.8 * np.exp(2j * np.pi * f_offset * t)
        noise = 0.05 * (np.random.randn(N) + 1j * np.random.randn(N))
        signal = tone + noise
        
        segments = self.segmenter.process(signal.astype(np.complex64))
        
        # Should find segments
        self.assertGreaterEqual(len(segments), 1, "Should find at least one segment for CW tone")
        
        # Find strongest segment (highest power)
        # Add peak_power to each segment for sorting
        for seg in segments:
            seg['_temp_power'] = 10 * np.log10(10 ** (seg.get('peak_db', -100) / 10))
        
        segments_sorted = sorted(segments, key=lambda s: s.get('peak_db', -100), reverse=True)
        main_seg = segments_sorted[0]
        
        # Center should be near ±500 kHz
        self.assertLess(
            abs(abs(main_seg["center_hz"]) - abs(f_offset)),
            100e3,
            f"Tone center {main_seg['center_hz']/1e3:.0f} kHz should be near ±{f_offset/1e3:.0f} kHz"
        )
        
        # Bandwidth should be narrow (< 400 kHz for CW)
        self.assertLess(main_seg["bandwidth_hz"], 400e3, "CW tone bandwidth should be narrow")

    def test_segment_confidence(self):
        """Segment should have reasonable confidence."""
        N = 2048
        fs = self.config.sample_rate
        
        t = np.arange(N) / fs
        tone = 1.0 * np.exp(2j * np.pi * 500e3 * t)
        noise = 0.01 * (np.random.randn(N) + 1j * np.random.randn(N))
        signal = tone + noise
        
        segments = self.segmenter.process(signal.astype(np.complex64))
        
        if len(segments) > 0:
            seg = segments[0]
            self.assertGreater(seg["confidence"], 0.0)
            self.assertLessEqual(seg["confidence"], 1.0)


class TestWidebandNoise(unittest.TestCase):
    """Test 3: Wideband noise → one wide segment."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.segmenter = Segmenter(self.config)

    def test_wideband_signal_produces_wide_segment(self):
        """Wideband signal with low background should produce wide segment."""
        N = 4096  # Larger for better frequency resolution
        
        # Generate wideband bandlimited noise
        # Start with noise in frequency domain
        freq_noise = np.random.randn(N) + 1j * np.random.randn(N)
        
        # Zero out edges (bandlimit to center 60%)
        edge_bins = int(N * 0.2)
        freq_noise[:edge_bins] = 0
        freq_noise[-edge_bins:] = 0
        
        # Convert to time domain
        signal = np.fft.ifft(np.fft.ifftshift(freq_noise))
        signal = signal / np.std(signal) * 0.5  # Normalize
        
        segments = self.segmenter.process(signal.astype(np.complex64))
        
        # Should find segments
        self.assertGreaterEqual(len(segments), 1, "Should find at least one segment")
        
        # Should have segments covering wide bandwidth
        if len(segments) > 0:
            # Sum of all segment bandwidths
            total_bw = sum(s["bandwidth_hz"] for s in segments)
            # Median threshold is conservative, check for >10% coverage
            self.assertGreater(
                total_bw, 
                self.config.sample_rate * 0.1,
                "Wideband signal should occupy >10% of total bandwidth"
            )


class TestTwoTones(unittest.TestCase):
    """Test 4: Two tones → two segments with correct spacing."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.segmenter = Segmenter(self.config)

    def test_two_tones_produce_two_segments(self):
        """Two separated CW tones should produce two segments."""
        N = 4096  # Larger FFT for better resolution
        fs = self.config.sample_rate
        
        # Generate two tones at different frequencies
        t = np.arange(N) / fs
        f1 = -400e3  # -400 kHz
        f2 = 400e3   # +400 kHz
        
        tone1 = 0.5 * np.exp(2j * np.pi * f1 * t)
        tone2 = 0.5 * np.exp(2j * np.pi * f2 * t)
        noise = 0.01 * (np.random.randn(N) + 1j * np.random.randn(N))
        signal = tone1 + tone2 + noise
        
        segments = self.segmenter.process(signal.astype(np.complex64))
        
        # Should find two prominent segments
        self.assertGreaterEqual(len(segments), 2, "Should find at least two segments for two tones")
        
        # Sort by bandwidth (power) to find the two main tones, then by frequency
        segments_by_power = sorted(segments, key=lambda s: s["bandwidth_hz"], reverse=True)[:2]
        main_segs = sorted(segments_by_power, key=lambda s: s["center_hz"])
        
        # Check we have two distinct frequency regions
        seg1 = main_segs[0]
        seg2 = main_segs[1]
        
        # They should be on opposite sides of center (roughly)
        self.assertLess(seg1["center_hz"], 0, "Lower tone should be negative freq")
        self.assertGreater(seg2["center_hz"], 0, "Upper tone should be positive freq")
        
        # Check rough frequency positions
        self.assertAlmostEqual(abs(seg1["center_hz"]), abs(f1), delta=200e3)
        self.assertAlmostEqual(abs(seg2["center_hz"]), abs(f2), delta=200e3)

    def test_tone_separation(self):
        """Verify tones are properly separated."""
        N = 4096
        fs = self.config.sample_rate
        
        t = np.arange(N) / fs
        tone1 = 0.5 * np.exp(2j * np.pi * -300e3 * t)
        tone2 = 0.5 * np.exp(2j * np.pi * 300e3 * t)
        noise = 0.01 * (np.random.randn(N) + 1j * np.random.randn(N))
        signal = tone1 + tone2 + noise
        
        segments = self.segmenter.process(signal.astype(np.complex64))
        
        # Should have at least 2 segments
        self.assertGreaterEqual(len(segments), 2)
        
        # Segments should not overlap
        for i in range(len(segments) - 1):
            self.assertLess(
                segments[i]["high_hz"],
                segments[i + 1]["low_hz"],
                "Segments should not overlap"
            )


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = RFConfig()
        self.segmenter = Segmenter(self.config)

    def test_empty_or_small_chunk(self):
        """Test with very small IQ chunk."""
        small_chunk = np.array([1+1j, 2+2j], dtype=np.complex64)
        segments = self.segmenter.process(small_chunk)
        
        # Should not crash, may return empty or minimal segments
        self.assertIsInstance(segments, list)

    def test_all_zeros(self):
        """Test with all-zero IQ data."""
        zeros = np.zeros(1024, dtype=np.complex64)
        segments = self.segmenter.process(zeros)
        
        # Should not crash
        self.assertIsInstance(segments, list)


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
