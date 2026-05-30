# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

from PySide6.QtCore import QObject, Signal


class PSDPublisher(QObject):
    """Qt signal bridge for PSD snapshots from the engine to the UI."""

    snapshot_ready = Signal(dict)

    def __init__(self, parent=None):
        # Ensure QObject is properly initialised to avoid undefined
        # behaviour or crashes when emitting signals across threads.
        super().__init__(parent)

    def publish(self, snapshot: dict):
        self.snapshot_ready.emit(snapshot)
