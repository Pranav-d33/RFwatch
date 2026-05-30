# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

"""
Transmission Thread - Handles RF transmission using GNU Radio.
"""

import time
from PySide6.QtCore import QThread

# GNU Radio / SDR Imports (optional)
try:
    from gnuradio import gr, analog, blocks
    import osmosdr
    GNU_RADIO_AVAILABLE = True
except ImportError:
    GNU_RADIO_AVAILABLE = False


class TxThread(QThread):
    def __init__(self, freq_hz, noise_amp=0.1):
        super().__init__()
        self.freq_hz = freq_hz
        self.noise_amp = noise_amp
        self.tb = None
        self._stop_event = False

    def stop_transmission(self):
        """Stop the transmission safely."""
        self._stop_event = True
        if self.tb:
            try:
                self.tb.stop()
                self.tb.wait()
            except Exception as e:
                print(f"Error stopping GNU Radio flowgraph: {e}")
        # Request thread interruption as fallback
        self.requestInterruption()

    def run(self):
        if not GNU_RADIO_AVAILABLE:
            print("GNU Radio not available, transmission disabled")
            return

        try:
            self.tb = gr.top_block()
            
            # Simple noise source for jamming (as in reference)
            src_noise = analog.noise_source_c(analog.GR_GAUSSIAN, self.noise_amp, 0)
            
            # Optional: Add a tone for testing
            src_tone = analog.sig_source_c(2e6, analog.GR_SIN_WAVE, 1000, 0.1, 0)
            adder = blocks.add_vcc(1)
            
            sink = osmosdr.sink(args="numchan=1 hackrf=0")
            sink.set_sample_rate(2e6)
            sink.set_center_freq(self.freq_hz, 0)
            sink.set_gain(40, 0)
            sink.set_if_gain(30, 0)
            sink.set_bb_gain(20, 0)
            
            # Connect: noise + tone -> sink
            self.tb.connect(src_tone, (adder, 0))
            self.tb.connect(src_noise, (adder, 1))
            self.tb.connect(adder, sink)
            
            self.tb.start()
            while not self._stop_event and not self.isInterruptionRequested():
                time.sleep(0.05)
            
            # Ensure clean shutdown
            if self.tb:
                self.tb.stop()
                self.tb.wait()
            
        except Exception as e:
            print(f"Transmission error: {e}")
        finally:
            self.tb = None