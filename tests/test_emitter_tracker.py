import pytest

from core.emitter_tracker import EmitterTracker, EmitterTrackerConfig
from core.event import SignalEvent
from core.feature_extractor import FeatureExtractor


def _make_closed_event(event_id: str, start_ts: float, end_ts: float, f_hz: float, bw_hz: float, p_db: float) -> SignalEvent:
    ev = SignalEvent(id=event_id, start_time=start_ts)
    # 10 samples of "within-event" observations
    for i in range(10):
        ev.center_freq_history.append(float(f_hz) + i * 100.0)  # tiny drift
        ev.bandwidth_history.append(float(bw_hz))
        ev.power_history.append(float(p_db))
        ev.timestamp_history.append(start_ts + (end_ts - start_ts) * (i / 10.0))
        ev.present_history.append(True)
        ev.hit_count += 1

    ev.close(end_ts)
    ev.features = FeatureExtractor().extract(ev)
    return ev


def test_emitter_association_same_source():
    cfg = EmitterTrackerConfig(
        f_gate_hz=300e3,
        bw_gate_hz=2e6,
        p_gate_db=40.0,
        timeout_s=10.0,
        wf=5.0,
        wb=2.0,
        wp=1.0,
        wt=1.0,
        distance_threshold=3.0,
        emitter_timeout_s=60.0,
    )
    trk = EmitterTracker(cfg)

    e1 = _make_closed_event("e1", 0.0, 0.5, 2.412e9, 20e6, 12.0)
    em1 = trk.process_closed_event(e1)
    assert em1 is not None

    e2 = _make_closed_event("e2", 0.7, 1.2, 2.41215e9, 20e6, 8.0)  # within 150 kHz
    em2 = trk.process_closed_event(e2)

    assert em2 is not None
    assert em2.id == em1.id
    assert em2.event_count == 2


def test_emitter_association_wideband_center_jitter():
    """Wideband channels can have center estimates that wander inside the BW.

    Even with a small absolute f_gate_hz, the tracker should associate using
    bandwidth-scaled gates / overlap gating.
    """
    cfg = EmitterTrackerConfig(
        f_gate_hz=250e3,
        bw_gate_hz=1.5e6,
        p_gate_db=40.0,
        timeout_s=10.0,
        distance_threshold=3.5,
        emitter_timeout_s=60.0,
        # Keep defaults for wideband robustness (f_gate_bw_factor, overlap)
    )
    trk = EmitterTracker(cfg)

    e1 = _make_closed_event("e1", 0.0, 0.5, 2.412e9, 20e6, 12.0)
    em1 = trk.process_closed_event(e1)
    assert em1 is not None

    # 2 MHz shift inside a 20 MHz channel => heavy overlap, should still match.
    e2 = _make_closed_event("e2", 0.7, 1.2, 2.414e9, 20e6, 11.0)
    em2 = trk.process_closed_event(e2)

    assert em2 is not None
    assert em2.id == em1.id
    assert em2.event_count == 2


def test_emitter_birth_for_far_frequency():
    cfg = EmitterTrackerConfig(
        f_gate_hz=100e3,
        bw_gate_hz=2e6,
        p_gate_db=40.0,
        timeout_s=10.0,
        distance_threshold=3.0,
        emitter_timeout_s=60.0,
    )
    trk = EmitterTracker(cfg)

    e1 = _make_closed_event("e1", 0.0, 0.5, 2.412e9, 20e6, 10.0)
    em1 = trk.process_closed_event(e1)

    e2 = _make_closed_event("e2", 0.7, 1.2, 2.437e9, 20e6, 10.0)  # 25 MHz away
    em2 = trk.process_closed_event(e2)

    assert em1 is not None and em2 is not None
    assert em1.id != em2.id


def test_emitter_timeout_creates_new_identity():
    cfg = EmitterTrackerConfig(
        f_gate_hz=300e3,
        bw_gate_hz=2e6,
        p_gate_db=40.0,
        timeout_s=2.0,
        distance_threshold=3.0,
        emitter_timeout_s=60.0,
    )
    trk = EmitterTracker(cfg)

    e1 = _make_closed_event("e1", 0.0, 0.5, 2.412e9, 20e6, 10.0)
    em1 = trk.process_closed_event(e1)

    # Same frequency but too late for association (dt > timeout_s)
    e2 = _make_closed_event("e2", 10.0, 10.5, 2.412e9, 20e6, 10.0)
    em2 = trk.process_closed_event(e2)

    assert em1 is not None and em2 is not None
    assert em1.id != em2.id
