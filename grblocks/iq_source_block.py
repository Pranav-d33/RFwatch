# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

"""
Custom GNU Radio Python block for IQ streaming.

This block does only one thing:
- Convert streaming IQ → fixed-size chunks → push to IQStream

Key rules:
- No FFT
- No detection
- No state beyond buffering
- No output stream (sink-only)
"""

import numpy as np

try:
    from gnuradio import gr
    GR_AVAILABLE = True
except ImportError:
    GR_AVAILABLE = False


class IQSourceBlock(gr.sync_block if GR_AVAILABLE else object):
    """GNU Radio block that buffers and feeds IQ samples to application."""

    def __init__(self, iq_stream, chunk_size: int = 2048):
        """
        Initialize IQ source block.

        Args:
            iq_stream: IQStream instance to push samples into
            chunk_size: Size of chunks to buffer before pushing
        """
        if GR_AVAILABLE:
            gr.sync_block.__init__(
                self,
                name="iq_source_block",
                in_sig=[np.complex64],
                out_sig=[],
            )
        self.iq_stream = iq_stream
        self.chunk_size = chunk_size
        self.buffer = np.zeros(0, dtype=np.complex64)

    def work(self, input_items, output_items):
        """
        GNU Radio work function.

        Buffers incoming samples and pushes fixed-size chunks to IQStream.

        Args:
            input_items: Input buffers
            output_items: Output buffers (unused)

        Returns:
            Number of samples consumed
        """
        if not GR_AVAILABLE:
            return 0

        samples = input_items[0]

        # Concatenate with existing buffer
        self.buffer = np.concatenate((self.buffer, samples))

        # Push complete chunks
        while len(self.buffer) >= self.chunk_size:
            chunk = self.buffer[: self.chunk_size]
            self.buffer = self.buffer[self.chunk_size :]
            self.iq_stream.push(chunk)

        return len(samples)
