"""
Thread-safe IQ buffer for streaming data.

This is the contract boundary between GNU Radio and Python logic.
Where GNU Radio feeds Python IQ samples.

Design goals:
- Thread-safe (no locks needed, Queue handles it)
- Bounded (avoid RAM death)
- Chunk-based
- Drop-old-data-on-overflow (real-time > perfect)

No DSP here. Ever.
"""

import queue
import numpy as np
from typing import Optional


class IQStream:
    """Thread-safe queue for IQ samples using queue.Queue."""

    def __init__(self, max_chunks: int = 100):
        """
        Initialize IQ stream buffer.

        Args:
            max_chunks: Maximum number of chunks to buffer
        """
        self.q = queue.Queue(maxsize=max_chunks)

    def push(self, iq_chunk: np.ndarray) -> None:
        """
        Push IQ samples into the stream.

        Handles backpressure by dropping oldest data if queue is full.

        Args:
            iq_chunk: numpy array of complex IQ samples
        """
        if not isinstance(iq_chunk, np.ndarray):
            return

        try:
            self.q.put_nowait(iq_chunk.copy())
        except queue.Full:
            # Drop oldest data (real-time priority)
            try:
                _ = self.q.get_nowait()
                self.q.put_nowait(iq_chunk.copy())
            except queue.Empty:
                pass

    def pop(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        """
        Pop IQ samples from the stream.

        Args:
            timeout: Maximum time to wait in seconds (default 0.1)

        Returns:
            numpy array of complex IQ samples, or None if timeout
        """
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def size(self) -> int:
        """Return current buffer size."""
        return self.q.qsize()

    def clear(self) -> None:
        """Clear all buffered data."""
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
