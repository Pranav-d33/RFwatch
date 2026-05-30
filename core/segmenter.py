# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

"""
Frequency and time segmentation.

Given:
- IQ chunk
- present=True from detector

Determine:
- Occupied bandwidth
- Frequency edges
- Center frequency
- Multiple channels (if obvious)

Pipeline:
1. Window IQ
2. FFT
3. PSD (dB)
4. Noise floor (median)
5. Threshold
6. Contiguous bin grouping
7. Frequency segments
"""

import numpy as np
from typing import List, Dict, Any


class Segmenter:
    """
    Performs frequency segmentation of signals.
    
    Runs only when detector says present=True.
    Stateless across chunks.
    Emits frequency segments, not events.
    """

    def __init__(self, config):
        """
        Initialize segmenter.

        Args:
            config: RFConfig instance
        """
        self.config = config
        self._cache = {}

    def process(self, iq_chunk: np.ndarray) -> List[Dict[str, Any]]:
        """
        Segment IQ chunk into frequency regions.

        Args:
            iq_chunk: Complex IQ samples

        Returns:
            List of frequency segments, each with:
            - low_hz: Lower frequency edge
            - high_hz: Upper frequency edge
            - center_hz: Weighted centroid frequency
            - bandwidth_hz: Occupied bandwidth
            - confidence: Segment confidence (0.0 to 1.0)
        """
        fs = float(self.config.sample_rate)

        # Use a fixed FFT size for performance and consistent UI.
        # This keeps CPU bounded even if chunk_size is large.
        n_in = int(len(iq_chunk))
        n_fft = int(min(n_in, int(getattr(self.config, "fft_size", n_in))))
        if n_fft <= 0:
            return []

        x = iq_chunk[-n_fft:]

        cache_key = (n_fft, fs)
        cached = self._cache.get(cache_key)
        if cached is None:
            window = np.hanning(n_fft).astype(np.float32)
            freqs = np.fft.fftshift(np.fft.fftfreq(n_fft, d=1.0 / fs)).astype(np.float64)
            self._cache[cache_key] = (window, freqs)
        else:
            window, freqs = cached

        # 1. Window and FFT
        windowed = x * window
        fft = np.fft.fftshift(np.fft.fft(windowed))

        # 2. PSD in dB
        psd = 10 * np.log10(np.abs(fft) ** 2 + 1e-20)

        # Optional light smoothing to suppress single-bin stochastic spikes.
        smooth_bins = int(getattr(self.config, "psd_smooth_bins", 1) or 1)
        if smooth_bins > 1:
            k = np.ones(smooth_bins, dtype=np.float32) / float(smooth_bins)
            psd = np.convolve(psd, k, mode="same")

        # 5. Frequency vector (baseband Hz).
        # Precomputed via fftfreq/fftshift for correct bin centers.

        # Expose last_psd for UI/engine
        self.last_psd = (freqs, psd)

        # 3. Noise floor (lower percentile approximates baseline even when
        # parts of the band are occupied by signals).
        noise_floor = np.percentile(psd, 30)

        # 4. Threshold (binary spectrum mask)
        mask = psd > (noise_floor + self.config.bw_threshold_db)

        # Minimum segment width (bins): suppress 1-bin noise spikes.
        min_bins = max(
            int(getattr(self.config, "min_bw_bins", 1) or 1),
            int(getattr(self.config, "min_segment_bins", 3) or 3),
        )

        # 6. Contiguous bin grouping
        segments = []
        in_seg = False
        start = 0

        for i, val in enumerate(mask):
            if val and not in_seg:
                # Start of segment
                in_seg = True
                start = i
            elif not val and in_seg:
                # End of segment
                end = i
                if end - start >= min_bins:
                    seg = self._make_segment(psd, freqs, start, end)
                    if seg is not None:
                        seg["bins"] = int(end - start)
                        # Require peak to exceed the threshold by an additional margin.
                        thr = float(noise_floor + float(self.config.bw_threshold_db))
                        peak = float(seg.get("peak_db", -1e9))
                        narrow_bins = int(getattr(self.config, "narrow_segment_max_bins", 6) or 6)
                        prom = float(getattr(self.config, "segment_peak_prominence_db", 0.0) or 0.0)
                        prom_n = float(getattr(self.config, "segment_peak_prominence_narrow_db", prom) or prom)
                        required = prom_n if int(end - start) <= narrow_bins else prom
                        if (peak - thr) >= required:
                            segments.append(seg)
                in_seg = False

        # Handle segment extending to end
        if in_seg:
            end = n_fft
            if end - start >= min_bins:
                seg = self._make_segment(psd, freqs, start, end)
                if seg is not None:
                    seg["bins"] = int(end - start)
                    thr = float(noise_floor + float(self.config.bw_threshold_db))
                    peak = float(seg.get("peak_db", -1e9))
                    narrow_bins = int(getattr(self.config, "narrow_segment_max_bins", 6) or 6)
                    prom = float(getattr(self.config, "segment_peak_prominence_db", 0.0) or 0.0)
                    prom_n = float(getattr(self.config, "segment_peak_prominence_narrow_db", prom) or prom)
                    required = prom_n if int(end - start) <= narrow_bins else prom
                    if (peak - thr) >= required:
                        segments.append(seg)

        return segments

    def _make_segment(
        self, psd: np.ndarray, freqs: np.ndarray, start: int, end: int
    ) -> Dict[str, Any]:
        """
        Create frequency segment from bin range.

        Args:
            psd: Power spectral density (dB)
            freqs: Frequency vector
            start: Start bin index
            end: End bin index

        Returns:
            Segment dictionary
        """
        psd_db = psd[start:end]
        f = freqs[start:end]
        if len(f) == 0:
            return None

        # Bin spacing (Hz). freqs are bin centers after fftshift(fftfreq).
        if len(freqs) >= 2:
            bin_hz = float(abs(freqs[1] - freqs[0]))
        else:
            bin_hz = 0.0

        # Convert dB back to linear for proper weighted centroid
        power_linear = 10 ** (psd_db / 10)
        
        # Weighted centroid for center frequency
        center = np.sum(f * power_linear) / (np.sum(power_linear) + 1e-20)

        # Peak power in segment
        peak_db = np.max(psd_db)

        # Simple confidence based on segment width
        # More bins = higher confidence
        confidence = min(1.0, len(f) / 10.0)

        # Compute edges as true band edges (not just bin centers).
        # For a 1-bin segment, bandwidth should be ~1 bin, not 0.
        if len(f) > 0 and bin_hz > 0.0:
            low_edge = float(f[0] - bin_hz / 2.0)
            high_edge = float(f[-1] + bin_hz / 2.0)
            bandwidth_hz = float(max(bin_hz, (end - start) * bin_hz))
        elif len(f) > 0:
            low_edge = float(f[0])
            high_edge = float(f[-1])
            bandwidth_hz = float(max(0.0, high_edge - low_edge))
        else:
            low_edge = 0.0
            high_edge = 0.0
            bandwidth_hz = 0.0

        return {
            "low_hz": float(low_edge),
            "high_hz": float(high_edge),
            "center_hz": float(center),
            "bandwidth_hz": float(bandwidth_hz),
            "confidence": float(confidence),
            "peak_db": float(peak_db),
        }

    def reset(self) -> None:
        """Reset segmenter state (currently stateless)."""
        pass
