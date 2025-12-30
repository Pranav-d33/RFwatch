"""
Extract features from completed events.

Responsibilities:
- Consume completed events
- Extract feature schema

No streaming logic.
Pure computation.
"""

import numpy as np
from typing import Dict, Any
from .event import SignalEvent
from utils.stats import compute_stats


class FeatureExtractor:
    """Extracts signal features from completed events."""


    def extract(self, event: SignalEvent) -> Dict[str, Any]:
        # Ensure event is properly closed
        if event.end_time is None:
            raise ValueError("Feature extraction requires a closed event with end_time set")

        features = {}
        duration_s = event.end_time - event.start_time
        center_freq_history = event.center_freq_history
        bandwidth_history = event.bandwidth_history
        power_history = event.power_history
        ts_history = getattr(event, "timestamp_history", [])
        present_history = getattr(event, "present_history", [])

        features["meta"] = self._extract_meta(event, duration_s)
        features["frequency"] = self._extract_frequency(event, duration_s, center_freq_history, power_history)
        features["bandwidth"] = self._extract_bandwidth(bandwidth_history)
        features["time_structure"] = self._extract_time_structure(event, duration_s, ts_history, present_history)
        features["power"], features["noise"] = self._extract_power_noise(power_history)
        features["signal_dynamics"] = self._extract_signal_dynamics(power_history, duration_s)
        features["stability"] = self._extract_stability(features)
        features["confidence"] = self._extract_confidence(features)

        return features

    def _extract_meta(self, event, duration_s):
        return {
            "start_time": event.start_time,
            "end_time": event.end_time,
            "duration_s": duration_s,
            "chunks_seen": event.hit_count,
            "relative_units": True
        }

    def _extract_frequency(self, event, duration_s, center_freq_history, power_history):
        center_hz = float(np.mean(center_freq_history)) if center_freq_history else 0.0
        times = np.linspace(0, duration_s, len(center_freq_history)) if center_freq_history else []
        slope = 0.0
        if len(center_freq_history) > 1:
            # If the frequency is effectively constant, avoid numerical noise.
            try:
                if float(np.std(center_freq_history)) < 1e-9:
                    slope = 0.0
                else:
                    slope = 0.0
                    # Avoid hard dependency on scipy; np.polyfit is sufficient here.
                    try:
                        slope = float(np.polyfit(times, center_freq_history, 1)[0])
                    except Exception:
                        slope = 0.0
            except Exception:
                slope = 0.0
        cfo = center_hz - float(np.median(center_freq_history)) if center_freq_history else 0.0

        # Peak frequency: center frequency at max observed power (if aligned histories).
        peak_hz = 0.0
        if center_freq_history and power_history and len(center_freq_history) == len(power_history):
            try:
                peak_idx = int(np.argmax(power_history))
                peak_hz = float(center_freq_history[peak_idx])
            except Exception:
                peak_hz = float(center_hz)
        elif center_freq_history:
            peak_hz = float(np.max(center_freq_history))

        return {
            "center_hz": center_hz,
            "peak_hz": peak_hz,
            "drift_hz_per_s": slope,
            "cfo_rel": cfo
        }

    def _extract_bandwidth(self, bandwidth_history):
        bw_hz = float(np.mean(bandwidth_history)) if bandwidth_history else 0.0
        bw_std = float(np.std(bandwidth_history)) if bandwidth_history else 0.0
        unstable = (bw_std / bw_hz > 0.3) if bw_hz > 0 else False
        return {
            "mean_hz": bw_hz,
            "std_hz": bw_std,
            "min_hz": float(np.min(bandwidth_history)) if bandwidth_history else 0.0,
            "max_hz": float(np.max(bandwidth_history)) if bandwidth_history else 0.0,
            "var_hz2": float(np.var(bandwidth_history)) if bandwidth_history else 0.0,
            "unstable": unstable
        }

    def _extract_time_structure(self, event, duration_s, ts_history, present_history):
        burst_type = "continuous" if event.miss_count == 0 else "bursty"
        total = event.hit_count + event.miss_count
        duty_cycle = event.hit_count / total if total > 0 else 0.0

        avg_burst_s = 0.0
        avg_gap_s = 0.0
        if ts_history and present_history and len(ts_history) == len(present_history):
            # Compute contiguous run lengths using timestamps.
            burst_lengths = []
            gap_lengths = []
            run_state = present_history[0]
            run_start_t = float(ts_history[0])
            for t, present in zip(ts_history[1:], present_history[1:]):
                t = float(t)
                if bool(present) != bool(run_state):
                    run_len = max(0.0, t - run_start_t)
                    if run_state:
                        burst_lengths.append(run_len)
                    else:
                        gap_lengths.append(run_len)
                    run_state = bool(present)
                    run_start_t = t

            # Close last run at event end.
            last_end = float(event.end_time) if event.end_time is not None else float(ts_history[-1])
            run_len = max(0.0, last_end - run_start_t)
            if run_state:
                burst_lengths.append(run_len)
            else:
                gap_lengths.append(run_len)

            if burst_lengths:
                avg_burst_s = float(np.mean(burst_lengths))
            if gap_lengths:
                avg_gap_s = float(np.mean(gap_lengths))

        return {
            "burst_type": burst_type,
            "duty_cycle": duty_cycle,
            "avg_burst_s": avg_burst_s,
            "avg_gap_s": avg_gap_s,
        }

    def _extract_power_noise(self, power_history):
        avg_power = float(np.mean(power_history)) if power_history else 0.0
        peak_power = float(np.max(power_history)) if power_history else 0.0
        papr = peak_power - avg_power
        noise_floor = float(np.percentile(power_history, 20)) if power_history else 0.0
        # If power is perfectly constant, treat SNR as high
        if np.std(power_history) < 1e-6:
            snr = 100.0
        else:
            snr = avg_power - noise_floor
        power = {
            "avg_power": avg_power,
            "peak_power": peak_power,
            "papr": papr
        }
        noise = {
            "noise_floor": noise_floor,
            "snr": snr
        }
        return power, noise

    def _extract_signal_dynamics(self, power_history, duration_s):
        power_var = float(np.var(power_history)) if power_history else 0.0
        fading = "unknown"
        if duration_s < 0.2 and power_var > 0.5:
            fading = "fast"
        elif duration_s >= 0.2 and power_var < 0.2:
            fading = "slow"
        return {
            "power_var": power_var,
            "fading": fading
        }

    def _extract_stability(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Honest stability score derived from drift + variance (0..1)."""
        drift = abs(float(features.get("frequency", {}).get("drift_hz_per_s", 0.0)))
        bw_mean = float(features.get("bandwidth", {}).get("mean_hz", 0.0))
        bw_std = float(features.get("bandwidth", {}).get("std_hz", 0.0))

        # Normalize drift using a gentle scale: 1 kHz/s is "very unstable".
        drift_score = max(0.0, min(1.0, 1.0 - (drift / 1000.0)))

        # Normalize bandwidth stability by coefficient of variation.
        if bw_mean > 0:
            bw_score = max(0.0, min(1.0, 1.0 - (bw_std / bw_mean)))
        else:
            bw_score = 0.0

        score = float(0.6 * drift_score + 0.4 * bw_score)
        return {
            "score": max(0.0, min(1.0, score)),
            "notes": "derived from drift + bandwidth variance",
        }

    def _extract_confidence(self, features):
        # Frequency confidence
        snr = features["noise"]["snr"]
        bw_std = features["bandwidth"]["std_hz"]
        bw_hz = features["bandwidth"]["mean_hz"]
        avg_power = features["power"]["avg_power"]
        # Clamp stability_factor to [0, 1]
        stability_factor = 1.0 if bw_hz == 0 else max(0.0, min(1.0, 1 - (bw_std / bw_hz)))
        # If average power is very low, confidence should be low
        if avg_power < 1e-3:
            freq_conf = 0.0
        else:
            freq_conf = min(1.0, max(0.0, snr / 5.0)) * stability_factor
        freq_conf = max(0.0, min(1.0, freq_conf))
        return {
            "frequency": freq_conf
        }
