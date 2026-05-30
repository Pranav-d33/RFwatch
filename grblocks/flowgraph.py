# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

"""
GNU Radio flowgraph builder.

Builds the minimal flowgraph:
    src → dc_block → iq_source_block

Hardware abstraction lives here.
"""

try:
    from gnuradio import gr, filter
    from gnuradio import blocks
    import osmosdr
    GR_AVAILABLE = True
except ImportError:
    GR_AVAILABLE = False

import os
import threading
import time
import numpy as np


class _IQStreamPuller:
    """Pull fixed-size IQ chunks from a GNU Radio vector sink into IQStream."""

    def __init__(self, iq_stream, sink, chunk_size: int, poll_sleep_s: float = 0.002):
        self._iq_stream = iq_stream
        self._sink = sink
        self._chunk_size = int(chunk_size)
        self._poll_sleep_s = float(poll_sleep_s)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="IQStreamPuller", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 1.0):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout_s)

    def _run(self):
        # Reset once at start to avoid stale data.
        try:
            self._sink.reset()
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                data = self._sink.data()
                if data and len(data) >= self._chunk_size:
                    chunk = np.asarray(data[-self._chunk_size :], dtype=np.complex64)
                    self._iq_stream.push(chunk)
                    self._sink.reset()
            except Exception:
                # If anything goes wrong, back off slightly.
                time.sleep(0.01)
            time.sleep(self._poll_sleep_s)


class HackRFFlowgraph:
    """Wrapper that presents top_block-like start/stop/wait methods.

    Also exposes safe runtime setters for HackRF parameters.
    """

    def __init__(
        self,
        tb,
        puller: _IQStreamPuller | None = None,
        src=None,
    ):
        self._tb = tb
        self._puller = puller
        self._src = src
        self._src_lock = threading.RLock()

    def start(self):
        self._tb.start()
        if self._puller:
            self._puller.start()

    def stop(self):
        if self._puller:
            self._puller.stop()
        self._tb.stop()

    def wait(self):
        self._tb.wait()

    def set_gain(self, gain_db: float, chan: int = 0) -> bool:
        """Best-effort runtime gain update; returns True on success."""
        if self._src is None:
            return False
        try:
            with self._src_lock:
                self._src.set_gain(float(gain_db), int(chan))
            return True
        except Exception:
            return False

    def set_center_freq(self, center_freq_hz: float, chan: int = 0) -> bool:
        """Best-effort runtime retune; returns True on success."""
        if self._src is None:
            return False
        try:
            with self._src_lock:
                self._src.set_center_freq(float(center_freq_hz), int(chan))
            return True
        except Exception:
            return False

    def set_sample_rate(self, sample_rate_hz: float) -> bool:
        """Best-effort runtime sample-rate update; returns True on success."""
        if self._src is None:
            return False
        try:
            with self._src_lock:
                self._src.set_sample_rate(float(sample_rate_hz))
            return True
        except Exception:
            return False


def build_flowgraph(config, iq_stream):
    """
    Build minimal GNU Radio flowgraph with HackRF.

    Chain: src → dc_blocker → iq_source_block

    Args:
        config: RFConfig instance
        iq_stream: IQStream instance

    Returns:
        Flowgraph (top_block) object
    """
    if not GR_AVAILABLE:
        raise RuntimeError("GNU Radio is not available")

    tb = gr.top_block()

    try:
        # HackRF source args.
        # IMPORTANT: do NOT enable bias-tee by default; some clone devices
        # segfault or misbehave when bias_t is set.
        hackrf_args = os.getenv("RFWATCH_HACKRF_ARGS", "numchan=1 hackrf=0")
        if os.getenv("RFWATCH_HACKRF_BIAS_T", "").lower() in {"1", "true", "yes", "on"}:
            if "bias_t=" not in hackrf_args:
                hackrf_args = hackrf_args + ",bias_t=1"

        src = osmosdr.source(args=hackrf_args)

        # Set basic parameters
        src.set_sample_rate(config.sample_rate)
        src.set_center_freq(config.center_freq)
        src.set_gain(config.gain, 0)

        print(
            f"[FLOWGRAPH] HackRF configured: "
            f"{config.center_freq/1e6:.0f} MHz, "
            f"{config.sample_rate/1e6:.0f} MS/s, {config.gain} dB"
        )

    except Exception as e:
        print(f"[FLOWGRAPH] Error configuring HackRF: {e}")
        raise

    # DC blocker
    dc = filter.dc_blocker_cc(32, True)

    # Use a C++ sink to avoid segfaults seen with Python sink blocks on some
    # HackRF/gr-osmosdr setups. Pull IQ into IQStream from Python.
    sink = blocks.vector_sink_c(1)

    try:
        tb.connect(src, dc, sink)
    except Exception as e:
        print(f"[FLOWGRAPH] Error connecting flowgraph: {e}")
        raise

    puller = _IQStreamPuller(iq_stream=iq_stream, sink=sink, chunk_size=config.chunk_size)
    return HackRFFlowgraph(tb, puller=puller, src=src)


def build_test_flowgraph(config, iq_stream):
    """
    Build flowgraph with null source for testing (no hardware needed).

    Args:
        config: RFConfig instance
        iq_stream: IQStream instance

    Returns:
        Flowgraph (top_block) object
    """
    if not GR_AVAILABLE:
        raise RuntimeError("GNU Radio is not available")

    from .iq_source_block import IQSourceBlock

    tb = gr.top_block()

    # Null source (generates zeros)
    src = blocks.null_source(gr.sizeof_gr_complex)

    # DC blocker
    dc = filter.dc_blocker_cc(32, True)

    # IQ sink block
    iq_sink = IQSourceBlock(iq_stream=iq_stream, chunk_size=config.chunk_size)

    # Connect
    tb.connect(src, dc, iq_sink)

    return tb
