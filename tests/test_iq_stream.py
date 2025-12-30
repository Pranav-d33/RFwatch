"""
Sanity tests for IQStream - the data spine.

MANDATORY: This must work perfectly before moving forward.
Everything else depends on this.
"""

import unittest
import numpy as np
import time
import threading
from core.iq_stream import IQStream


class TestIQStreamBasic(unittest.TestCase):
    """Basic IQStream functionality tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.stream = IQStream(max_chunks=10)

    def test_initialization(self):
        """Test stream initializes correctly."""
        self.assertEqual(self.stream.size(), 0)

    def test_push_and_pop_single(self):
        """Test single push and pop."""
        chunk = np.random.randn(2048).astype(np.complex64)
        self.stream.push(chunk)
        popped = self.stream.pop(timeout=1.0)
        self.assertIsNotNone(popped)
        np.testing.assert_array_equal(popped, chunk)

    def test_pop_empty_returns_none(self):
        """Test pop on empty stream returns None."""
        result = self.stream.pop(timeout=0.01)
        self.assertIsNone(result)

    def test_multiple_push_pop(self):
        """Test multiple push/pop operations."""
        chunks = [
            np.random.randn(2048).astype(np.complex64) for _ in range(5)
        ]

        for chunk in chunks:
            self.stream.push(chunk)

        for expected in chunks:
            popped = self.stream.pop(timeout=1.0)
            self.assertIsNotNone(popped)
            np.testing.assert_array_equal(popped, expected)

    def test_fifo_order(self):
        """Test FIFO order is maintained."""
        chunk1 = np.ones(2048, dtype=np.complex64)
        chunk2 = np.ones(2048, dtype=np.complex64) * 2
        chunk3 = np.ones(2048, dtype=np.complex64) * 3

        self.stream.push(chunk1)
        self.stream.push(chunk2)
        self.stream.push(chunk3)

        p1 = self.stream.pop(timeout=1.0)
        p2 = self.stream.pop(timeout=1.0)
        p3 = self.stream.pop(timeout=1.0)

        np.testing.assert_array_equal(p1, chunk1)
        np.testing.assert_array_equal(p2, chunk2)
        np.testing.assert_array_equal(p3, chunk3)

    def test_size_tracking(self):
        """Test size tracking."""
        self.assertEqual(self.stream.size(), 0)

        chunk = np.random.randn(2048).astype(np.complex64)
        self.stream.push(chunk)
        self.assertEqual(self.stream.size(), 1)

        self.stream.push(chunk)
        self.assertEqual(self.stream.size(), 2)

        self.stream.pop(timeout=1.0)
        self.assertEqual(self.stream.size(), 1)


class TestIQStreamBackpressure(unittest.TestCase):
    """Test backpressure handling when buffer is full."""

    def setUp(self):
        """Set up test fixtures."""
        self.stream = IQStream(max_chunks=3)

    def test_overflow_drops_oldest(self):
        """Test that overflow drops oldest data (real-time priority)."""
        chunk1 = np.ones(2048, dtype=np.complex64) * 1
        chunk2 = np.ones(2048, dtype=np.complex64) * 2
        chunk3 = np.ones(2048, dtype=np.complex64) * 3
        chunk4 = np.ones(2048, dtype=np.complex64) * 4
        chunk5 = np.ones(2048, dtype=np.complex64) * 5

        # Fill to max
        self.stream.push(chunk1)
        self.stream.push(chunk2)
        self.stream.push(chunk3)
        self.assertEqual(self.stream.size(), 3)

        # Push beyond max (should drop oldest, keep newest)
        self.stream.push(chunk4)
        self.assertEqual(self.stream.size(), 3)

        # Pop and verify chunk1 was dropped
        p1 = self.stream.pop(timeout=1.0)
        np.testing.assert_array_equal(p1, chunk2)

        p2 = self.stream.pop(timeout=1.0)
        np.testing.assert_array_equal(p2, chunk3)

        p3 = self.stream.pop(timeout=1.0)
        np.testing.assert_array_equal(p3, chunk4)

        # One more overflow
        self.stream.push(chunk5)
        p4 = self.stream.pop(timeout=1.0)
        np.testing.assert_array_equal(p4, chunk5)


class TestIQStreamThreadSafety(unittest.TestCase):
    """Test thread-safety with concurrent push/pop."""

    def setUp(self):
        """Set up test fixtures."""
        self.stream = IQStream(max_chunks=50)

    def test_producer_consumer_threads(self):
        """Test concurrent producer and consumer threads."""
        results = []
        chunk_count = 20

        def producer():
            for i in range(chunk_count):
                chunk = np.ones(2048, dtype=np.complex64) * i
                self.stream.push(chunk)
                time.sleep(0.001)

        def consumer():
            for _ in range(chunk_count):
                chunk = self.stream.pop(timeout=2.0)
                if chunk is not None:
                    results.append(chunk[0].real)

        producer_thread = threading.Thread(target=producer)
        consumer_thread = threading.Thread(target=consumer)

        consumer_thread.start()
        producer_thread.start()

        producer_thread.join()
        consumer_thread.join()

        # All chunks should have been consumed
        self.assertEqual(len(results), chunk_count)
        self.assertEqual(self.stream.size(), 0)

    def test_concurrent_producers(self):
        """Test multiple concurrent producers."""
        results = []
        chunk_count = 10
        producer_count = 3

        def producer(producer_id):
            for i in range(chunk_count):
                chunk = np.ones(2048, dtype=np.complex64) * (producer_id * 100 + i)
                self.stream.push(chunk)
                time.sleep(0.001)

        def consumer():
            total_expected = chunk_count * producer_count
            for _ in range(total_expected):
                chunk = self.stream.pop(timeout=2.0)
                if chunk is not None:
                    results.append(chunk[0].real)

        threads = []
        for pid in range(producer_count):
            t = threading.Thread(target=producer, args=(pid,))
            threads.append(t)

        consumer_thread = threading.Thread(target=consumer)
        consumer_thread.start()

        for t in threads:
            t.start()

        for t in threads:
            t.join()
        consumer_thread.join()

        # All chunks should have been consumed
        self.assertEqual(len(results), chunk_count * producer_count)
        self.assertEqual(self.stream.size(), 0)


class TestIQStreamClear(unittest.TestCase):
    """Test stream clearing."""

    def setUp(self):
        """Set up test fixtures."""
        self.stream = IQStream(max_chunks=10)

    def test_clear_empties_stream(self):
        """Test clear empties the stream."""
        chunk = np.random.randn(2048).astype(np.complex64)
        self.stream.push(chunk)
        self.stream.push(chunk)
        self.stream.push(chunk)

        self.assertEqual(self.stream.size(), 3)

        self.stream.clear()
        self.assertEqual(self.stream.size(), 0)

        result = self.stream.pop(timeout=0.01)
        self.assertIsNone(result)


class TestIQStreamInvalidInput(unittest.TestCase):
    """Test handling of invalid inputs."""

    def setUp(self):
        """Set up test fixtures."""
        self.stream = IQStream(max_chunks=10)

    def test_push_non_numpy_ignored(self):
        """Test pushing non-numpy data is ignored."""
        self.stream.push([1, 2, 3])  # List instead of ndarray
        self.assertEqual(self.stream.size(), 0)

        result = self.stream.pop(timeout=0.01)
        self.assertIsNone(result)


class TestIQStreamCopyBehavior(unittest.TestCase):
    """Test that data is copied properly to prevent external modification."""

    def setUp(self):
        """Set up test fixtures."""
        self.stream = IQStream(max_chunks=10)

    def test_push_copies_data(self):
        """Test that push copies data."""
        original = np.ones(2048, dtype=np.complex64)
        self.stream.push(original)

        # Modify original
        original[0] = 999

        # Pop should have original value
        popped = self.stream.pop(timeout=1.0)
        self.assertEqual(popped[0], 1.0)

    def test_pop_returns_data_not_reference(self):
        """Test that data is independent after pop."""
        chunk1 = np.ones(2048, dtype=np.complex64)
        self.stream.push(chunk1)

        popped1 = self.stream.pop(timeout=1.0)
        popped1[0] = 999

        # Should not affect future chunks
        chunk2 = np.ones(2048, dtype=np.complex64)
        self.stream.push(chunk2)
        popped2 = self.stream.pop(timeout=1.0)

        self.assertEqual(popped2[0], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
