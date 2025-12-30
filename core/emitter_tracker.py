"""Emitter tracking (identity inference) over closed events.

This implements a deterministic, explainable tracking layer:
- Each closed event becomes one observation in feature space
- Observations are associated to existing emitter hypotheses via gating
- Nearest-neighbor assignment with weighted distance
- Birth / update / death lifecycle for emitters

This intentionally does *not* attempt protocol ID, classification, or ML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import math


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass
class RunningStats:
    """Online mean/variance via Welford."""

    n: int = 0
    mean: float = 0.0
    m2: float = 0.0
    min_v: float = float("inf")
    max_v: float = float("-inf")

    def update(self, x: float) -> None:
        x = float(x)
        self.n += 1
        if x < self.min_v:
            self.min_v = x
        if x > self.max_v:
            self.max_v = x
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    @property
    def var(self) -> float:
        if self.n < 2:
            return 0.0
        return self.m2 / (self.n - 1)

    @property
    def std(self) -> float:
        return math.sqrt(max(0.0, self.var))


@dataclass
class Emitter:
    """Inferred emitter hypothesis."""

    id: str
    created_ts: float
    last_update_ts: float
    active: bool = True

    # Aggregates
    freq_hz: RunningStats = field(default_factory=RunningStats)
    bw_hz: RunningStats = field(default_factory=RunningStats)
    power_db: RunningStats = field(default_factory=RunningStats)
    power_var: RunningStats = field(default_factory=RunningStats)
    duty_cycle: RunningStats = field(default_factory=RunningStats)

    total_event_duration_s: float = 0.0
    event_count: int = 0

    # For UI/detail reuse: event-level histories (one sample per event)
    center_freq_history: List[float] = field(default_factory=list)
    bandwidth_history: List[float] = field(default_factory=list)
    power_history: List[float] = field(default_factory=list)
    timestamp_history: List[float] = field(default_factory=list)

    # References to contributing events
    event_ids: List[str] = field(default_factory=list)

    # Feature schema compatible with UI detail view
    features: Dict = field(default_factory=dict)

    end_time: Optional[float] = None

    def lifetime_s(self, now_ts: Optional[float] = None) -> float:
        now = float(self.last_update_ts if now_ts is None else now_ts)
        return max(0.0, now - float(self.created_ts))

    def activity_fraction(self, now_ts: Optional[float] = None) -> float:
        life = self.lifetime_s(now_ts)
        if life <= 1e-9:
            return 0.0
        return _clamp(self.total_event_duration_s / life, 0.0, 1.0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_ts": self.created_ts,
            "last_update_ts": self.last_update_ts,
            "end_time": self.end_time,
            "active": self.active,
            "event_count": self.event_count,
            "total_event_duration_s": self.total_event_duration_s,
            "frequency": {
                "mean_hz": self.freq_hz.mean,
                "std_hz": self.freq_hz.std,
                "min_hz": self.freq_hz.min_v if self.freq_hz.n else 0.0,
                "max_hz": self.freq_hz.max_v if self.freq_hz.n else 0.0,
            },
            "bandwidth": {
                "mean_hz": self.bw_hz.mean,
                "std_hz": self.bw_hz.std,
                "min_hz": self.bw_hz.min_v if self.bw_hz.n else 0.0,
                "max_hz": self.bw_hz.max_v if self.bw_hz.n else 0.0,
            },
            "power": {
                "avg_db_rel": self.power_db.mean,
                "std_db": self.power_db.std,
            },
            "activity": {
                "fraction": self.activity_fraction(),
            },
            "event_ids": list(self.event_ids),
            "features": self.features,
        }


@dataclass
class EmitterTrackerConfig:
    # Gating
    f_gate_hz: float = 250e3
    bw_gate_hz: float = 1.5e6
    p_gate_db: float = 25.0
    timeout_s: float = 4.0

    # Wideband robustness: expand gates proportional to observed bandwidth.
    # This helps for 2.4 GHz Wi-Fi / LTE where the segment "center" can move
    # around inside the occupied channel due to thresholding and multipath.
    f_gate_bw_factor: float = 0.25
    bw_gate_bw_factor: float = 0.50

    # If two occupied bands overlap sufficiently, allow association even if
    # centers drift outside the base f_gate_hz.
    min_overlap_fraction: float = 0.20

    # Distance weights (dimensionless, applied to normalized deltas)
    wf: float = 5.0
    wb: float = 2.0
    wp: float = 1.0
    wt: float = 1.5
    wo: float = 1.0

    # Accept if D < threshold
    # With the default weights, a "reasonable" within-gate match often lands
    # in the 1.5..3.0 range (e.g. ~0.5*f_gate with wf=5 => 2.5 by itself).
    distance_threshold: float = 3.0

    # Emitter lifecycle
    emitter_timeout_s: float = 8.0
    max_event_refs: int = 200


class EmitterTracker:
    """Tracks emitters using gated nearest-neighbor association."""

    def __init__(self, cfg: EmitterTrackerConfig, emitter_publisher=None):
        self.cfg = cfg
        self.emitter_publisher = emitter_publisher
        self._counter = 0
        self.active_emitters: Dict[str, Emitter] = {}
        self.closed_emitters: List[Emitter] = []
        self._t0: Optional[float] = None

    def reset(self) -> None:
        self._counter = 0
        self.active_emitters.clear()
        self.closed_emitters.clear()
        self._t0 = None

    def process_closed_event(self, event) -> Optional[Emitter]:
        """Consume one closed SignalEvent and update/create an emitter."""
        try:
            end_ts = float(getattr(event, "end_time"))
        except Exception:
            return None

        if self._t0 is None:
            self._t0 = end_ts

        obs = self._event_to_observation(event)
        if obs is None:
            self._expire_emitters(now_ts=end_ts)
            return None

        emitter, _ = self._associate(obs)
        if emitter is None:
            emitter = self._spawn_emitter(obs)
        else:
            self._update_emitter(emitter, obs)

        self._expire_emitters(now_ts=end_ts)

        if self.emitter_publisher is not None:
            try:
                self.emitter_publisher.emitter_updated.emit(emitter)
            except Exception:
                pass

        return emitter

    # ---------------------------------------------------------------------
    # Observation, gating, distance
    # ---------------------------------------------------------------------

    def _event_to_observation(self, event) -> Optional[dict]:
        features = getattr(event, "features", None) or {}
        if not features:
            return None

        try:
            f_center = float(features.get("frequency", {}).get("center_hz", 0.0) or 0.0)
            bw = float(features.get("bandwidth", {}).get("mean_hz", 0.0) or 0.0)
            p_mean = float(features.get("power", {}).get("avg_power", 0.0) or 0.0)
            p_var = float(features.get("signal_dynamics", {}).get("power_var", 0.0) or 0.0)
            duty = float(features.get("time_structure", {}).get("duty_cycle", 0.0) or 0.0)
            end_ts = float(getattr(event, "end_time"))
            start_ts = float(getattr(event, "start_time", end_ts) or end_ts)
            dur = max(0.0, end_ts - start_ts)
        except Exception:
            return None

        return {
            "event_id": str(getattr(event, "id", "")),
            "t": end_ts,
            "f_center": f_center,
            "bw": bw,
            "p_mean": p_mean,
            "p_var": p_var,
            "duty": duty,
            "duration_s": dur,
        }

    def _band_overlap_fraction(self, f1: float, bw1: float, f2: float, bw2: float) -> float:
        bw1 = max(0.0, float(bw1))
        bw2 = max(0.0, float(bw2))
        if bw1 <= 0.0 or bw2 <= 0.0:
            return 0.0
        low1 = float(f1) - bw1 / 2.0
        high1 = float(f1) + bw1 / 2.0
        low2 = float(f2) - bw2 / 2.0
        high2 = float(f2) + bw2 / 2.0
        inter = max(0.0, min(high1, high2) - max(low1, low2))
        # Use the smaller BW as denominator so "contained" bands score high.
        denom = max(1e-9, min(bw1, bw2))
        return _clamp(inter / denom, 0.0, 1.0)

    def _dynamic_gates(self, emitter: Emitter, obs: dict) -> Tuple[float, float]:
        obs_bw = max(1e-9, float(obs.get("bw", 0.0) or 0.0))
        em_bw = float(emitter.bw_hz.mean) if emitter.bw_hz.n else obs_bw
        em_bw = max(1e-9, em_bw)

        bw_ref = max(obs_bw, em_bw)
        freq_std = float(emitter.freq_hz.std) if emitter.freq_hz.n >= 2 else 0.0

        f_gate = max(
            float(self.cfg.f_gate_hz),
            float(self.cfg.f_gate_bw_factor) * bw_ref,
            3.0 * freq_std,
        )
        bw_gate = max(
            float(self.cfg.bw_gate_hz),
            float(self.cfg.bw_gate_bw_factor) * bw_ref,
        )
        return f_gate, bw_gate

    def _in_gate(self, emitter: Emitter, obs: dict) -> bool:
        dt = abs(float(obs["t"]) - float(emitter.last_update_ts))
        if dt > self.cfg.timeout_s:
            return False

        em_f = float(emitter.freq_hz.mean)
        em_bw = float(emitter.bw_hz.mean) if emitter.bw_hz.n else float(obs["bw"])
        df = abs(float(obs["f_center"]) - em_f)
        dbw = abs(float(obs["bw"]) - em_bw)

        f_gate, bw_gate = self._dynamic_gates(emitter, obs)

        # Standard center/BW gate.
        if df <= f_gate and dbw <= bw_gate:
            return True

        # Wideband fallback: allow association based on band overlap.
        overlap = self._band_overlap_fraction(em_f, em_bw, float(obs["f_center"]), float(obs["bw"]))
        if overlap >= float(self.cfg.min_overlap_fraction) and dbw <= (2.0 * bw_gate):
            return True

        return False

        dp = abs(float(obs["p_mean"]) - float(emitter.power_db.mean))
        if dp > self.cfg.p_gate_db:
            return False

        return True

    def _distance(self, emitter: Emitter, obs: dict) -> float:
        em_f = float(emitter.freq_hz.mean)
        em_bw = float(emitter.bw_hz.mean) if emitter.bw_hz.n else float(obs["bw"])
        df = abs(float(obs["f_center"]) - em_f)
        dbw = abs(float(obs["bw"]) - em_bw)
        dp = abs(float(obs["p_mean"]) - float(emitter.power_db.mean))
        dt = abs(float(obs["t"]) - float(emitter.last_update_ts))

        f_gate, bw_gate = self._dynamic_gates(emitter, obs)

        # Normalize to gate widths => dimensionless components
        nf = df / max(1e-9, float(f_gate))
        nbw = dbw / max(1e-9, float(bw_gate))
        np = dp / max(1e-9, float(self.cfg.p_gate_db))
        nt = dt / max(1e-9, float(self.cfg.timeout_s))

        overlap = self._band_overlap_fraction(em_f, em_bw, float(obs["f_center"]), float(obs["bw"]))
        no = 1.0 - float(overlap)

        return (
            float(self.cfg.wf) * nf
            + float(self.cfg.wb) * nbw
            + float(self.cfg.wp) * np
            + float(self.cfg.wt) * nt
            + float(self.cfg.wo) * no
        )

    def _associate(self, obs: dict) -> Tuple[Optional[Emitter], Optional[float]]:
        best: Optional[Emitter] = None
        best_d: Optional[float] = None

        for emitter in self.active_emitters.values():
            if not self._in_gate(emitter, obs):
                continue
            d = self._distance(emitter, obs)
            if best_d is None or d < best_d:
                best = emitter
                best_d = d

        if best is None:
            return None, None

        if best_d is not None and best_d < float(self.cfg.distance_threshold):
            return best, best_d

        return None, best_d

    # ---------------------------------------------------------------------
    # Lifecycle + feature aggregation
    # ---------------------------------------------------------------------

    def _spawn_emitter(self, obs: dict) -> Emitter:
        self._counter += 1
        eid = f"emitter_{self._counter:06d}"
        t = float(obs["t"])
        emitter = Emitter(id=eid, created_ts=t, last_update_ts=t, active=True)
        self.active_emitters[eid] = emitter
        self._update_emitter(emitter, obs)
        return emitter

    def _update_emitter(self, emitter: Emitter, obs: dict) -> None:
        t = float(obs["t"])
        emitter.last_update_ts = t

        emitter.freq_hz.update(float(obs["f_center"]))
        emitter.bw_hz.update(float(obs["bw"]))
        emitter.power_db.update(float(obs["p_mean"]))
        emitter.power_var.update(float(obs["p_var"]))
        emitter.duty_cycle.update(float(obs["duty"]))

        emitter.total_event_duration_s += float(obs.get("duration_s", 0.0) or 0.0)
        emitter.event_count += 1

        # Histories (one per event)
        emitter.center_freq_history.append(float(obs["f_center"]))
        emitter.bandwidth_history.append(float(obs["bw"]))
        emitter.power_history.append(float(obs["p_mean"]))
        emitter.timestamp_history.append(t)

        ev_id = str(obs.get("event_id") or "")
        if ev_id:
            emitter.event_ids.append(ev_id)
            if len(emitter.event_ids) > int(self.cfg.max_event_refs):
                emitter.event_ids = emitter.event_ids[-int(self.cfg.max_event_refs):]

        # Maintain a UI-friendly feature schema compatible with EventDetailView.
        emitter.features = self._build_features(emitter)

    def _build_features(self, emitter: Emitter) -> dict:
        now_ts = float(emitter.last_update_ts)
        duration_s = emitter.lifetime_s(now_ts)
        activity = emitter.activity_fraction(now_ts)

        # "Confidence" is heuristic: more observations + stable freq => higher.
        freq_std = float(emitter.freq_hz.std)
        n = int(emitter.freq_hz.n)
        freq_stability = 1.0 - _clamp(freq_std / 250e3, 0.0, 1.0)  # 250 kHz std ~ unstable
        count_factor = _clamp(math.log10(1.0 + n) / 2.0, 0.0, 1.0)  # saturates ~100 obs
        freq_conf = _clamp(0.25 + 0.75 * (0.6 * freq_stability + 0.4 * count_factor), 0.0, 1.0)

        bw_mean = float(emitter.bw_hz.mean)
        bw_std = float(emitter.bw_hz.std)
        bw_unstable = (bw_std / bw_mean > 0.3) if bw_mean > 0 else False

        return {
            "meta": {
                "start_time": emitter.created_ts,
                "end_time": emitter.end_time,
                "duration_s": duration_s,
                "chunks_seen": emitter.event_count,
                "relative_units": True,
                "kind": "emitter",
            },
            "frequency": {
                "center_hz": float(emitter.freq_hz.mean),
                "peak_hz": float(emitter.freq_hz.max_v if emitter.freq_hz.n else 0.0),
                "drift_hz_per_s": 0.0,
                "cfo_rel": 0.0,
            },
            "bandwidth": {
                "mean_hz": float(emitter.bw_hz.mean),
                "std_hz": float(bw_std),
                "min_hz": float(emitter.bw_hz.min_v if emitter.bw_hz.n else 0.0),
                "max_hz": float(emitter.bw_hz.max_v if emitter.bw_hz.n else 0.0),
                "var_hz2": float(emitter.bw_hz.var),
                "unstable": bool(bw_unstable),
            },
            "time_structure": {
                "burst_type": "continuous" if activity > 0.8 else "bursty",
                "duty_cycle": float(activity),
                "avg_burst_s": 0.0,
                "avg_gap_s": 0.0,
            },
            "power": {
                "avg_power": float(emitter.power_db.mean),
                "peak_power": float(emitter.power_db.max_v if emitter.power_db.n else 0.0),
                "papr": float((emitter.power_db.max_v - emitter.power_db.mean) if emitter.power_db.n else 0.0),
            },
            "noise": {
                "noise_floor": 0.0,
                "snr": 0.0,
            },
            "signal_dynamics": {
                "power_var": float(emitter.power_var.mean),
                "fading": "unknown",
            },
            "stability": {
                "score": float(freq_stability),
                "notes": "derived from emitter frequency scatter",
            },
            "confidence": {
                "frequency": float(freq_conf),
            },
            "emitter": {
                "event_count": int(emitter.event_count),
                "activity_fraction": float(activity),
            },
        }

    def _expire_emitters(self, now_ts: float) -> None:
        now = float(now_ts)
        to_close: List[str] = []
        for eid, emitter in self.active_emitters.items():
            if (now - float(emitter.last_update_ts)) > float(self.cfg.emitter_timeout_s):
                to_close.append(eid)

        for eid in to_close:
            emitter = self.active_emitters.pop(eid, None)
            if emitter is None:
                continue
            emitter.active = False
            emitter.end_time = float(emitter.last_update_ts)
            emitter.features = self._build_features(emitter)
            self.closed_emitters.append(emitter)
            if self.emitter_publisher is not None:
                try:
                    self.emitter_publisher.emitter_closed.emit(emitter)
                except Exception:
                    pass
